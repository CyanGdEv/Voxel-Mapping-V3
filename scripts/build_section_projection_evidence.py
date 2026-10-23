"""Build all original-corner section projections and shared-face ambiguity."""
import argparse
import json
from pathlib import Path
from voxel_mapper.section_projection_evidence import build
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('section-evidence','pyramid-evidence','section-catalogue','source-directory','fascia-evidence','roof-plan-pdf','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--max-checks',type=int,default=100000);r=build(**vars(p.parse_args()))
    print(json.dumps({k:r[k] for k in ('status','counts','checks','directory')}))
