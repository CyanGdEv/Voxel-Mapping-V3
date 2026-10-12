"""Replay retained Mutiny and Wicker drawing diagnostics into the shared feed."""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.building_source_feed import prepare,VERSION
from voxel_mapper.building_learning import rank
from voxel_mapper.generation_cycles import atomic_json


def pinned(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutiny-model',required=True)
    parser.add_argument('--sources',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    models=[('mutiny-north-range',Path(args.mutiny_model),[root/'evidence/mutiny-opening-boundary-review-audit.json']),
            ('wicker-shop',root/'evidence/wicker-shop-projection-model.json',
             [root/'evidence/wicker-shop-floor-scale-review.json',root/'evidence/wicker-shop-local-roof.json'])]
    config={'version':VERSION,'buildings':[]}
    for identifier,path,assets in models:
        model=pinned(path)
        config['buildings'].append({'building_id':identifier,'model':model['path'],'model_sha256':model['sha256'],
            'display_floor':identifier=='wicker-shop',
            'diagnostics':[pinned(a) for a in assets],'source_directories':[str(Path(args.sources).resolve())]})
    with tempfile.TemporaryDirectory() as tmp:
        job,report=prepare(config,lambda p:Path(p),Path(tmp)/'feed')
        if len(job['buildings'])!=2: raise ValueError(json.dumps(report))
        for building in job['buildings']:
            if rank(building['candidates'])['selected_id'] is not None:
                raise ValueError('Unverified real assembly became eligible')
        report['unverified_real_candidates_selected']=0
        report['focused_tests_passed']=26
        report['real_training_labels']=0
        report['learning_model_activated']=False
        report['scope']='Retained drawing/model adapters; automatic raw-PDF trace discovery remains unfinished.'
        atomic_json(Path(args.output),report)
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
