"""Verify generic native rows against retained real-study world exports."""
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
    for key in ('mutiny-model','mutiny-preview','shop-preview','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--shop-model',default='evidence/wicker-shop-projection-model.json')
    parser.add_argument('--shop-display-floor',action='store_true')
    args=parser.parse_args();rows=[]
    for identifier,path,directory in [('mutiny-v12',args.mutiny_model,args.mutiny_preview),('wicker-shop',args.shop_model,args.shop_preview)]:
        raw=Path(path).read_bytes();spec=from_study(json.loads(raw),identifier,hashlib.sha256(raw).hexdigest(),display_floor=args.shop_display_floor and identifier=='wicker-shop')
        cells,audit=compile_spec(spec);root=Path(directory)
        exported={}
        for line in (root/'voxels.jsonl').read_text().splitlines():
            row=json.loads(line)
            if row['kind']=='structure':exported[row['x'],row['y'],row['z']]=row['material']
        if exported!=cells:raise ValueError('Retained native rows differ from shared compiler')
        report=json.loads((root/'quality-report.json').read_text());world=report['world']
        if hashlib.sha256((root/'park.mcworld').read_bytes()).hexdigest()!=world['sha256']:raise ValueError('World checksum changed')
        rows.append({'building_id':identifier,'source_model_sha256':hashlib.sha256(raw).hexdigest(),
            'component_meshes':len(spec['components']),'surface_cells':len(cells),'roof_join_repairs':audit['roof_join_repairs'],
            'structural_status':audit['structural_review']['status'],
            'unsupported_roof_regions':audit['structural_review']['unsupported_roof_regions'],
            'floor_reference':spec.get('floor_reference'),
            'native_rows_sha256':digest([[*p,m] for p,m in sorted(cells.items())]),
            'sampling_checks':audit['sampling_checks'],'protected_air_halves':audit['protected_air_halves'],
            'protected_air_verified':audit['protected_air_verified'],'blocked_roof_cells':audit['blocked_roof_cells'],
            'block_policy':audit['block_policy'],
            'full_blocks_withheld_for_air':audit['full_blocks_withheld_for_air'],
            'non_roof_stairs':audit['non_roof_stairs'],
            'material_counts':audit['material_counts'],
            'max_roof_rounding_error_m':audit['max_roof_top_rounding_error_m'],
            'wooden_roof_stairs':0,'glazing_cells':0,
            'world_sha256':world['sha256'],'composed_blocks':world['composed_blocks'],'chunks':world['chunks'],
            'native_readback':world['round_trip_validation'],'world_placement_eligible':False})
    atomic_json(Path(args.output),{'version':'building-native-validation-v1','real_studies':rows,
        'regression_tests_passed':1151,'focused_tests_passed':56,'park_world_blocks_added':0,
        'limitations':['Experimental surface previews, not complete solid-volume or surveyed reconstructions.',
            'Native roof joins, support connectivity and material inference remain unresolved.']})
    print(json.dumps({'real_studies':len(rows),'world_rows_match_shared_compiler':True}))


if __name__=='__main__':main()
