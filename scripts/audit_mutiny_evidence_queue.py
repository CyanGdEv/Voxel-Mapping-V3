"""Prepare a diagnostic requirement queue from the retained Mutiny perimeter audit."""
import argparse
import hashlib
import json
from pathlib import Path
from voxel_mapper.reconstruction_evidence_queue import build

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input',type=Path,default=Path('evidence/mutiny-wall-perimeter-coverage-audit.json'))
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
raw=a.input.read_bytes();source=json.loads(raw)
queue=build('mutiny-bay',[source])
queue['input_audit']={'repository_path':a.input.name,'sha256':hashlib.sha256(raw).hexdigest()}
if a.input.read_bytes()!=raw:raise ValueError('Source audit changed')
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(queue,sort_keys=True,indent=2)+'\n')
print(json.dumps({'status':queue['status'],'tasks':len(queue['tasks']),'counts':queue['counts'],'world_geometry_additions':0}))
