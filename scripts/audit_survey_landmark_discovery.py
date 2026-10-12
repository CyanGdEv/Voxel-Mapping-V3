"""Replay source-bound survey station discovery against retained original PDFs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.survey_landmark_discovery import run,VERSION
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.generation_cycles import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','geometry','work-directory','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--manifest',type=Path);args=parser.parse_args();root=args.work_directory
    if root.exists():raise ValueError('Fresh station audit directory required')
    root.mkdir(parents=True);corpus=Corpus(args.corpus)
    try:
        options={'manifest':args.manifest}
        first=run(corpus,args.geometry,root/'memory.sqlite',root/'first',**options)
        resumed=run(corpus,args.geometry,root/'memory.sqlite',root/'first',**options)
        replay=run(corpus,args.geometry,root/'memory.sqlite',root/'replay',**options)
        if first['output_sha256']!=resumed['output_sha256'] or first['output_sha256']!=replay['output_sha256']:
            raise ValueError('Station discovery replay differs')
        if resumed['run_pages'] or replay['run_pages'] or replay['reused_pages']!=first['pages']:
            raise ValueError('Station discovery recomputed unchanged evidence')
        receipt={'version':VERSION,'source_pages':first['contract']['source_pages'],
            **{k:first[k] for k in ('pages','page_statuses','reference_statuses','station_candidates',
                'reference_count','ambiguous_station_ids','output_sha256','ocr_pages','raster_triage_statuses')},
            'unchanged_resume_identical':True,'fresh_output_reuses_pages':replay['reused_pages'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
            'limitations':['Only explicit CP:id E=... N=... native station rows and unique leader marks are supported.',
                'Raster OCR yields unverified leads only; unresolved pages are not certified absent.',
                'Reference release requires independently verified survey policies; no automatic identity certification.',
                'A released registry still requires independent qualification on the target drawing.']}
        atomic_json(args.output,receipt)
        print(json.dumps({k:receipt[k] for k in ('pages','page_statuses','station_candidates','reference_count','fresh_output_reuses_pages')}))
    finally:corpus.close()


if __name__=='__main__':main()
