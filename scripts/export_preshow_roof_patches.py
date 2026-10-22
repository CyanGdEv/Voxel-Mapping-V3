"""Export conditional, unplaced source-cap patches as OBJ review artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from voxel_mapper.generation_cycles import file_hash, atomic_json


def export(evidence, output):
    evidence, output=map(Path,(evidence,output)); source=evidence/'preshow-level-geometry.json'; data=json.loads(source.read_text())
    if data['status']!='conditional_preshow_level_geometry_only':raise ValueError('Complete conditional source patch review required')
    if not data['conditional_roof_patches']:raise ValueError('Conditional source patches required')
    files={}; entries=[]
    for model in data['conditional_roof_patches']:
        mesh=model['mesh']; vertices=np.array(mesh['vertices']); triangles=np.array(mesh['triangles'])
        if vertices.shape!=(6,3) or triangles.shape!=(4,3) or not np.isfinite(vertices).all():raise ValueError('Bounded partial source mesh required')
        lines=['# Conditional source-cap patch; unplaced nominal metres, Z up.',
            '# Continuous planes and physical roof/fascia roles are assumptions.',
            '# Original rail tails are unmeshed; this is not a complete wing.',
            '# Printed source reference: '+model['source_level_label']+' '+str(model['source_level_value_m_candidate'])]
        lines+=['v '+' '.join(format(float(v),'.17g') for v in point) for point in vertices]
        lines+=['f '+' '.join(str(int(v)+1) for v in face) for face in triangles]
        raw=('\n'.join(lines)+'\n').encode(); name=model['id']+'.obj'; files[name]=raw
        parsed_vertices=np.array([[float(v) for v in line.split()[1:]] for line in raw.decode().splitlines() if line.startswith('v ')])
        parsed_faces=np.array([[int(v)-1 for v in line.split()[1:]] for line in raw.decode().splitlines() if line.startswith('f ')])
        assert np.array_equal(parsed_vertices,vertices) and np.array_equal(parsed_faces,triangles)
        entries.append({'model_id':model['id'],'file':name,'sha256':hashlib.sha256(raw).hexdigest(),
            'source_level_label':model['source_level_label'],'source_level_value_m_candidate':model['source_level_value_m_candidate'],
            'source_ink_threshold':model['source_ink_threshold'],'vertices':6,'triangles':4,
            'complete_wing_mesh':False,'world_placement_eligible':False})
    manifest={'status':'conditional_unplaced_source_cap_obj_exports','source_review_sha256':file_hash(source),
        'models':entries,'all_obj_vertices_and_triangles_round_trip_identical':True}
    if (output/'manifest.json').exists():
        if json.loads((output/'manifest.json').read_text())!=manifest:raise ValueError('Saved source patch export changed')
        for entry in entries:
            if file_hash(output/entry['file'])!=entry['sha256']:raise ValueError('Saved source patch OBJ changed')
    else:
        output.mkdir(parents=True,exist_ok=True)
        for name,raw in files.items():(output/name).write_bytes(raw)
        atomic_json(output/'manifest.json',manifest)
    return {'directory':str(output),'models':len(entries),'source_review_sha256':manifest['source_review_sha256'],
        'all_obj_vertices_and_triangles_round_trip_identical':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    print(json.dumps(export(**vars(p.parse_args()))))
