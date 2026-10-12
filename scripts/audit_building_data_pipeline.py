"""Replay real study compatibility without manufacturing training feedback."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.building_spec import from_study, build, digest
from voxel_mapper.building_learning import baseline, rank, FEATURES, GATES
from voxel_mapper.generation_cycles import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutiny-model', required=True)
    parser.add_argument('--shop-model', default='evidence/wicker-shop-projection-model.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    records = []
    for identifier, path in [('mutiny-courtyard', args.mutiny_model), ('wicker-shop', args.shop_model)]:
        raw = Path(path).read_bytes(); parent = json.loads(raw)
        spec = from_study(parent, identifier, hashlib.sha256(raw).hexdigest()); result = build(spec)
        rows = parent.get('components') or [{'id': key, 'mesh': parent[key]} for key in ('wall_mesh','roof_mesh','projection_mesh') if key in parent]
        original = [{'id': c['id'], 'vertices': c['mesh']['vertices'], 'triangles': c['mesh']['triangles']} for c in rows]
        rebuilt = [{'id': c['id'], 'vertices': c['mesh']['vertices'], 'triangles': c['mesh']['triangles']} for c in result['components']]
        if original != rebuilt: raise ValueError('Study geometry changed during adaptation')
        # These studies contain inferred dimensions and unverified assembly
        # correspondence. Do not manufacture passing local-candidate gates.
        candidate = {'id': identifier, 'features': dict.fromkeys(FEATURES, 0),
                     'gates': dict.fromkeys(GATES, False)}
        ranking = rank([candidate], baseline())
        records.append({'building_id': identifier, 'parent_sha256': hashlib.sha256(raw).hexdigest(),
                        'component_meshes': len(rebuilt), 'source_state': result['source_state'], 'geometry_sha256': digest(original),
                        'coordinates_and_triangles_unchanged': True,
                        'spec_sha256': result['spec_sha256'],
                        'unverified_candidate_selected': ranking['selected_id'],
                        'world_placement_eligible': result['world_placement_eligible']})
    atomic_json(Path(args.output), {'version':'building-data-compatibility-audit-v1',
                'real_studies':records, 'real_training_records':0,
                'real_trained_model_activated':False, 'park_world_blocks_added':0})
    print(json.dumps({'real_studies':len(records),'meshes_preserved':sum(r['component_meshes'] for r in records)}))


if __name__ == '__main__': main()
