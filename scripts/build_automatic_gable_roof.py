"""Build conditional pitched-roof geometry and independent source gable checks."""
import argparse,json
from pathlib import Path
from voxel_mapper.automatic_gable_roof import build
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('profile','preview','components','views','corpus','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--max-checks',type=int,default=100000);a=p.parse_args()
    r=build(a.profile,a.preview,a.components,a.views,a.corpus,a.output,max_checks=a.max_checks)
    print(json.dumps({k:r[k] for k in ('status','counts','checks','directory')}))
