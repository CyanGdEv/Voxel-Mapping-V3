"""Reproduce the Alton sheet search from pinned saved archives and park map."""
import argparse
import hashlib
import json
from pathlib import Path

from .boundary_registration import file_hash

ARCHIVES = {
    'expanded': '830ef2e993ceff0ab64017f6a2324dd3cfe45a933352650064be429ffc3271fd',
    'mutiny': '6b1ec3033c559bc64fb81c5d35d03ddaff390b9deb8bd37468cb7ec614487a6c',
}
OSM_SHA256 = '49f601bb30fc11935457f26f6653b53be1b0172820a25c8c465ee84d91497d93'


def run(expanded_archive, mutiny_archive, osm, work_directory, *, max_pair_fits=2000):
    from .cli import parse_osm
    from .park_pipeline import run as run_job
    from .sheet_alignment import fit_sheet
    fit_sheet([], [], max_pair_fits=max_pair_fits)
    archives={'expanded':Path(expanded_archive).resolve(),'mutiny':Path(mutiny_archive).resolve()}
    for key, archive in archives.items():
        if file_hash(archive)!=ARCHIVES[key]:raise ValueError('Retained '+key+' archive checksum mismatch')
    data=Path(osm).read_bytes()
    if hashlib.sha256(data).hexdigest()!=OSM_SHA256:raise ValueError('Retained park map checksum mismatch')
    collection,_=parse_osm(json.loads(data))
    collection['features']=[f for f in collection['features'] if f['properties'].get('name')]
    # Preserve the exact reference serialization used by the previous search.
    encoded=json.dumps(collection).encode()
    root=Path(work_directory).resolve();root.mkdir(parents=True,exist_ok=True)
    reference=root/'reference-landmarks.geojson'
    if reference.exists() and reference.read_bytes()!=encoded:raise ValueError('Reference output changed; use a fresh replay directory')
    reference.write_bytes(encoded)
    job={
        'work_directory':'.',
        'acquisition':{'official_hosts':['publicaccess.staffsmoorlands.gov.uk'],'offline':True,'retained_archives':[
            {'file':str(archives['mutiny']),'sha256':ARCHIVES['mutiny'],'catalogue_member':'alton-planning-catalogue.json','allow_partial':True},
            {'file':str(archives['expanded']),'sha256':ARCHIVES['expanded']},
        ]},
        'drawing_analysis':{'enabled':False},
        'drawing_geometry':{'enabled':True,'max_pages':10000,'curve_tolerance_points':.25},
        'footprint_matching':{'enabled':True,'references':reference.name,'reference_crs':'EPSG:4326','target_crs':'EPSG:27700'},
        'sheet_alignment':{'enabled':True,'max_pair_fits':max_pair_fits},
    }
    job_path=root/'replay-job.json';job_text=json.dumps(job,indent=2)+'\n'
    if job_path.exists() and job_path.read_text()!=job_text:raise ValueError('Replay configuration changed; use a fresh replay directory')
    job_path.write_text(job_text)
    return run_job(job_path,'acquire')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('expanded-archive','mutiny-archive','osm','work-directory'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--max-pair-fits',type=int,default=2000);args=parser.parse_args()
    state=run(args.expanded_archive,args.mutiny_archive,args.osm,args.work_directory,max_pair_fits=args.max_pair_fits)
    print(json.dumps({key:state['stages'][key] for key in ('downloads','drawing_geometry','footprint_matching','sheet_alignment')},indent=2))

if __name__=='__main__':main()
