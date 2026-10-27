"""Add a source-informed maintenance shell to the retained aligned park world."""
import argparse
from concurrent.futures import CancelledError
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.geometry import shape,Polygon,LineString,mapping

from .generation_cycles import atomic_json,file_hash
from . import planning_station_preshow_world as shell,planning_wall_shell as shop
from .drawing_page_tools import pixel_to_native
from .wicker_building_models import rectangular_model
from .station_access import paving_approach
from .shop_slabs import occupied_halves
from .shop_shell import leak_audit

PROFILE=Path(__file__).with_name('data')/'wicker-maintenance-building.json'
UNIT=100*.0254/72


def traced_heights(trace,metres_per_pixel,floor):
    datum=trace['datum_pixel'][1];eave=trace['eave_pixel'][1];ridge=trace['ridge_pixel'][1]
    if not ridge<eave<datum or not 0<metres_per_pixel<.1:raise ValueError('Ordered elevation samples required')
    absolute={k:trace['inspection_level_m']+(datum-y)*metres_per_pixel for k,y in [('eave',eave),('ridge',ridge)]}
    relative={k:v-floor for k,v in absolute.items()}
    if not 2.3<relative['eave']<relative['ridge']<15:raise ValueError('Maintenance roof cannot enclose a two-block opening')
    return {'absolute_display_assumption_m':absolute,'above_display_floor_m':relative,'reference_label':trace['datum_label'],
        'inspection_reference_m':trace['inspection_level_m'],'display_floor_top_m':floor,
        'two_endpoint_sampling_bound_m':2*trace['endpoint_sampling_bound_pixels']*metres_per_pixel,'physical_datum_verified':False}


def make_component(wall,roof_dimensions,pose,top,heights,plan_openings,cancelled=lambda:False):
    centre=np.asarray(wall.centroid.coords[0]);local=(np.asarray(wall.exterior.coords)[:-1]-centre)@pose
    model=rectangular_model(*roof_dimensions,heights['eave'],heights['ridge'])
    model['outer_wall_base_outline']=[[*p,0] for p in local];model['opening_base_segments']=copy.deepcopy(plan_openings)
    blocks,placed,boundary,portals,quality=shell.build_component(model,[0,0],pose,centre,top,{'roof_sampling_cells':2048},cancelled)
    # Source lower stone bunding is represented by one display row only.
    for k in list(blocks):
        if k[1]==top and blocks[k]=='spruce_planks':blocks[k]='sandstone'
    return blocks,placed,boundary,portals,quality


def retained_seam(blocks,old,wall,boundary,portals,base,base_directory,top):
    """Retained station wins grid aliases; verify the resulting compound join."""
    aliases=[{'source_xyz':list(k),'retained_material':old[k],'proposed_material':m} for k,m in blocks.items() if k in old and old[k]!=m]
    for r in aliases:blocks[tuple(r['source_xyz'])]=r['retained_material']
    old_air={tuple(p) for p in json.loads((Path(base_directory)/'portal-air.json').read_text())}
    preserved_air=[]
    for k in old_air:
        if k in blocks:preserved_air.append(list(k));blocks.pop(k)
    combined={**old,**blocks};blocked=[];clear_air=set()
    for p in portals:
        clear=[]
        for x,y in p['columns_xy']:
            if any((x,h,y) in combined for h in range(top,top+p['headroom_blocks'])):
                blocked.append({'opening_id':p['id'],'source_cell_xy':[x,y],'reason':'retained station wall / source-opening grid alias'})
            else:
                clear.append([x,y]);clear_air.update((x,h,y) for h in range(top,top+p['headroom_blocks']))
        p['source_raster_columns_xy']=p['columns_xy'];p['columns_xy']=clear
    # Restrict to both whole building envelopes, excluding unrelated partial
    # fences/trapdoors rather than treating those as full blocking cubes.
    station=shape(next(p for p in base['parts'] if p['id']=='station')['wall_geometry_nominal_local'])
    xmin=min(wall.bounds[0],station.bounds[0])-2;ymin=min(wall.bounds[1],station.bounds[1])-2
    xmax=max(wall.bounds[2],station.bounds[2])+2;ymax=max(wall.bounds[3],station.bounds[3])+2
    cx,cy=map(math.floor,wall.centroid.coords[0])
    shapes={(x-cx,h-top,y-cy):m for (x,h,y),m in combined.items() if xmin<=x<=xmax and ymin<=y<=ymax and h>=top and ('slab' in m or m in ['spruce_planks','stone_bricks','sandstone'])}
    occupied=occupied_halves(shapes);door_heights={}
    seal=old_air|{(x,h,y) for p in portals for x,y in p['source_raster_columns_xy'] for h in range(top,top+p['headroom_blocks'])}
    for x,h,y in seal:
        if h>=top:door_heights[x-cx,y-cy]=max(door_heights.get((x-cx,y-cy),0),h-top+1)
    doors={(2*x+dx,2*y+dy):2*h for (x,y),h in door_heights.items() for dx in [0,1] for dy in [0,1]}
    half_boundary={(2*(x-cx)+dx,2*(y-cy)+dy) for x,y in boundary for dx in [0,1] for dy in [0,1]}
    audit=leak_audit(occupied,half_boundary,doors,[[x-cx,y-cy,0] for x,y in list(wall.exterior.coords)[:-1]],2)
    if audit['interior_reached_from_exterior']:raise ValueError('Maintenance/station native slab seam is open')
    return clear_air,{'retained_material_aliases':aliases,'retained_parent_portal_air_columns':preserved_air,'source_opening_blocked_aliases':blocked,'compound_native_half_shape_air_flood':audit}


def run(base_directory,pdf_directory,evidence_directory,shop_directory,output,*,allow_provisional=False,cancelled=lambda:False):
    if allow_provisional is not True:raise ValueError('Conditional maintenance review opt-in required')
    if cancelled():raise CancelledError('Maintenance review cancelled')
    output=Path(output)
    if output.exists():raise ValueError('Fresh maintenance output required')
    base_directory=Path(base_directory);pdf_directory=Path(pdf_directory);evidence_directory=Path(evidence_directory);shop_directory=Path(shop_directory)
    profile=json.loads(PROFILE.read_text())
    def pins():
        for name,sha in profile['base_pins'].items():
            if file_hash(base_directory/name)!=sha:raise ValueError('Exact aligned preshow base required')
        for key in ['source_pdf_sha256','roof_pdf_sha256']:
            if file_hash(pdf_directory/(profile[key]+'.pdf'))!=profile[key]:raise ValueError('Pinned maintenance/roof original required')
        if file_hash(evidence_directory/'wicker-architectural-outline-review.json')!=profile['outline_review_sha256']:raise ValueError('Pinned architectural outlines required')
        if file_hash(shop_directory/'quality-report.json')!=profile['shop_report_sha256'] or file_hash(shop_directory/'source-access-review/access-review.json')!=profile['access_review_sha256']:raise ValueError('Pinned shop/placement context required')
    pins();base=json.loads((base_directory/'quality-report.json').read_text());access=json.loads((shop_directory/'source-access-review/access-review.json').read_text())
    review=json.loads((evidence_directory/'wicker-architectural-outline-review.json').read_text());roof=next(r for r in review['measurements'] if r['role']=='maintenance_main_roof')
    wall=shape(next(r['wall_geometry_nominal_local'] for r in access['building_outline_role_comparisons'] if r['building']=='Maintenance'))
    a,b,c,d,e,f=access['drawing_correspondence']['affine'];pose=np.array([[a,b],[c,d]])
    if not np.allclose(pose.T@pose,np.eye(2),atol=1e-8) or np.linalg.det(pose)<0:raise ValueError('Retained unit-scale drawing pose required')
    import pymupdf
    with pymupdf.open(pdf_directory/(profile['source_pdf_sha256']+'.pdf')) as pdf:
        page=pdf[0]
        if len(pdf)!=1 or page.rotation!=90:raise ValueError('Original maintenance sheet required')
        pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width))
        if [pix.width,pix.height]!=profile['render_size'] or hashlib.sha256(pix.samples).hexdigest()!=profile['render_samples_sha256']:raise ValueError('Original maintenance render changed')
        inverse=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height));mpp=math.hypot(inverse.c,inverse.d)*UNIT
        heights=traced_heights(profile['elevation_trace'],mpp,profile['display_floor_top_m'])
        words=' '.join(page.get_text().split())
        if not all(s in words for s in ['Inspection Lvl +181.50','183.745','184000','Thatched effect roof tiles','Ride opening']):raise ValueError('Separate maintenance source levels/materials required')
        own=next(r for r in review['measurements'] if r['source_sha256']==profile['source_pdf_sha256'] and r['role']=='maintenance_outer_walls')
        source_centre=np.asarray(shape(own['geometry']).centroid.coords[0]);opening_specs=[]
        # Source-plan gap sides. Their vertical size is a display hypothesis;
        # the large west-side gap is not equated to the smaller elevation opening.
        for name,pixels in [('z-/west-plan-gap',[[252,203],[252,375]]),('z+/east-ride-gap',[[752,203],[752,279]]),('x+/service-door',[[718,376],[738,376]])]:
            points=np.asarray([list(pymupdf.Point(*p)*inverse) for p in pixels])*UNIT-source_centre
            # Place the trace on the retained footprint's corresponding wall.
            local=(np.asarray(wall.exterior.coords)[:-1]-np.asarray(wall.centroid.coords[0]))@pose
            axis=0 if name.startswith('x') else 1
            points[:,axis]=local[:,axis].min() if name.startswith('z-') else local[:,axis].max()
            opening_specs.append({'id':name,'endpoints':[[*p,0] for p in points],'width_metres':float(np.linalg.norm(points[1]-points[0])),'height_metres':2.3,'source_plan_pixels':pixels,'source_opening_height_verified':False})
        from PIL import Image,ImageDraw
        source_image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);draw=ImageDraw.Draw(source_image)
        tr=profile['elevation_trace'];draw.line([tuple(tr['ridge_pixel']),tuple(tr['eave_pixel']),tuple(tr['datum_pixel'])],fill='#e13d55',width=4)
    top=profile['display_floor_top_m'];blocks,placed,boundary,portals,quality=make_component(wall,roof['opposite_edge_mean_dimensions_metres'][::-1],pose,top,heights['above_display_floor_m'],opening_specs,cancelled)
    rows=[json.loads(l) for l in (base_directory/'voxels.jsonl').read_text().splitlines()]
    terrain={(r['x'],r['z']-1):r for r in rows if r['kind']=='terrain'};old={(r['x'],r['y'],r['z']-1):r['material'] for r in rows if r['kind']=='structure'}
    floor=shell.grid_cells(wall)|boundary
    for x,y in floor:
        if (x,y) not in terrain or terrain[x,y]['y']>=top:raise ValueError('Maintenance floor meets incompatible terrain')
        for h in range(terrain[x,y]['y']+1,top):blocks[x,h,y]='stone_bricks'
    if len(blocks)>12000:raise ValueError('Maintenance structure budget exceeded')
    portal_air,seam=retained_seam(blocks,old,placed,boundary,portals,base,base_directory,top)
    all_blocks={**old,**blocks}
    shop_cells=json.loads((shop_directory/'shell-blocks.json').read_text());protected={(r['source_xyz'][0],r['source_xyz'][2]) for r in shop_cells}
    protected|={tuple(k) for o in json.loads((shop_directory/'quality-report.json').read_text())['shop_ground_fit']['openings'] for k in o['source_cells_xy']}
    service=next(p for p in portals if p['id'].startswith('x+'))
    # The existing material-labelled paving is retained; coloured plan guides
    # and grass are excluded from the estimated pedestrian approach target.
    paving={k for k,r in terrain.items() if r['material'] in ['stone','stone_bricks','cobblestone','gray_concrete','light_gray_concrete']}
    if service['columns_xy']:flight,flight_review=paving_approach(service,top,terrain,all_blocks,protected,floor,paving,cancelled=cancelled)
    else:flight,flight_review={},{'status':'withheld_source_service_opening_aliases_retained_station','surfaces':[]}
    blocks.update(flight);all_blocks.update(flight)
    if any(all_blocks.get(tuple(r['source_xyz']))!=r['material'] for r in shop_cells):raise ValueError('Corrected shop changed')
    report=copy.deepcopy(base);report.update(version='maintenance-shell-world-v1',status='maintenance_shell_added_to_aligned_preshow_world',implementation_sha256=file_hash(__file__),profile_sha256=file_hash(PROFILE),source_parent_world_sha256=base['world']['sha256'],source_parent_world_unchanged=True)
    report['maintenance']={'wall_geometry_nominal_local':mapping(placed),'source_roof_geometry':roof,'source_pdf_sha256':profile['source_pdf_sha256'],'height_trace':heights,'source_opening_traces':opening_specs,'openings':portals,'floor_top_m':top,'floor_columns':len(floor),'new_structure_records':len(blocks),'quality':quality,'service_approach':flight_review,'station_seam':seam,
        'limitations':['Roof span and source-relative heights retained; roof centering on the existing floor/wall outline is a display assembly hypothesis.',
        'Inspection 181.50, maximum-level 183.745, landscape FFL 183.25 and comms 184.00 remain separate source roles. Floor slope and physical ODN datum remain unresolved; existing walking floor 184 is retained.',
        'West floor-plan gap is wider than the elevation ride opening; its source width is retained as a review gap with two-block display headroom, not an accepted door mechanism.',
        'Palette, one-row sandstone bunding and opening heights are illustrative. Communications annex, ride mechanisms, detailed interiors and conflicting bridge levels are not reconstructed.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='maintenance-world-',dir=output.parent) as temp:
        root=Path(temp)/'result';root.mkdir();voxel=root/'voxels.jsonl'
        with voxel.open('w') as stream:
            for r in terrain.values():stream.write(json.dumps(r)+'\n')
            for (x,h,y),m in sorted(all_blocks.items()):stream.write(json.dumps({'x':x,'y':h,'z':y+1,'kind':'structure','material':m})+'\n')
        from . import bedrock
        from .planning_world_preview import _spawn_check,_verify_archive
        parent_shop=json.loads((shop_directory/'quality-report.json').read_text());old_portals={tuple(p) for p in json.loads((base_directory/'portal-air.json').read_text())}|{tuple(p) for p in json.loads((base_directory/'basement-gap-air.json').read_text())}
        samples={'bounds':[min(k[0] for k in terrain),min(k[1] for k in terrain),max(k[0] for k in terrain)+1,max(k[1] for k in terrain)+1],'ground':{k:r['material'] for k,r in terrain.items()},'rocks':{},'boundary_blocks':0,'platform_cells':len(terrain)}
        flight_surfaces=flight_review.get('surfaces',[])
        def check(path,offset,spawn):
            if offset!=base['world']['vertical_offset_blocks']:raise ValueError('Existing world offset changed')
            report['spawn_validation']=_spawn_check(path,spawn)
            report['saved_geometry_validation']=shop.saved_check(path,offset,samples,{k:r['y'] for k,r in terrain.items()},all_blocks,parent_shop['shop_shell']['openings'],183,cancelled)
            report['native_maintenance_portals']=shell._native_air(path,offset,portal_air)
            report['preserved_parent_portals']=shell._native_air(path,offset,old_portals)
            report['native_maintenance_floor']=shell._native_surfaces(path,offset,[{'source_cell_xy':k,'walking_top_m':top} for k in sorted(floor)])
            report['native_service_approach']=shell._native_surfaces(path,offset,flight_surfaces)
            report['native_service_headroom']=shell._native_air(path,offset,{(p['source_cell_xy'][0],h,p['source_cell_xy'][1]) for p in flight_surfaces for h in [math.ceil(p['walking_top_m']),math.ceil(p['walking_top_m'])+1]})
            atomic_json(path/'MAINTENANCE-ASSUMPTIONS.json',report['maintenance'])
        world=bedrock.export_world(voxel,root,report,name='Wicker MAINTENANCE BUILT - aligned park retained',max_blocks=1_000_000,ground_depth=3,foundation_mode='chunk',post_export_check=check)
        report['world']=world;report['archive_validation']=_verify_archive(root/world['file'],root/'bedrock-world',world,cancelled)
        shutil.move(root/world['file'],root/'wicker-maintenance.mcworld');report['world']['file']='wicker-maintenance.mcworld';shutil.rmtree(root/'bedrock-world')
        source_image.save(root/'maintenance-source-heights.png');shell._preview(root,voxel,top)
        image=Image.open(root/'building-shell-preview.png');draw=ImageDraw.Draw(image);draw.rectangle((0,0,image.width,58),fill='#f9f7ee');draw.text((20,15),'MAINTENANCE BUILDING CONSTRUCTED: slab gable roof / timber walls / sandstone lower course',fill='black');draw.text((20,35),'Shop, station, aligned preshow and queue retained. Source datum, floor slope and door mechanisms remain provisional.',fill='black');image.save(root/'building-shell-preview.png')
        atomic_json(root/'quality-report.json',report);atomic_json(root/'maintenance-blocks.json',[{'source_xyz':list(k),'material':m} for k,m in sorted(blocks.items())]);atomic_json(root/'maintenance-portal-air.json',[list(p) for p in sorted(portal_air)])
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><h1>Maintenance building prototype</h1><a href="wicker-maintenance.mcworld">Download world</a><p>Source-informed maintenance shell added to the aligned park. Existing shop, preshow and queue retained. Heights/datum, floor slope and detailed opening roles remain provisional.</p><img style="max-width:100%" src="building-shell-preview.png">')
        pins();shutil.move(root,output)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['base-directory','pdf-directory','evidence-directory','shop-directory','output']:p.add_argument('--'+n,required=True)
    p.add_argument('--allow-provisional',action='store_true');a=p.parse_args(argv)
    r=run(a.base_directory,a.pdf_directory,a.evidence_directory,a.shop_directory,a.output,allow_provisional=a.allow_provisional)
    print(json.dumps({'world_sha256':r['world']['sha256'],'maintenance_records':r['maintenance']['new_structure_records']}))


if __name__=='__main__':main()
