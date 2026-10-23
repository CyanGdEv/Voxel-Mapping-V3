"""Exact roof plus one observed-face fascia OBJ inspection exports."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from voxel_mapper.generation_cycles import atomic_json,file_hash


def inspection_mesh(model):
    roof=model['mesh'];strip=model.get('observed_fascia_mesh')
    if strip is None:raise ValueError('Observed-face strip required')
    index=strip['original_plan_edge_index'];a,b=index,(index+1)%4
    if strip['vertices'][0]!=roof['vertices'][a] or strip['vertices'][3]!=roof['vertices'][b]:raise ValueError('Exact original top corners required')
    if strip['depth_transferred_to_other_edges'] or strip['wall_mesh'] is not None:raise ValueError('Only the observed fascia face is eligible')
    return {'vertices':[*roof['vertices'],strip['vertices'][1],strip['vertices'][2]],
        'triangles':[*roof['triangles'],[a,5,6],[a,6,b]],'observed_edge_index':index,'world_placement_eligible':False}


def export(evidence,output):
    evidence,output=map(Path,(evidence,output));source=evidence/'pyramid-fascia-evidence.json';data=json.loads(source.read_text())
    if data['status']!='conditional_source_gradient_fascia_only' or not data['models']:raise ValueError('Complete source fascia inspection models required')
    files={};entries=[]
    for model in data['models']:
        mesh=inspection_mesh(model);vertices=np.array(mesh['vertices']);faces=np.array(mesh['triangles'])
        if vertices.shape!=(7,3) or faces.shape!=(6,3) or not np.isfinite(vertices).all():raise ValueError('Finite observed-face source mesh required')
        lines=['# Conditional roof and ONE observed fascia face. Nominal metres; Z up.',
            '# Original source correspondence, roles and eave planes remain assumptions.',
            '# No depth transfer to shared cap, wall closure, physical acceptance or world placement.']
        lines+=['v '+' '.join(format(float(v),'.17g') for v in p) for p in vertices]
        lines+=['f '+' '.join(str(int(v)+1) for v in f) for f in faces];raw=('\n'.join(lines)+'\n').encode()
        parsed_v=np.array([[float(v) for v in l.split()[1:]] for l in raw.decode().splitlines() if l.startswith('v ')])
        parsed_f=np.array([[int(v)-1 for v in l.split()[1:]] for l in raw.decode().splitlines() if l.startswith('f ')])
        assert np.array_equal(parsed_v,vertices) and np.array_equal(parsed_f,faces)
        name=model['id']+'.obj';files[name]=raw;entries.append({'model_id':model['id'],'file':name,'sha256':hashlib.sha256(raw).hexdigest(),
            'vertices':7,'triangles':6,'observed_edge_index':mesh['observed_edge_index'],'world_placement_eligible':False})
    manifest={'status':'conditional_observed_face_fascia_exports','source_review_sha256':file_hash(source),'models':entries,'all_vertices_and_triangles_round_trip_identical':True}
    if (output/'manifest.json').exists():
        if json.loads((output/'manifest.json').read_text())!=manifest:raise ValueError('Saved observed fascia manifest changed')
        for entry in entries:
            if file_hash(output/entry['file'])!=entry['sha256']:raise ValueError('Saved observed fascia OBJ changed')
    else:
        output.mkdir(parents=True,exist_ok=True)
        for name,raw in files.items():(output/name).write_bytes(raw)
        atomic_json(output/'manifest.json',manifest)
    return {'directory':str(output),'models':len(entries),'all_vertices_and_triangles_round_trip_identical':True}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(export(**vars(p.parse_args()))))
