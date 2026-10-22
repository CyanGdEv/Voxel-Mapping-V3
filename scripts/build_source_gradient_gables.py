"""Build original grayscale gable evidence and plan-direction diagnostics."""
import argparse,json
from pathlib import Path
from voxel_mapper.source_gradient_gables import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('source-partial','gable','profile','preview','components','views','corpus','output'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--max-checks',type=int,default=100000)
    a=p.parse_args();print(json.dumps(build(a.source_partial,a.gable,a.profile,a.preview,a.components,a.views,a.corpus,a.output,max_checks=a.max_checks)))
