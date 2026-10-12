"""Verify frame qualification, original PDF pins and cross-output replay."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.registration_qualification import run, VERSION
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.generation_cycles import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','geometry','work-directory','output'):parser.add_argument('--'+key,type=Path,required=True)
    for key in ('manifest','references'):parser.add_argument('--'+key,type=Path)
    args=parser.parse_args();root=args.work_directory
    if root.exists():raise ValueError('Fresh qualification audit directory required')
    root.mkdir(parents=True);corpus=Corpus(args.corpus)
    try:
        options={'manifest':args.manifest,'references':args.references}
        first=run(corpus,args.geometry,root/'memory.sqlite',root/'first',**options)
        resumed=run(corpus,args.geometry,root/'memory.sqlite',root/'first',**options)
        replay=run(corpus,args.geometry,root/'memory.sqlite',root/'replay',**options)
        if first['output_sha256']!=resumed['output_sha256'] or first['output_sha256']!=replay['output_sha256']:
            raise ValueError('Qualification replay differs')
        if resumed['run_pages'] or replay['run_pages'] or replay['reused_pages']!=first['pages']:
            raise ValueError('Qualification replay recomputed unchanged evidence')
        receipt={'version':VERSION,'pages':first['pages'],'qualified_frames':first['qualified_frames'],
            'page_statuses':first['page_statuses'],'missing_requirements':first['missing_requirements'],
            'source_pages':first['contract']['pages'],'policy_sha256':first['contract']['policy_sha256'],
            'page_frames_sha256':first['output_sha256'],'unchanged_resume_identical':True,
            'fresh_output_reuses_pages':replay['reused_pages'],'world_geometry_additions':0,
            'physical_components_accepted':0,
            'limitations':['Qualification is horizontal only; component, state, view, height and material evidence remain separate.',
                'Without a supplied verified source policy and independent survey registry, frames remain unqualified.']}
        atomic_json(args.output,receipt)
        print(json.dumps({k:receipt[k] for k in ('pages','qualified_frames','missing_requirements','fresh_output_reuses_pages')}))
    finally:corpus.close()


if __name__=='__main__':main()
