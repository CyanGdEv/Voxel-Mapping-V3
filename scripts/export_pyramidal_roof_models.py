"""Exact OBJ inspection exports for conditional pyramidal roof surfaces."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from voxel_mapper.generation_cycles import atomic_json,file_hash


def export(evidence,output):
    evidence,output=map(Path,(evidence,output));source=evidence/'pyramidal-roof-evidence.json';data=json.loads(source.read_text())
    if data['status']!='conditional_pyramidal_roof_evidence_only' or not data['conditional_pyramid_models']:raise ValueError('Conditional pyramid inspection models required')
    files={};entries=[]
    for model in data['conditional_pyramid_models']:
        vertices=np.asarray(model['mesh']['vertices']);faces=np.asarray(model['mesh']['triangles'])
        if vertices.shape!=(5,3) or faces.shape!=(4,3) or not np.isfinite(vertices).all():raise ValueError('Finite five-vertex source roof required')
        lines=['# Conditional inspection roof; original plan axes, nominal metres, Z up.',
            '# Source datum/roles and linear eave plane assumed; no world placement.',
            '# Cross-threshold support may be missing; inspect evidence coverage holds.']
        lines+=['v '+' '.join(format(float(v),'.17g') for v in p) for p in vertices]
        lines+=['f '+' '.join(str(int(v)+1) for v in face) for face in faces];raw=('\n'.join(lines)+'\n').encode()
        parsed_v=np.array([[float(v) for v in line.split()[1:]] for line in raw.decode().splitlines() if line.startswith('v ')])
        parsed_f=np.array([[int(v)-1 for v in line.split()[1:]] for line in raw.decode().splitlines() if line.startswith('f ')])
        assert np.array_equal(vertices,parsed_v) and np.array_equal(faces,parsed_f)
        name=model['id']+'.obj';files[name]=raw;entries.append({'model_id':model['id'],'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'vertices':5,'triangles':4,'source_level_binding_id':model['source_level_binding_id'],'world_placement_eligible':False})
    manifest={'status':'conditional_pyramid_inspection_exports','source_review_sha256':file_hash(source),'models':entries,'all_vertices_and_triangles_round_trip_identical':True}
    if (output/'manifest.json').exists():
        if json.loads((output/'manifest.json').read_text())!=manifest:raise ValueError('Saved pyramid export manifest changed')
        for row in entries:
            if file_hash(output/row['file'])!=row['sha256']:raise ValueError('Saved pyramid OBJ changed')
    else:
        output.mkdir(parents=True,exist_ok=True)
        for name,raw in files.items():(output/name).write_bytes(raw)
        atomic_json(output/'manifest.json',manifest)
    return {'directory':str(output),'models':len(entries),'all_vertices_and_triangles_round_trip_identical':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(export(**vars(parser.parse_args()))))
