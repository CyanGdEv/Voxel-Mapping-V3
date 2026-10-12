"""Build a complete core-shell hypothesis preview from a pinned partial wing."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.local_wing_review import run
from voxel_mapper.wing_shell_study import build
from voxel_mapper.bedrock import export_world


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--recipe',type=Path,required=True)
    p.add_argument('--closure-seed',type=Path,required=True);p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--partition-seed',type=Path);a=p.parse_args()
    if a.output.exists():p.error('Use a fresh output directory')
    recipe=json.loads(a.recipe.read_text());sources={k:a.sources/(v['sha256']+'.pdf') for k,v in recipe['documents'].items()}
    result=run(a.recipe,sources,a.output/'source-model');parent=json.loads(Path(result['model_path']).read_text())
    model,cells,audit=build(parent,json.loads(a.closure_seed.read_text()))
    if a.partition_seed:
        from voxel_mapper.wing_partition_review import review
        from voxel_mapper.wing_partition_study import apply
        partition_seed=json.loads(a.partition_seed.read_text())
        partition_review=review(parent,sources['plan'],recover_mixed_paths=partition_seed.get('recover_mixed_paths',False))
        model,cells,audit=apply(model,cells,audit,partition_review,partition_seed)
        (a.output/'partition-source-review.json').write_text(json.dumps(partition_review,sort_keys=True,indent=2)+'\n')
    (a.output/'shell-model.json').write_text(json.dumps(model,indent=2,sort_keys=True)+'\n')
    lines=['# Provisional core shell; rear/end closures and thickness are explicit hypotheses.'];offset=0
    for component in model['components']:
        mesh=component['mesh'];lines.append('o '+component['id']);lines.extend('v '+' '.join(map(str,v)) for v in mesh['vertices'])
        lines.extend('f '+' '.join(str(i+offset+1) for i in f) for f in mesh['triangles']);offset+=len(mesh['vertices'])
    (a.output/'wing-shell.obj').write_text('\n'.join(lines)+'\n')
    world=a.output/'isolated-world';world.mkdir();length=parent['width_check']['elevation_length_m'];depth=parent['measurements']['depth_m']
    rows=[{'x':x,'y':y,'z':z,'kind':'review_surface','material':m,'feature':'provisional_north_wing_shell'} for (x,y,z),m in sorted(cells.items())]
    rows.extend({'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'} for x in range(-6,int(length)+7) for z in range(-12,int(depth)+7))
    voxels=world/'voxels.jsonl';voxels.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    report={'version':model['version'],'voxel_size_m':1,'model_blocks_per_source_metre':1,'crs':None,'vertical_datum':'STUDY_ZERO',
            'geographic_registration':None,'world_placement_eligible':False,'park_world_blocks_added':0,'spawn_local_xyz_m':[length/2,2,-7],
            'shell_audit':audit,'limitations':model['assumptions'],'unresolved':parent['unresolved']}
    report['world']=export_world(voxels,world,report,name=('Mutiny North Range — PARTITIONS AND CLEARANCE V7' if partition_seed.get('recover_mixed_paths') else 'Mutiny North Range — SOURCE PARTITION STUDY V6') if a.partition_seed else 'Mutiny North Range — CORE SHELL HYPOTHESIS V5',ground_depth=4)
    (world/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    (a.output/'shell-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps({'status':model['status'],'surface_cells':len(cells),'world':str(world/'park.mcworld'),'surveyed_complete_structure':False}))

if __name__=='__main__':main()
