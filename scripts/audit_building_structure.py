"""Replay native structural checks and verify that existing native rows are unchanged."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.building_spec import from_study,digest
from voxel_mapper.building_native import compile_spec
from voxel_mapper.generation_cycles import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutiny-model',required=True)
    parser.add_argument('--shop-model',default='evidence/wicker-shop-projection-model.json')
    parser.add_argument('--native-validation',default='docs/evidence/building-native-validation.json')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    previous={r['building_id']:r for r in json.loads(Path(args.native_validation).read_text())['real_studies']}
    rows=[]
    for identifier,path in [('mutiny-v12',args.mutiny_model),('wicker-shop',args.shop_model)]:
        raw=Path(path).read_bytes();source=hashlib.sha256(raw).hexdigest()
        spec=from_study(json.loads(raw),identifier,source);cells,audit=compile_spec(spec)
        native_hash=digest([[*p,m] for p,m in sorted(cells.items())])
        if previous[identifier]['source_model_sha256']!=source or previous[identifier]['native_rows_sha256']!=native_hash:
            raise ValueError('Structural checks changed previously verified native geometry or source model')
        rows.append({'building_id':identifier,'source_model_sha256':source,'spec_sha256':digest(spec),
                     'native_rows_sha256':native_hash,'native_geometry_unchanged':True,
                     'surface_cells':len(cells),'structural_review':audit['structural_review']})
    report={'version':'building-native-structure-validation-v1','real_studies':rows,
            'park_world_blocks_added':0,'training_labels_generated':0}
    atomic_json(Path(args.output),report)
    print(json.dumps({'real_studies':len(rows),'native_geometry_unchanged':True}))


if __name__=='__main__':main()
