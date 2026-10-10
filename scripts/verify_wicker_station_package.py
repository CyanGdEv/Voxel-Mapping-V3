"""Verify station blocks, compound apertures and ground contact in the download."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.bedrock import material_block
from voxel_mapper.reconstruction.local_buildings import rotate_model
from voxel_mapper.shop_shell import opening_columns


def verify(directory):
    import amulet
    directory=Path(directory);report=json.loads((directory/'quality-report.json').read_text())
    package=directory/report['world']['file']
    rows=[json.loads(l) for l in (directory/'voxels.jsonl').read_text().splitlines()]
    cells=[r for r in rows if r.get('feature','').startswith(('station-review/','access-review/'))]
    if not cells:raise ValueError('Station review rows required')
    offset=report['world']['vertical_offset_blocks'];apertures=set();bottoms={}
    for r in cells:bottoms[r['x'],r['z']]=min(bottoms.get((r['x'],r['z']),r['y']),r['y'])
    for part in report['station_review']['parts']:
        model=rotate_model(json.loads((directory/(part['id']+'-model.json')).read_text()),part['rotation_degrees'])
        ax,az=map(round,part['anchor_bng_m']);floor=round(part['provisional_base_m'])
        for (x,z),head in opening_columns(model['opening_base_segments'],1).items():
            apertures.update((x+ax,y+floor,z+az) for y in range(head))
    support=0
    with tempfile.TemporaryDirectory(prefix='station-package-') as d:
        with zipfile.ZipFile(package) as archive:
            if any(Path(n).is_absolute() or '..' in Path(n).parts for n in archive.namelist()):
                raise ValueError('Unsafe archive member')
            archive.extractall(d)
        level=amulet.load_level(d)
        try:
            for row in cells:
                x,y,z=row['x'],row['y']+offset,-row['z']
                actual=level.get_block(x,y,z,'minecraft:overworld');expected=material_block(row['material'])
                if actual.namespaced_name!=expected.namespaced_name or any(actual.properties.get(k)!=v for k,v in expected.properties.items()):
                    raise ValueError(f'Packaged building mismatch at {x},{y},{z}')
            for x,y,z in apertures:
                if level.get_block(x,y+offset,-z,'minecraft:overworld').base_name!='air':
                    raise ValueError(f'Compound aperture obstructed at {x},{y},{z}')
            floor=max(round(p['provisional_base_m']) for p in report['station_review']['parts'])
            for (x,z),bottom in bottoms.items():
                if bottom>floor:continue # Roof overhangs have no ground-bearing requirement.
                if level.get_block(x,bottom-1+offset,-z,'minecraft:overworld').base_name=='air':
                    raise ValueError(f'Floating bearing column at {x},{bottom},{z}')
                support+=1
        finally:level.close()
    return {'status':'downloadable world reopened; building cells, apertures and bearing columns verified',
            'building_and_access_cells_checked':len(cells),'aperture_air_cells_checked':len(apertures),
            'bearing_columns_checked':support,'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
            'world':report['world'],'station_review':report['station_review'],
            'limitation':'Native verification, no in-game visual validation or accepted surveyed placement.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True);parser.add_argument('--receipt',required=True)
    args=parser.parse_args();receipt=verify(args.directory)
    Path(args.receipt).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('station_review','world')}))
