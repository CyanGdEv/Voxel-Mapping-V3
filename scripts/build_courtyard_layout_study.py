"""Build a source-pinned complete courtyard ground-floor preview and Bedrock study."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.local_wing_review import run
from voxel_mapper.wing_shell_study import build as build_north
from voxel_mapper.wing_partition_review import review
from voxel_mapper.wing_partition_study import apply
from voxel_mapper.courtyard_layout_study import build, validate_source
from voxel_mapper.bedrock import export_world


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--roof-style',choices=('slabs','stairs'),default='slabs')
    p.add_argument('--facade-sources',type=Path,help='Folder containing checksum-named existing courtyard elevations')
    p.add_argument('--dormers',action='store_true',help='Add AL08 dormer fronts with explicit depth/roof-junction hypotheses')
    p.add_argument('--seed',type=Path,default=Path(__file__).resolve().parents[1]/'evidence/mutiny-full-courtyard-layout-seed.json')
    a=p.parse_args()
    if a.output.exists():p.error('Use a fresh output directory')
    if a.dormers and (not a.facade_sources or a.roof_style!='slabs'):p.error('Dormers require facade sources and slab roofs')
    evidence=Path(__file__).resolve().parents[1]/'evidence'
    recipe=evidence/'mutiny-north-wing-window-cycle-review-seed.json'
    recipes=json.loads(recipe.read_text())
    sources={k:a.sources/(v['sha256']+'.pdf') for k,v in recipes['documents'].items()}
    seed=json.loads(a.seed.read_text());validate_source(seed,sources['plan'])
    result=run(recipe,sources,a.output/'source-model')
    parent=json.loads(Path(result['model_path']).read_text())
    north,cells,audit=build_north(parent,json.loads((evidence/'mutiny-north-wing-shell-study-seed.json').read_text()))
    partition_seed=json.loads((evidence/'mutiny-north-wing-mixed-partition-study-seed.json').read_text())
    partition_review=review(parent,sources['plan'],recover_mixed_paths=True)
    north,cells,audit=apply(north,cells,audit,partition_review,partition_seed)
    model,cells,audit=build(north,cells,seed)
    tag='V8'
    if a.facade_sources:
        from voxel_mapper.courtyard_facade_study import apply as apply_facade,validate_source as validate_elevation
        facade_seed=json.loads((evidence/'mutiny-west-facade-access-seed.json').read_text())
        validate_elevation(facade_seed,a.facade_sources/(facade_seed['source_pdf_sha256']+'.pdf'))
        model,cells,facade_audit=apply_facade(model,cells,facade_seed)
        audit['facade_access_review']=facade_audit
        for row in audit['passages_and_doors']:
            if row['id']=='south_lobby_courtyard':row['standing_air_verified']=True
        audit['doorways_with_retained_obstruction']=[r['id'] for r in audit['passages_and_doors'] if not r['standing_air_verified']]
        audit['north_cells_unchanged']=False
        model['slab_conversion_passages']=model.get('slab_conversion_passages',[])+[{'native_columns':[(0,1)]}]
        tag='V10'
        if a.dormers:
            from voxel_mapper.courtyard_dormer_study import apply as apply_dormers
            model,cells,dormer_audit=apply_dormers(model,cells,json.loads((evidence/'mutiny-west-dormer-seed.json').read_text()))
            audit['dormer_review']=dormer_audit
            audit['facade_access_review']['west_dormers_withheld']=0
            tag='V11'
    if a.roof_style=='slabs':
        from voxel_mapper.slab_roof_study import convert
        model['slab_conversion_passages']=model.get('slab_conversion_passages',[])+[r for r in audit['passages_and_doors'] if r['kind']=='passage']
        model,cells,roof_audit=convert(model,cells)
        audit['slab_roof_conversion']=roof_audit
        audit['pre_slab_surface_cells']=audit['surface_cells']
        audit['pre_slab_added_cells']=audit.pop('added_cells')
        audit['pre_slab_native_roof_join_rule']=audit['native_roof_join_rule']
        audit['native_roof_join_rule']='highest source surface sampled into slab courses; masonry collision and edge sealing adjustments retain non-roof cells'
        audit['north_cells_unchanged']=False
        audit['north_non_roof_cells_unchanged']=not bool(a.facade_sources)
        audit['surface_cells']=len(cells)
        tag='V11' if a.dormers else 'V10' if a.facade_sources else 'V9'
    (a.output/'courtyard-model.json').write_text(json.dumps(model,sort_keys=True,indent=2)+'\n')
    (a.output/'courtyard-audit.json').write_text(json.dumps(audit,sort_keys=True,indent=2)+'\n')
    (a.output/'layout-seed.json').write_text(a.seed.read_text())
    lines=['# Whole courtyard layout hypothesis; XYZ = frontage, depth, height in metres.'];offset=0
    for c in model['components']:
        mesh=c['mesh'];lines.append('o '+c['id'])
        lines.extend('v '+' '.join(map(str,v)) for v in mesh['vertices'])
        lines.extend('f '+' '.join(str(i+offset+1) for i in f) for f in mesh['triangles']);offset+=len(mesh['vertices'])
    (a.output/('Mutiny_Full_Courtyard_'+tag+'.obj')).write_text('\n'.join(lines)+'\n')
    from voxel_mapper.study_mesh_export import write_glb
    write_glb(model,a.output/('Mutiny_Full_Courtyard_'+tag+'.glb'))
    world=a.output/'isolated-world';world.mkdir()
    rings=[ring for ring in model['footprints'].values()]
    xs=[v[0] for ring in rings for v in ring];zs=[v[1] for ring in rings for v in ring]
    import math
    rows=[{'x':x,'y':y,'z':z,'kind':'structure','material':m,'feature':'mutiny_full_courtyard_study'} for (x,y,z),m in sorted(cells.items())]
    rows.extend({'x':x,'y':-1,'z':z,'kind':'terrain','material':'grass_block'} for x in range(math.floor(min(xs))-5,math.ceil(max(xs))+6) for z in range(math.floor(min(zs))-5,math.ceil(max(zs))+6))
    voxel=world/'voxels.jsonl';voxel.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    courtyard=model['courtyard_ring_xy_m'];cx=sum(v[0] for v in courtyard[:-1])/4;cz=sum(v[1] for v in courtyard[:-1])/4
    report={'voxel_size_m':1,'model_blocks_per_source_metre':1,'crs':None,'vertical_datum':'STUDY_ZERO',
            'geographic_registration':None,'world_placement_eligible':False,'park_world_blocks_added':0,
            'spawn_local_xyz_m':[cx,0,cz],'courtyard_audit':audit,'limitations':model['assumptions']}
    report['world']=export_world(voxel,world,report,name='Mutiny Full Courtyard — '+('WEST DORMERS V11' if tag=='V11' else 'WEST FACADE AND ACCESS V10' if tag=='V10' else 'SLAB ROOFS V9' if tag=='V9' else 'GROUND FLOOR LAYOUT V8'),ground_depth=4)
    (world/'quality-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':model['status'],'rooms':len(model['rooms']),'audit':audit,'world':report['world']},indent=2))


if __name__=='__main__':main()
