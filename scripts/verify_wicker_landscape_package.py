"""Check landscape visibility in the actual downloadable Bedrock archive."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.bedrock import material_block


def verify(package, rows_path, report_path):
    import amulet
    report=json.loads(Path(report_path).read_text())
    rows=[json.loads(line) for line in Path(rows_path).read_text().splitlines()]
    landscape=[r for r in rows if r.get('feature','').startswith('landscape/')]
    if not landscape:raise ValueError('No landscape rows to verify')
    occupied={(r['x'],r['y'],r['z']) for r in rows}
    offset=report['world']['vertical_offset_blocks']
    materials=Counter();clear=0
    with tempfile.TemporaryDirectory(prefix='wicker-package-') as directory:
        with zipfile.ZipFile(package) as archive:
            for name in archive.namelist():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError('Unsafe archive member')
            archive.extractall(directory)
        level=amulet.load_level(directory)
        try:
            root=level.level_wrapper.root_tag.compound
            name=str(root['LevelName'])
            spawn=[int(root[key]) for key in ('SpawnX','SpawnY','SpawnZ')]
            if spawn!=report['world']['spawn']:raise ValueError('Packaged spawn differs from report')
            for row in landscape:
                x,y,z=row['x'],row['y']+offset,-row['z']
                actual=level.get_block(x,y,z,'minecraft:overworld')
                expected=material_block(row['material'])
                if actual.namespaced_name!=expected.namespaced_name or any(actual.properties.get(k)!=v for k,v in expected.properties.items()):
                    raise ValueError(f'Packaged landscape mismatch at {x},{y},{z}: {actual}')
                materials[row['material']]+=1
                if row['kind']=='path' and (row['x'],row['y']+1,row['z']) not in occupied:
                    if level.get_block(x,y+1,z,'minecraft:overworld').base_name!='air':
                        raise ValueError(f'Packaged paving covered at {x},{y},{z}')
                    clear+=1
            sx,sy,sz=spawn
            if level.get_block(sx,sy-2,sz,'minecraft:overworld').base_name in ('air','grass_block','dirt'):
                raise ValueError('Packaged spawn is not over paving')
        finally:level.close()
    return {'status':'downloadable archive reopened and landscape verified',
            'world_name':name,'spawn':spawn,'landscape_cells_checked':len(landscape),
            'materials':dict(materials),'uncovered_path_cells_checked':clear,
            'sha256':hashlib.sha256(Path(package).read_bytes()).hexdigest(),
            'limitation':'Native block verification; no Minecraft client screenshot validation.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True)
    parser.add_argument('--rows',required=True)
    parser.add_argument('--report',required=True)
    parser.add_argument('--receipt',required=True)
    args=parser.parse_args()
    result=verify(args.package,args.rows,args.report)
    Path(args.receipt).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
