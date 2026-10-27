"""Download a bounded, checksum-pinned public source pilot without changing pins."""
import argparse
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse
import requests
from . import study_component_learning as reader
from .generation_cycles import atomic_json


def acquire(profile_path,output,*,cancelled=lambda:False,session=None):
    profile,raw=reader._json(profile_path,4_000_000);output=Path(output)
    if not isinstance(profile,dict) or profile.get('version')!='pinned-study-source-acquisition-v1':raise ValueError('Pinned source profile required')
    sources=profile.get('sources')
    if not isinstance(sources,list) or not 1<=len(sources)<=32:raise ValueError('One to 32 bounded source assets required')
    if output.exists():raise ValueError('Fresh acquisition directory required')
    names=set();budget=0
    for row in sources:
        name=row.get('file');reader._asset(Path('.').resolve(),name)
        if name in names:raise ValueError('Unique source file paths required')
        names.add(name);url=urlparse(row.get('url',''))
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Public HTTPS source URL required')
        if not reader._hash(row.get('sha256')) or type(row.get('bytes')) is not int or not 1<=row['bytes']<=32_000_000:raise ValueError('Bounded expected source bytes and SHA256 required')
        if row.get('format') not in ['pdf','jpeg','png']:raise ValueError('Supported original source format required')
        budget+=row['bytes']
    if budget>128_000_000:raise ValueError('Source acquisition byte budget exceeded')
    output.parent.mkdir(parents=True,exist_ok=True);client=session or requests
    with tempfile.TemporaryDirectory(prefix='study-source-download-',dir=output.parent) as temporary:
        stage=Path(temporary)/'sources';stage.mkdir();receipts=[]
        for row in sources:
            if cancelled():raise CancelledError('Source acquisition cancelled')
            path=reader._asset(stage,row['file']);path.parent.mkdir(parents=True,exist_ok=True)
            count=0;hasher=hashlib.sha256();signature=b''
            with client.get(row['url'],stream=True,timeout=(10,45)) as response:
                response.raise_for_status()
                if urlparse(response.url).scheme!='https':raise ValueError('HTTPS source redirect required')
                with path.open('wb') as f:
                    for chunk in response.iter_content(1_000_000):
                        if cancelled():raise CancelledError('Source acquisition cancelled')
                        if not chunk:continue
                        count+=len(chunk)
                        if count>row['bytes']:raise ValueError('Downloaded source exceeds pinned byte count')
                        signature=(signature+chunk)[:8];hasher.update(chunk);f.write(chunk)
                if count!=row['bytes'] or hasher.hexdigest()!=row['sha256']:raise ValueError('Downloaded source bytes differ from pinned evidence')
                magic={'pdf':b'%PDF','jpeg':b'\xff\xd8','png':b'\x89PNG\r\n\x1a\n'}[row['format']]
                if not signature.startswith(magic):raise ValueError('Downloaded source format does not match profile')
                receipts.append({'file':row['file'],'url':row['url'],'resolved_url':response.url,'bytes':count,'sha256':hasher.hexdigest(),'format':row['format'],'usage':row.get('usage','reference_only')})
        result={'version':'pinned-study-source-acquisition-v1','profile_sha256':reader._sha(raw),'assets':receipts,'asset_bytes':sum(r['bytes'] for r in receipts),'training_labels_generated':0,'model_weights_updated':False}
        atomic_json(stage/'acquisition.json',result)
        if cancelled():raise CancelledError('Source acquisition cancelled')
        shutil.move(stage,output)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',required=True);p.add_argument('--output',required=True)
    a=p.parse_args(argv);r=acquire(a.profile,a.output);print(json.dumps({'assets':len(r['assets']),'asset_bytes':r['asset_bytes'],'training_labels_generated':0}))

if __name__=='__main__':main()
