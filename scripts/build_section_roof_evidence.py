"""Build original section leader/roof diagnostics against conditional roof heights."""
import argparse
import json
from pathlib import Path
from voxel_mapper.section_roof_evidence import build
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source-catalogue','source-directory','fascia-evidence','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--level-text',default='191.5');p.add_argument('--max-checks',type=int,default=2000000)
    r=build(**vars(p.parse_args()));print(json.dumps({k:r[k] for k in ('status','counts','checks','directory')}))
