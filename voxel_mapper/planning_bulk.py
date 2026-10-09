"""Resumable park-wide PDF acquisition and page inventory, separate from geometry approval."""
import argparse
import concurrent.futures as futures
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from .acquisition import USER_AGENT


class Corpus:
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'files').mkdir(exist_ok=True)
        self.db=sqlite3.connect(self.root/'corpus.sqlite')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS downloads(url TEXT PRIMARY KEY,expected_sha TEXT,status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,sha TEXT,size INTEGER,error TEXT);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,url TEXT NOT NULL,record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pages(sha TEXT,page INTEGER,summary TEXT NOT NULL,PRIMARY KEY(sha,page));
        ''')

    def ingest(self, records, hosts):
        hosts=set(hosts)
        if not hosts:raise ValueError('Explicit official portal hosts required')
        with self.db:
            for record in records:
                parsed=urlparse(record['url'])
                if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.port not in (None,443) or parsed.username or parsed.password:
                    raise ValueError('Drawing URL outside declared HTTPS portals')
                sha=record.get('sha256')
                if sha and (len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha)):raise ValueError('Invalid pinned SHA256')
                previous=self.db.execute('SELECT expected_sha FROM downloads WHERE url=?',(record['url'],)).fetchone()
                if previous and sha and previous[0] and previous[0]!=sha:raise ValueError('Conflicting expected hashes for one drawing URL')
                self.db.execute('INSERT INTO downloads(url,expected_sha) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET expected_sha=COALESCE(excluded.expected_sha,expected_sha)',(record['url'],sha))
                identity=json.dumps([record.get('applicationReference',record.get('application_reference')),record['url'],record.get('title')],sort_keys=True)
                identifier=hashlib.sha256(identity.encode()).hexdigest()
                self.db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record',(identifier,record['url'],json.dumps(record,sort_keys=True)))

    def report(self):
        states=dict(self.db.execute('SELECT status,COUNT(*) FROM downloads GROUP BY status'))
        return {'document_links':self.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],
                'unique_urls':sum(states.values()),'download_status':states,
                'distinct_pdf_blobs':self.db.execute("SELECT COUNT(DISTINCT sha) FROM downloads WHERE status='downloaded'").fetchone()[0],
                'inspected_pages':self.db.execute('SELECT COUNT(*) FROM pages').fetchone()[0],
                'status':'complete_manifest' if states.get('downloaded',0)==sum(states.values()) else 'partial_manifest',
                'discovery_completeness':'Not implied by manifest completion',
                'failed_urls':[{
                    'url':url,'attempts':attempts,'error':error} for url,attempts,error in self.db.execute("SELECT url,attempts,error FROM downloads WHERE status='failed' ORDER BY url LIMIT 100")],
                'world_geometry_additions':0,'geometry_status':'PDF vectors and labels require semantics, existing-state review and registration'}

    def acquire(self, *, workers=4, limit=10000, attempts=3, max_bytes=64_000_000,
                max_run_bytes=2_000_000_000, interval=1., cache=None, offline=False, fetch=None):
        if not 1<=workers<=8 or not 1<=limit<=100000 or not 1<=attempts<=10 or max_bytes<=0 or max_run_bytes<=0 or interval<0:
            raise ValueError('Invalid acquisition budgets')
        # Recheck retained bytes; a completed DB flag never bypasses checksums.
        with self.db:
            for url,pin,status,sha in self.db.execute('SELECT url,expected_sha,status,sha FROM downloads').fetchall():
                candidates=[self.root/'files'/f'{sha}.pdf'] if sha else []
                if pin:candidates.append(self.root/'files'/f'{pin}.pdf')
                if cache and pin:candidates.append(Path(cache)/'files'/f'{pin}.pdf')
                retained=None
                for path in candidates:
                    if path.is_file() and path.stat().st_size<=max_bytes:
                        data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
                        if data.startswith(b'%PDF-') and digest==(pin or sha):retained=(data,digest);break
                if retained:
                    data,digest=retained;self._retain(data,digest)
                    self.db.execute("UPDATE downloads SET status='downloaded',sha=?,size=?,error=NULL WHERE url=?",(digest,len(data),url))
                elif status=='downloaded':
                    self.db.execute("UPDATE downloads SET status='pending',attempts=0,error='Retained blob missing or corrupt' WHERE url=?",(url,))
        if offline:return self.report()
        jobs=self.db.execute("SELECT url,expected_sha FROM downloads WHERE status!='downloaded' AND attempts<? ORDER BY url LIMIT ?",(attempts,limit)).fetchall()
        lock=threading.Lock();next_request={};spent=[0];exhausted=threading.Event()
        def take(n):
            with lock:
                if spent[0]+n>max_run_bytes:
                    exhausted.set();raise ValueError('Run byte budget exhausted; resume remaining URLs later')
                spent[0]+=n
        def obtain(job):
            url,pin=job
            if fetch:data=fetch(url);take(len(data))
            else:
                host=urlparse(url).hostname
                with lock:
                    delay=max(0,next_request.get(host,0)-time.monotonic());next_request[host]=time.monotonic()+delay+interval
                if delay:time.sleep(delay)
                with requests.Session() as session:
                    session.headers.update({'User-Agent':USER_AGENT})
                    with session.get(url,stream=True,allow_redirects=False,timeout=(10,45)) as response:
                        response.raise_for_status()
                        if response.status_code!=200:raise ValueError('Redirect/non-200 requires recataloguing')
                        data=bytearray()
                        for chunk in response.iter_content(65536):
                            if len(data)+len(chunk)>max_bytes:raise ValueError('PDF byte budget exceeded')
                            take(len(chunk));data.extend(chunk)
                        data=bytes(data)
            if len(data)>max_bytes or not data.startswith(b'%PDF-'):raise ValueError('Bounded PDF required; HTML/error responses are not drawings')
            digest=hashlib.sha256(data).hexdigest()
            if pin and digest!=pin:raise ValueError('Pinned drawing changed; recataloguing required')
            self._retain(data,digest)
            return digest,len(data)
        # Only a worker-sized window is in flight, rather than one future per PDF.
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            iterator=iter(jobs);pending={}
            def refill():
                while len(pending)<workers and not exhausted.is_set():
                    job=next(iterator,None)
                    if job is None:break
                    pending[pool.submit(obtain,job)]=job
            refill()
            while pending:
                done,_=futures.wait(pending,return_when=futures.FIRST_COMPLETED)
                for future in done:
                    url,_=pending.pop(future)
                    try:
                        digest,size=future.result();state,error='downloaded',None
                    except (OSError,ValueError,requests.RequestException) as exc:
                        digest,size,state,error=None,None,'failed',str(exc)
                    with self.db:self.db.execute('UPDATE downloads SET status=?,attempts=attempts+1,sha=?,size=?,error=? WHERE url=?',(state,digest,size,error,url))
                refill()
        result=self.report();result['run_network_bytes']=spent[0];return result

    def _retain(self,data,digest):
        path=self.root/'files'/f'{digest}.pdf'
        temporary=path.with_suffix('.'+uuid.uuid4().hex+'.partial')
        temporary.write_bytes(data);temporary.replace(path)

    def inspect(self, max_pages=10000):
        import pymupdf
        if not 1<=max_pages<=100000:raise ValueError('Invalid page budget')
        processed=0;errors=[]
        for (sha,) in self.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall():
            try:
                with pymupdf.open(self.root/'files'/f'{sha}.pdf') as pdf:
                    for page_number in range(len(pdf)):
                        if self.db.execute('SELECT 1 FROM pages WHERE sha=? AND page=?',(sha,page_number+1)).fetchone():continue
                        if processed>=max_pages:break
                        page=pdf[page_number];text=page.get_text();summary={'document_sha256':sha,'page':page_number+1,'document_pages':len(pdf),
                            'frame':'PDF native points; not geographic coordinates','width_points':page.rect.width,'height_points':page.rect.height,'rotation':page.rotation,
                            'native_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'native_text_excerpt':text[:20000],
                            'raw_vector_path_count':len(page.get_cdrawings()),'status':'page_inventory_only','world_geometry_additions':0}
                        with self.db:self.db.execute('INSERT INTO pages VALUES(?,?,?)',(sha,page_number+1,json.dumps(summary)))
                        processed+=1
                if processed>=max_pages:break
            except Exception as exc:errors.append({'sha256':sha,'error':str(exc)})
        result=self.report();result.update(run_inspected_pages=processed,inspection_errors=errors);return result

    def close(self):self.db.close()


def discover_alton(corpus, refresh=False, max_search_pages=40, max_applications=1000):
    """Provider-specific address search and resumable full attachment-page discovery."""
    from .alton_discovery import search_applications,parse_attachments,HOST
    if not 1<=max_applications<=10000:raise ValueError('Application budget must be 1–10000')
    corpus.db.execute('CREATE TABLE IF NOT EXISTS applications(reference TEXT PRIMARY KEY,record TEXT,status TEXT,attempts INTEGER DEFAULT 0,sha TEXT,error TEXT)')
    search_path=corpus.root/'alton-application-search.json';deadline=time.monotonic()+900
    with requests.Session() as session:
        session.headers.update({'User-Agent':USER_AGENT})
        search=json.loads(search_path.read_text()) if search_path.exists() and not refresh else search_applications(session,corpus.root,max_search_pages,deadline)
        with corpus.db:
            for application in search['applications']:
                corpus.db.execute("INSERT OR IGNORE INTO applications(reference,record,status) VALUES(?,?,'pending')",(application['reference'],json.dumps(application)))
        processed=0
        for reference,text,status,attempts,sha in corpus.db.execute('SELECT reference,record,status,attempts,sha FROM applications ORDER BY reference').fetchall():
            if processed>=max_applications or time.monotonic()>=deadline:break
            application=json.loads(text);path=corpus.root/'files'/f'{sha}.html' if sha else None
            cached=path is not None and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==sha
            if status=='discovered' and cached and not refresh:continue
            if attempts>=3 and not refresh:continue
            try:
                if not application.get('application_context'):raise ValueError('Application site context required')
                time.sleep(1)
                parsed=urlparse(application['url'])
                if parsed.scheme!='https' or parsed.hostname!=HOST:raise ValueError('Official application URL required')
                with session.get(application['url'],stream=True,allow_redirects=False,timeout=(10,30)) as response:
                    response.raise_for_status()
                    if response.status_code!=200:raise ValueError('Application redirect requires recataloguing')
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>2_000_000:raise ValueError('Application HTML byte budget exceeded')
                data=bytes(data);digest=hashlib.sha256(data).hexdigest()
                documents=parse_attachments(data,application)
                (corpus.root/'files'/f'{digest}.html').write_bytes(data)
                corpus.ingest(documents,[HOST])
                with corpus.db:corpus.db.execute("UPDATE applications SET status='discovered',sha=?,attempts=attempts+1,error=NULL WHERE reference=?",(digest,reference))
            except (ValueError,OSError,requests.RequestException) as error:
                with corpus.db:corpus.db.execute("UPDATE applications SET status='failed',attempts=attempts+1,error=? WHERE reference=?",(str(error),reference))
            processed+=1
    result=corpus.report();result.update(application_states=dict(corpus.db.execute('SELECT status,COUNT(*) FROM applications GROUP BY status')),
        address_search_complete=search['complete_search'],complete_council_discovery=False,
        discovery_status='Address-match corpus, not proof of complete/current in-park coverage; verify site identity before placement')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['discover-alton','download','inspect','report'])
    p.add_argument('--corpus',required=True);p.add_argument('--manifest');p.add_argument('--hosts',nargs='+')
    p.add_argument('--attempts',type=int,default=3);p.add_argument('--max-file-bytes',type=int,default=64000000);p.add_argument('--max-run-bytes',type=int,default=2000000000)
    p.add_argument('--cache');p.add_argument('--offline',action='store_true');p.add_argument('--workers',type=int,default=4)
    p.add_argument('--refresh-discovery',action='store_true');p.add_argument('--max-search-pages',type=int,default=40)
    p.add_argument('--limit',type=int,default=10000);p.add_argument('--max-pages',type=int,default=10000)
    a=p.parse_args();corpus=Corpus(a.corpus)
    try:
        if a.manifest:
            data=json.loads(Path(a.manifest).read_text());corpus.ingest(data.get('entries',data.get('documents',[])),a.hosts or [])
        result=discover_alton(corpus,a.refresh_discovery,a.max_search_pages,min(a.limit,10000)) if a.stage=='discover-alton' else corpus.acquire(workers=a.workers,limit=a.limit,attempts=a.attempts,max_bytes=a.max_file_bytes,max_run_bytes=a.max_run_bytes,cache=a.cache,offline=a.offline) if a.stage=='download' else corpus.inspect(a.max_pages) if a.stage=='inspect' else corpus.report()
        (corpus.root/'corpus-report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
