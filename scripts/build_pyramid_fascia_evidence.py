"""Build complementary original-contrast fascia support and observed-face strips."""
import argparse
import json
from pathlib import Path
from voxel_mapper.pyramid_fascia_evidence import build
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pyramid','preshow','references','topology-source','gradient','components','views','corpus','source-catalogue','additional-pdfs','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--max-checks',type=int,default=100000)
    print(json.dumps(build(**vars(p.parse_args()))))
