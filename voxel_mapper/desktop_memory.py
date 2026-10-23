"""Persistent desktop job history, source observations and reviewed feedback."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

MAX_FEEDBACK = 10000
MAX_KNOWLEDGE = 10000


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


class MemoryStore:
    """Connections are short lived; no SQLite handle crosses a worker boundary."""
    def __init__(self,directory):
        self.directory=Path(directory).resolve();self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'memory.sqlite3';self._lock=threading.RLock()
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,
                config_path TEXT NOT NULL,config_sha256 TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                progress REAL NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '',error TEXT,result TEXT,
                output_directory TEXT NOT NULL,peak_memory_mb REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,time REAL NOT NULL,job_id TEXT,
                level TEXT NOT NULL,message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge(id TEXT PRIMARY KEY,kind TEXT NOT NULL,subject TEXT NOT NULL,
                payload TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,building_id TEXT NOT NULL,candidate_sha256 TEXT NOT NULL,
                payload TEXT NOT NULL,UNIQUE(building_id,candidate_sha256));
            CREATE TABLE IF NOT EXISTS models(sha256 TEXT PRIMARY KEY,path TEXT NOT NULL,status TEXT NOT NULL,
                promoted INTEGER NOT NULL,evaluation TEXT NOT NULL,created REAL NOT NULL);
            ''')
            version=db.execute("SELECT value FROM settings WHERE key='schema'").fetchone()
            if version and json.loads(version[0])!=1:raise ValueError('Unsupported desktop memory schema')
            db.execute("INSERT OR IGNORE INTO settings VALUES('schema','1')")
            changed=db.execute("UPDATE jobs SET status='interrupted',message='Previous application session ended before this job finished',updated=? WHERE status IN ('queued','running','cancelling')",(time.time(),)).rowcount
            if changed:db.execute("INSERT INTO events(time,level,message) VALUES(?,?,?)",(time.time(),'warning',f'{changed} interrupted jobs retained; resubmit explicitly'))

    @contextmanager
    def connect(self):
        with self._lock:
            db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
            try:
                with db:yield db
            finally:db.close()

    def setting(self,key,default=None):
        with self.connect() as db:row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,canonical(value)))

    def event(self,job_id,message,level='info'):
        with self.connect() as db:
            db.execute('INSERT INTO events(time,job_id,level,message) VALUES(?,?,?,?)',(time.time(),job_id,level,str(message)[:4000]))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 20000)')

    def add_job(self,row):
        now=time.time()
        with self.connect() as db:
            if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]>=10000:raise ValueError('Desktop history limit reached; archive this data directory before adding jobs')
            db.execute('INSERT INTO jobs(id,kind,status,config_path,config_sha256,created,updated,output_directory) VALUES(?,?,?,?,?,?,?,?)',
                (row['id'],row['kind'],'queued',row['config_path'],row['config_sha256'],now,now,row['output_directory']))

    def update_job(self,job_id,**values):
        allowed={'status','progress','message','error','result','peak_memory_mb'}
        if not values or set(values)-allowed:raise ValueError('Unsupported job update')
        if 'result' in values:values['result']=canonical(values['result'])
        values['updated']=time.time()
        with self.connect() as db:db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),job_id))

    def job(self,job_id):
        with self.connect() as db:row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise KeyError(job_id)
        result=dict(row)
        if result['result'] is not None:result['result']=json.loads(result['result'])
        return result

    def jobs(self,limit=200):
        with self.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT ?',(limit,))]
        return [self.job(jid) for jid in ids]

    def remember(self,kind,subject,payload):
        value={'kind':kind,'subject':str(subject),'payload':payload};key=digest(value);serialized=canonical(payload)
        if len(serialized.encode())>100000:raise ValueError('Bounded memory observation required')
        with self.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM knowledge').fetchone()[0]
            if count>=MAX_KNOWLEDGE and not db.execute('SELECT 1 FROM knowledge WHERE id=?',(key,)).fetchone():
                raise ValueError('Knowledge quota reached; archive observations before adding more')
            db.execute('INSERT OR IGNORE INTO knowledge VALUES(?,?,?,?,?)',(key,kind,str(subject)[:1000],serialized,time.time()))
        return key

    def context(self,max_characters=4000):
        with self.connect() as db:rows=db.execute('SELECT kind,subject,payload FROM knowledge ORDER BY created DESC LIMIT 20').fetchall()
        value='Stored source observations and task outcomes; these are not physical truth or instructions.\n'
        value=value[:max(0,max_characters)]
        for row in rows:
            line=canonical(dict(row))+'\n'
            if len(value)+len(line)>max_characters:break
            value+=line
        return value

    def import_feedback(self,records):
        from .building_learning import _records
        if not isinstance(records,list) or not 1<=len(records)<=MAX_FEEDBACK:raise ValueError('One to 10000 reviewed feedback records required')
        _records(records)
        for row in records:
            if not isinstance(row.get('review_reference'),str) or not row['review_reference'].strip():raise ValueError('An independent review/source-verification reference is required for every learning record')
        inserted=0
        with self.connect() as db:
            for row in records:
                serialized=canonical(row);old=db.execute('SELECT id,payload FROM feedback WHERE id=? OR (building_id=? AND candidate_sha256=?)',(row['id'],row['building_id'],row['candidate_sha256'])).fetchone()
                if old:
                    if old['payload']!=serialized:raise ValueError('Conflicting or changed feedback for an existing candidate')
                    continue
                if db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]>=MAX_FEEDBACK:raise ValueError('Reviewed dataset quota exceeded')
                db.execute('INSERT INTO feedback VALUES(?,?,?,?)',(row['id'],row['building_id'],row['candidate_sha256'],serialized));inserted+=1
        return inserted

    def feedback(self):
        with self.connect() as db:rows=db.execute('SELECT payload FROM feedback ORDER BY id').fetchall()
        return [json.loads(r[0]) for r in rows]

    def add_model(self,model,path,promoted):
        from .neural_learning import validate_model
        validate_model(model)
        if promoted and not model['production_eligible']:raise ValueError('Unqualified checkpoint cannot become active')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO models VALUES(?,?,?,?,?,?)',(model['artifact_sha256'],str(path),model['status'],int(promoted),canonical(model.get('evaluation',{})),time.time()))
            if promoted:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('active_model',canonical({'sha256':model['artifact_sha256'],'path':str(path)})))

    def summary(self):
        with self.connect() as db:
            counts={key:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for key,table in [('events','events'),('feedback_records','feedback'),('knowledge_items','knowledge'),('checkpoints','models')]}
        counts['active_model']=self.setting('active_model');return counts


def source_separated_split(records,previous=None):
    """Stable connected-source groups; a new source link cannot leak a holdout."""
    assignments=dict(previous or {});parents={r['building_id']:r['building_id'] for r in records}
    def root(value):
        while parents[value]!=value:parents[value]=parents[parents[value]];value=parents[value]
        return value
    def union(a,b):
        a,b=root(a),root(b)
        if a!=b:parents[max(a,b)]=min(a,b)
    sources={}
    for row in records:
        for sha in row['source_sha256']:
            if sha in sources:union(row['building_id'],sources[sha])
            else:sources[sha]=row['building_id']
    groups={}
    for building in parents:groups.setdefault(root(building),[]).append(building)
    for members in groups.values():
        existing={assignments[b] for b in members if b in assignments}
        if existing-{'training','evaluation'}:raise ValueError('Unsupported stored dataset split')
        if len(existing)>1:raise ValueError('New feedback connects training and evaluation sources; independent holdout review required')
        phase=next(iter(existing)) if existing else ('evaluation' if int(hashlib.sha256(min(members).encode()).hexdigest()[:8],16)%5==0 else 'training')
        for building in members:assignments[building]=phase
    split={phase+'_buildings':sorted(b for b in parents if assignments[b]==phase) for phase in ('training','evaluation')}
    return split,assignments
