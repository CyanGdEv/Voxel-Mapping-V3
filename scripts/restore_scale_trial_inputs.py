"""Restore the checksum-pinned dated EA raster originals for a retained scale job."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

import requests

from voxel_mapper.acquisition import USER_AGENT
from voxel_mapper.generation_cycles import file_hash


def restore(job_path):
    job_path=Path(job_path).resolve();job=json.loads(job_path.read_text())
    sources={s['id']:s for s in job['sources']}
    for key,source_id in [('terrain','ea-dtm'),('surface','ea-dsm')]:
        target=(job_path.parent/job[key]['file']).resolve();sha=job[key]['sha256']
        if target.exists():
            if file_hash(target)!=sha:raise ValueError('Existing source raster changed: '+target.name)
            print('verified',target.name,flush=True);continue
        url=sources[source_id]['url']
        if not url.startswith('https://environment.data.gov.uk/tiles/collections/survey/'):
            raise ValueError('Official retained EA survey URL required')
        with tempfile.TemporaryFile() as archive_file:
            with requests.get(url,headers={'User-Agent':USER_AGENT},stream=True,allow_redirects=False,timeout=(10,45)) as response:
                response.raise_for_status()
                if response.status_code!=200:raise ValueError('Survey redirect/non-200 requires source review')
                size=0
                for chunk in response.iter_content(1024*1024):
                    size+=len(chunk)
                    if size>100000000:raise ValueError('Survey download exceeds source budget')
                    archive_file.write(chunk)
            archive_file.seek(0)
            with zipfile.ZipFile(archive_file) as archive:
                files=[e for e in archive.infolist() if e.filename.lower().endswith('.tif')]
                if len(files)!=1 or files[0].file_size>150000000:raise ValueError('One bounded source raster required')
                data=archive.read(files[0])
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Original survey raster checksum differs; no fallback used')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        print('restored',target.name,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--job',type=Path,required=True)
    restore(parser.parse_args().job)
