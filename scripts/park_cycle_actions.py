"""Portable GitHub Actions handoffs for the park cycle CLI."""
import argparse
import json
import os
import shutil
from pathlib import Path
from voxel_mapper.generation_cycles import CyclePlan, atomic_json
from voxel_mapper.generation_cycle_export import worker_directory


def checkpoint(root, destination):
    """Keep the base, native write journal and latest preview; older downloads stay in their runs."""
    root, destination = Path(root), Path(destination)
    if destination.exists(): raise ValueError('Use a fresh checkpoint directory')
    destination.mkdir(parents=True)
    for name in ['geometry.sqlite','base-world','cycles.sqlite','terrain-config.json','draft-snapshot-report.json']:
        source = root/name
        if source.is_dir(): shutil.copytree(source,destination/name)
        elif source.is_file(): shutil.copyfile(source,destination/name)
    if (root/'terrain-config.json').exists():
        config=json.loads((root/'terrain-config.json').read_text())
        relative=Path(config['terrain']['path'])
        raster=root/relative
        if relative.is_absolute() or not raster.resolve().is_relative_to(root.resolve()) or not raster.is_file():
            raise ValueError('Checkpoint terrain must be a portable relative file inside the input bundle')
        target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(raster,target)
    output = root/'output'; saved = destination/'output'; saved.mkdir()
    for name in ['native','progress.json']:
        source = output/name
        if source.is_dir(): shutil.copytree(source,saved/name)
        elif source.is_file(): shutil.copyfile(source,saved/name)
    plan = CyclePlan(root/'cycles.sqlite')
    try:
        complete = [r for r in plan.report()['cycles'] if r['status']=='complete']
        if complete:
            latest = max(complete,key=lambda r:r['id'])
            source = output/Path(latest['preview']['file']).parent
            shutil.copytree(source,saved/Path(latest['preview']['file']).parent)
    finally: plan.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','collect','checkpoint']);p.add_argument('--root',default='cycle-work')
    p.add_argument('--source');p.add_argument('--destination');p.add_argument('--allow-draft',action='store_true')
    a=p.parse_args();root=Path(a.root)
    if a.stage == 'checkpoint':
        if not a.destination:p.error('checkpoint requires --destination')
        checkpoint(root,a.destination);return
    plan=CyclePlan(root/'cycles.sqlite')
    try:
        cycle=plan.next_cycle()
        if a.stage=='collect':
            if cycle is None:raise ValueError('No next cycle to collect')
            if not a.source:p.error('collect requires --source')
            for number in range(plan.contract['workers']):
                source=Path(a.source)/f'park-cycle-worker-{number}'
                target=worker_directory(root/'output',cycle,number)
                if target.exists():shutil.rmtree(target)
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,target)
        else:
            if plan.contract.get('review_draft') and not a.allow_draft:
                raise ValueError('Actions preparation of review geometry requires explicit --allow-draft')
            plan.validate_inputs(root/'geometry.sqlite',root/'base-world')
            if plan.contract['workers']!=10:raise ValueError('Actions workflow requires exactly ten workers')
            atomic_json(root/'output/progress.json',plan.report())
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
                    stream.write('cycle='+str(cycle or '')+'\n')
                    stream.write('complete='+str(cycle is None).lower()+'\n')
                    stream.write('preview_artifact=park-preview-cycle-'+f'{cycle:04d}'+'\n' if cycle else 'preview_artifact=none\n')
            print(json.dumps({'cycle':cycle,'complete':cycle is None}))
    finally:plan.close()


if __name__=='__main__':main()
