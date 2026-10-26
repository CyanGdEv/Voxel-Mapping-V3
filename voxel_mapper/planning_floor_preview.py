"""Explicitly conditional FFL floor/plinth and bounded cut/fill path-grading preview."""
from concurrent.futures import CancelledError
import json
import math
from pathlib import Path
import shutil
import tempfile

from shapely.geometry import Point,shape
from shapely.affinity import scale

from . import planning_geo_preview as geo,planning_geometry_world as geometry_world,planning_surface_audit as audit
from .generation_cycles import atomic_json,file_hash
from .horizontal_grid import OSTN15Transform

MAX_FLOOR_CELLS=2048
MAX_PLINTH_BLOCKS=16384


def grade_paths(cells,heights,*,cancelled=lambda:False):
    """Minimum L1 cut/fill proposal, within one block and unit neighbour steps."""
    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix
    if len(cells)>65536 or not cells<=set(heights):raise ValueError('Bounded complete path heights required')
    if cancelled():raise CancelledError('Grading proposal cancelled')
    keys=sorted(cells);n=len(keys)
    if not n:return {}
    index={k:i for i,k in enumerate(keys)};rows=[];cols=[];values=[];rhs=[]
    def constraint(terms,bound):
        number=len(rhs)
        for col,value in terms:rows.append(number);cols.append(col);values.append(value)
        rhs.append(bound)
    original=np.array([heights[k] for k in keys],dtype=float)
    for i,(x,y) in enumerate(keys):
        if cancelled():raise CancelledError('Grading proposal cancelled')
        constraint([(i,1),(n+i,-1)],original[i]);constraint([(i,-1),(n+i,-1)],-original[i])
        for q in ((x+1,y),(x,y+1)):
            if q in index:
                j=index[q];constraint([(i,1),(j,-1)],1);constraint([(j,1),(i,-1)],1)
    matrix=coo_matrix((values,(rows,cols)),shape=(len(rhs),2*n)).tocsr()
    # Total earthwork is primary; a tiny secondary cost favours cuts in exact ties.
    objective=np.r_[np.full(n,1e-6),np.ones(n)]
    result=linprog(objective,A_ub=matrix,b_ub=rhs,bounds=[(v-1,v+1) for v in original]+[(0,None)]*n,
        method='highs',options={'time_limit':20})
    if cancelled():raise CancelledError('Grading proposal cancelled')
    if not result.success:raise ValueError('No bounded one-block grading solution: '+result.message)
    heights_new=np.rint(result.x[:n]).astype(int)
    if np.max(np.abs(result.x[:n]-heights_new))>1e-6:raise ValueError('Grading solver did not return integral block heights')
    proposed=dict(zip(keys,map(int,heights_new)))
    for k,v in proposed.items():
        if abs(v-heights[k])>1:raise ValueError('Grading exceeds one-block cut/fill limit')
        for q in ((k[0]+1,k[1]),(k[0],k[1]+1)):
            if q in proposed and abs(v-proposed[q])>1:raise ValueError('Grading retains a multi-block neighbour step')
    return {k:v for k,v in proposed.items() if heights[k]!=v}


def floor_cells(claims,buildings,heights,unit):
    polygons={r['id']:scale(shape(r['geometry_pdf_native']),xfact=unit,yfact=unit,origin=(0,0)) for r in buildings['records']}
    cells={};floors=[];work=0
    for claim in claims:
        if len(claim['source_building_ids'])!=1:raise ValueError('Unambiguous source floor footprint required')
        identifier=claim['source_building_ids'][0];g=polygons[identifier];a,b,c,d=g.bounds
        # Full one-metre floor blocks: top is the floored FFL, never FFL + 1.
        top=math.floor(claim['printed_level_m']);base=top-1;count=0
        for x in range(math.floor(a),math.ceil(c)):
            for y in range(math.floor(b),math.ceil(d)):
                work+=1
                if work>65536:raise ValueError('Floor proposal sampling budget exceeded')
                if not g.covers(Point(x+.5,y+.5)):continue
                k=x,y
                if k not in heights:raise ValueError('Complete floor coverage required')
                if k in cells:
                    if cells[k]['source_ffl_m']!=claim['printed_level_m']:raise ValueError('Overlapping floor claims have different source levels')
                    cells[k]['source_building_ids'].append(identifier);cells[k]['labels']=sorted(set(cells[k]['labels'])|set(claim['building_labels']));count+=1;continue
                if abs(base-heights[k])>8:raise ValueError('Floor/terrain difference exceeds prototype limit')
                cells[k]={'base_odn_block_m':base,'source_building_id':identifier,'source_building_ids':[identifier],'source_ffl_m':claim['printed_level_m'],'labels':list(claim['building_labels'])};count+=1
                if len(cells)>MAX_FLOOR_CELLS:raise ValueError('Floor area budget exceeded')
        floors.append({'source_building_id':identifier,'labels':claim['building_labels'],'source_ffl_m':claim['printed_level_m'],
            'preview_floor_top_odn_assumption_m':top,'quantization_error_m':top-claim['printed_level_m'],'floor_cells':count,
            'datum_assumption':'printed FFL treated as ODN for this conditional preview only','datum_verified':False})
    return cells,floors


def run(config,world_directory,pdf,output,*,assume_plan_ffl_odn=False,cancelled=lambda:False):
    if assume_plan_ffl_odn is not True:raise ValueError('Explicit conditional FFL-as-ODN preview assumption required')
    output=Path(output)
    if output.exists():raise ValueError('Fresh floor prototype output required')
    world_directory=Path(world_directory);base=json.loads((world_directory/'quality-report.json').read_text())
    original_world=world_directory/base['world']['file'];original_world_sha=file_hash(original_world)
    if original_world_sha!=base['world']['sha256'] or base['implementation_sha256']!=file_hash(geo.__file__):raise ValueError('Pinned current geographic world required')
    for n in ('osm','dtm','grid'):
        if file_hash(config[n+'_path'])!=config[n+'_sha256'] or base['source_pins'][n]!=config[n+'_sha256']:raise ValueError('Geographic source pin mismatch')
    data=geometry_world.read_inputs(config['geometry_request']);sampled=geometry_world.rasterize(data,cancelled=cancelled)
    if base['planning_source_pins']!={n:config['geometry_request'][n+'_sha256'] for n in data}:raise ValueError('Planning source pins changed')
    project=OSTN15Transform('EPSG:4326','EPSG:27700',{'method':'ostn15-bng-v1','path':config['grid_path'],'sha256':config['grid_sha256']})
    placement,_=geo.alignment(data,json.loads(Path(config['osm_path']).read_text()),project)
    if placement!=base['alignment']:raise ValueError('Geographic alignment changed')
    heights,terrain=geo.terrain_heights(sampled,placement['nominal_local_xy_to_bng_en_affine'],config['dtm_path'],cancelled=cancelled)
    saved={tuple(r['source_cell_xy']):r['surface_odn_block_m'] for r in json.loads((world_directory/'terrain-samples.json').read_text())}
    if saved!=heights:raise ValueError('Base terrain differs from current pinned raster')
    claims=audit.floor_claims(pdf,data['layout']['document_sha256'],data['buildings'],geo.profile()['source_metres_per_native_point'])
    if sorted(label for c in claims for label in c['building_labels'])!=['Maintenance','Shop','Station']:raise ValueError('Exactly the three reviewed floor claims required')
    floors,floor_report=floor_cells(claims,data['buildings'],heights,geo.profile()['source_metres_per_native_point'])
    if set(floors)&set(sampled['rocks']):raise ValueError('Floor proposal conflicts with existing edging')
    path=audit.walkable_cells(sampled)-set(floors);cuts=grade_paths(path,heights,cancelled=cancelled)
    original_heights=dict(heights);old_ground=dict(sampled['ground']);before=audit.path_steps(path,heights,placement['nominal_local_xy_to_bng_en_affine'])
    heights.update(cuts)
    for k,r in floors.items():
        heights[k]=r['base_odn_block_m'];sampled['ground'].setdefault(k,'stone_bricks')
    after=audit.path_steps(path,heights,placement['nominal_local_xy_to_bng_en_affine'])
    if after['multi_block_step_pairs']:raise ValueError('Path grading proposal retains a multi-block step')
    combined=audit.path_steps(path|set(floors),heights,placement['nominal_local_xy_to_bng_en_affine'])
    perimeter_steps=[r for r in combined['hotspots'] if sum(tuple(k) in floors for k in r['source_cells_xy'])==1]
    if any(sampled['ground'][k]!=v for k,v in old_ground.items()):raise ValueError('Original plan material changed')
    plinths={k:list(range(original_heights[k]+1,r['base_odn_block_m'])) for k,r in floors.items()}
    plinth_blocks=sum(len(v) for v in plinths.values())
    if plinth_blocks>MAX_PLINTH_BLOCKS:raise ValueError('Plinth preview budget exceeded')
    a,b,c,d=sampled['bounds'];spawn=sampled['retained_spawn_local_xyz_m'];spawn_key=math.floor(spawn[0]),math.floor(spawn[2])-1
    report={'version':'conditional-floor-foundation-preview-v1','status':'conditional_ffl_and_bounded_grade_prototype','crs':'EPSG:27700','vertical_datum':'ODN',
        'voxel_size_m':1,'model_blocks_per_source_metre':1,'spawn_local_xyz_m':[spawn[0],heights[spawn_key]+1,spawn[2]],
        'horizontal_transform':base['horizontal_transform'],'alignment':placement,'source_terrain':terrain,
        'floor_plates':floor_report,'floor_cells':len(floors),'same_level_shared_floor_cells':sum(len(v['source_building_ids'])>1 for v in floors.values()),'provisional_plinth_blocks':plinth_blocks,
        'foundation_design_verified':False,'plinth_basis':'solid neutral stone display supports; not measured foundations or confirmed undercroft design',
        'path_cells_changed':len(cuts),'path_cells_cut':sum(v<original_heights[k] for k,v in cuts.items()),'path_cells_filled':sum(v>original_heights[k] for k,v in cuts.items()),
        'maximum_path_cut_blocks':max([0]+[original_heights[k]-v for k,v in cuts.items()]),'maximum_path_fill_blocks':max([0]+[v-original_heights[k] for k,v in cuts.items()]),
        'grading_policy':'minimum total absolute one-metre block changes; each cell limited to plus/minus one block',
        'path_steps_before':before,'path_steps_after':after,'path_grading_source_verified':False,
        'floor_perimeter_multi_block_steps':perimeter_steps,'floor_perimeter_multi_block_step_pairs':len(perimeter_steps),'building_access_verified':False,
        'floor_perimeter_review_scope':'perimeter height differences, not identified doorways; entrances and access stairs remain unmodelled',
        'datum_assumption':'use printed FFL as ODN in an isolated preview; source datum remains unverified',
        'source_floor_datum_verified':False,'baseline_source_world_sha256':original_world_sha,'baseline_source_world_unchanged':True,
        'original_ground_feature_materials_preserved':len(old_ground),'plan_marking_cells_preserved':len(sampled['plan_markers']),
        'reconstructed_buildings':0,'building_heights_reconstructed':0,'production_placement_eligible':False,'physical_registration_verified':False,
        'training_labels_generated':0,'minecraft_import_tested':False,'implementation_sha256':file_hash(__file__),
        'geographic_implementation_sha256':file_hash(geo.__file__),'source_pdf_sha256':file_hash(pdf),
        'source_pins':base['source_pins'],'planning_source_pins':base['planning_source_pins'],'sources':base['sources']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='floor-preview-',dir=output.parent) as temporary:
        root=Path(temporary)/'result';root.mkdir();voxel=root/'voxels.jsonl'
        with voxel.open('w') as stream:
            for x in range(a,c):
                if cancelled():raise CancelledError('Floor preview generation cancelled')
                for y in range(b,d):
                    k=x,y;rows=[{'x':x,'y':heights[k],'z':y+1,'kind':'terrain','material':sampled['ground'].get(k,'grass_block')}]
                    rows.extend({'x':x,'y':h,'z':y+1,'kind':'structure','material':'stone_bricks'} for h in plinths.get(k,[]))
                    rows.extend({'x':x,'y':heights[k]+n,'z':y+1,'kind':'structure','material':m} for n,m in sampled['rocks'].get(k,[]))
                    for row in rows:stream.write(json.dumps(row)+'\n')
        from . import bedrock
        from .planning_world_preview import _spawn_check,_verify_archive
        def check(path,offset,native_spawn):
            report['spawn_validation']=_spawn_check(path,native_spawn)
            report['saved_geometry_validation']=geo.saved_check(path,offset,sampled,heights,cancelled)
            report['saved_geometry_validation']['provisional_plinth_blocks_verified_by_native_writer']=plinth_blocks
            atomic_json(path/'planning-geographic-alignment.json',{**placement,'minecraft_cell_centre_to_source_xy':'[Minecraft X + 0.5, -(Minecraft Z + 0.5)]','vertical_offset_blocks':offset})
            atomic_json(path/'CONDITIONAL-FLOOR-ASSUMPTIONS.json',{k:report[k] for k in ['datum_assumption','source_floor_datum_verified','floor_plates','plinth_basis','foundation_design_verified','path_grading_source_verified','building_access_verified','floor_perimeter_multi_block_step_pairs']})
        world=bedrock.export_world(voxel,root,report,name='Wicker conditional floor and path-grading prototype',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-floor-foundation-preview.mcworld');report['world']['file']='wicker-floor-foundation-preview.mcworld';shutil.rmtree(root/'bedrock-world')
        atomic_json(root/'floor-cells.json',[{'source_cell_xy':list(k),'old_terrain_block_odn_m':original_heights[k],**v} for k,v in sorted(floors.items())])
        atomic_json(root/'path-grading-changes.json',[{'source_cell_xy':list(k),'old_ground_block_odn_m':original_heights[k],'proposed_ground_block_odn_m':v} for k,v in sorted(cuts.items())])
        _plan_overview(root,sampled,floors,cuts)
        # This overview is plan-only; the actual height changes are in the sections and native world.
        _sections(root,floors,floor_report,original_heights)
        for n in ('osm','dtm','grid'):
            if file_hash(config[n+'_path'])!=config[n+'_sha256']:raise ValueError('Geographic source changed during export')
        geometry_world.read_inputs(config['geometry_request'])
        if file_hash(original_world)!=original_world_sha or file_hash(pdf)!=data['layout']['document_sha256']:raise ValueError('Original world or source PDF changed')
        atomic_json(root/'quality-report.json',report)
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Conditional floor prototype</title><h1>Conditional floor and grading prototype</h1><p><a href="wicker-floor-foundation-preview.mcworld">Download world</a></p><p>Printed FFLs are treated as ODN for this isolated study only. Whole-block floors, solid display plinths and bounded cut/fill path grading are proposals, not verified construction. No walls, roofs or as-built claims are supplied. Original aligned world is unchanged.</p><img style="max-width:100%" src="floor-sections.png"><p><a href="quality-report.json">Saved-world checks and assumptions</a></p>')
        shutil.move(str(root),output)
    return report


def _plan_overview(root,sampled,floors,cuts):
    from PIL import Image,ImageDraw
    from .rock_world_render import colour
    a,b,c,d=sampled['bounds'];unit=4;image=Image.new('RGB',((c-a)*unit+48,(d-b)*unit+100),'#f8f7ef');draw=ImageDraw.Draw(image)
    for x in range(a,c):
        for y in range(b,d):
            k=x,y;px=24+(x-a)*unit;py=42+(d-y-1)*unit
            draw.rectangle((px,py,px+3,py+3),fill=colour(sampled['ground'].get(k,'grass_block')))
            if k in sampled['rocks']:draw.rectangle((px,py,px+3,py+3),outline='#44483f')
            if k in cuts:draw.rectangle((px,py,px+3,py+3),fill='#d64941')
    draw.text((20,12),'CONDITIONAL floor/plinth and path-grading prototype - plan overview',fill='black')
    draw.text((20,image.height-38),'Neutral filled building areas: level floor proposals; red: proposed one-block path cut/fill changes.',fill='black')
    draw.text((20,image.height-20),'Floor datum, grading and solid plinth design are assumptions. This is not a measured building reconstruction.',fill='black');image.save(root/'world-overview.png')


def _sections(root,floors,reports,original):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(1100,560),'#faf8f0');draw=ImageDraw.Draw(image)
    draw.text((20,12),'CONDITIONAL floor/plinth study: printed FFL assumed ODN, whole-block quantization',fill='black')
    for i,row in enumerate(reports):
        cells=[k for k,v in floors.items() if row['source_building_id'] in v['source_building_ids']];x0=min(k[0] for k in cells);x1=max(k[0] for k in cells);middle=sorted({k[1] for k in cells})[len({k[1] for k in cells})//2]
        line=sorted(k for k in cells if k[1]==middle);base_y=170+i*170;top=row['preview_floor_top_odn_assumption_m']
        draw.text((20,base_y-125),', '.join(row['labels'])+' | source FFL '+str(row['source_ffl_m'])+' | preview walking top '+str(top),fill='black')
        for x,y in line:
            px=80+(x-x0)*25;ground=original[x,y]+1;gy=base_y-(ground-175)*9;fy=base_y-(top-175)*9
            drawn_ground_y=max(gy,fy)
            draw.rectangle((px,drawn_ground_y,px+24,base_y),fill='#91aa74')
            if ground>top:draw.line((px,gy,px+24,gy),fill='#d64f43',width=2)
            if fy<gy:draw.rectangle((px,fy+8,px+24,gy),fill='#9b9c96')
            draw.rectangle((px,fy,px+24,fy+8),fill='#58b5dd')
        draw.text((650,base_y-80),'Grey: provisional plinth; red line: original ground cut',fill='black')
    image.save(root/'floor-sections.png')


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','world-directory','pdf','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--assume-plan-ffl-odn',action='store_true',help='Explicit conditional study assumption; does not verify the datum.')
    args=parser.parse_args(argv);path=Path(args.config).resolve()
    if path.stat().st_size>32768:raise ValueError('Bounded geographic request required')
    config=json.loads(path.read_text())
    for n in ('osm','dtm','grid'):config[n+'_path']=str((path.parent/config[n+'_path']).resolve())
    for n in ('layout','paving','gaps','buildings','markings','expansion'):
        if n+'_path' in config['geometry_request']:config['geometry_request'][n+'_path']=str((path.parent/config['geometry_request'][n+'_path']).resolve())
    r=run(config,args.world_directory,args.pdf,args.output,assume_plan_ffl_odn=args.assume_plan_ffl_odn)
    print(json.dumps({'status':r['status'],'world_sha256':r['world']['sha256'],'floor_cells':r['floor_cells'],'path_cells_changed':r['path_cells_changed']}))


if __name__=='__main__':main()
