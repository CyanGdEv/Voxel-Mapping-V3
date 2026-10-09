"""Import checksum-pinned retained planning archives into a resumable corpus."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid
import zipfile


def import_archive(corpus,archive,expected_sha256,hosts,*,catalogue_member='metadata/alton-planning-catalogue.json'):
    archive=Path(archive)
    if not re.fullmatch('[0-9a-f]{64}',str(expected_sha256)):raise ValueError('Pinned archive SHA256 required')
    if archive.stat().st_size>2000000000:raise ValueError('Archive compressed-byte budget exceeded')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=expected_sha256:raise ValueError('Archive checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        members=source.infolist()
        if len(members)>20000 or len({m.filename for m in members})!=len(members):raise ValueError('Archive member budget or duplicate names')
        index={m.filename:m for m in members};catalogue=index[catalogue_member]
        if catalogue.file_size>8000000:raise ValueError('Catalogue byte budget exceeded')
        entries=json.loads(source.read(catalogue))['entries']
        if not isinstance(entries,list) or len(entries)>10000:raise ValueError('Bounded archive catalogue required')
        records=[];blobs={};total=0
        for record in entries:
            sha=record.get('sha256');member=record.get('file')
            if not re.fullmatch('[0-9a-f]{64}',str(sha)) or member!=f'files/{sha}.pdf':raise ValueError('Pinned content-addressed PDF member required')
            item=index[member]
            if item.file_size>64000000:raise ValueError('PDF byte budget exceeded')
            if sha not in blobs:total+=item.file_size;blobs[sha]=item
            if total>2000000000:raise ValueError('Archive expanded PDF budget exceeded')
            records.append({**record,'retained_archive_sha256':expected_sha256,'retained_archive_member':member,'acquisition_provenance':'checksum_verified_retained_archive; no live download'})
        # Validate every selected blob before changing catalogue/availability.
        for sha,item in blobs.items():
            data=source.read(item)
            if not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Retained PDF header/checksum mismatch')
        corpus.ingest(records,hosts)
        copied=resumed=0
        for sha,item in blobs.items():
            target=corpus.root/'files'/f'{sha}.pdf';valid=False
            if target.exists():
                with target.open('rb') as stream:valid=hashlib.file_digest(stream,'sha256').hexdigest()==sha
            if valid:resumed+=1
            else:
                temporary=target.with_suffix('.'+uuid.uuid4().hex+'.partial')
                try:
                    data=source.read(item)
                    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Retained PDF changed during import')
                    temporary.write_bytes(data);temporary.replace(target)
                finally:temporary.unlink(missing_ok=True)
                copied+=1
            with corpus.db:corpus.db.execute("UPDATE downloads SET status='downloaded',sha=?,size=?,error=NULL WHERE expected_sha=?",(sha,item.file_size,sha))
    report={'status':'retained_archive_imported','archive_sha256':expected_sha256,'catalogue_records':len(records),'unique_pdf_blobs':len(blobs),'copied_blobs':copied,'resumed_blobs':resumed,'expanded_pdf_bytes':total,'live_downloads':0,'world_geometry_additions':0}
    (corpus.root/f'archive-{expected_sha256}.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',required=True);p.add_argument('--archive',required=True);p.add_argument('--sha256',required=True);p.add_argument('--official-host',action='append',required=True);a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(import_archive(corpus,a.archive,a.sha256,a.official_host),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
