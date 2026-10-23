"""Test unchanged section cameras against whole original adjoining ridge lines."""
import argparse
import json
from pathlib import Path
from voxel_mapper.section_adjoining_evidence import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('projection-evidence','section-evidence','pyramid-evidence','reference-evidence','section-catalogue','source-directory','fascia-evidence','roof-plan-pdf','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--max-checks',type=int,default=2000000)
    r=build(**vars(p.parse_args()));print(json.dumps({k:r[k] for k in ('status','counts','checks','directory')}))
