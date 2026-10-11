"""Review complete source cycles and plan junctions without mesh promotion."""
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.wing_outline_review import run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('recipe','sources','output'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();recipe=json.loads(a.recipe.read_text())
    paths={k:a.sources/(v['sha256']+'.pdf') for k,v in recipe['documents'].items()}
    print(json.dumps(run(a.recipe,paths,a.output)))
