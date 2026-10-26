"""Audit retained terrain draping against source floor claims and path steps.

Literal proposed floor annotations are never promoted to ODN design levels.
"""
from collections import Counter,deque
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from shapely.geometry import Point,shape,Polygon
from shapely.affinity import scale

from . import planning_geometry_world as geometry_world,planning_geo_preview as geo
from .generation_cycles import atomic_json,file_hash

MAX_CELLS=65536


def floor_claims(pdf,expected_sha,buildings,metres_per_point):
    import pymupdf
    pdf=Path(pdf)
    if pdf.stat().st_size>24_000_000 or file_hash(pdf)!=expected_sha:raise ValueError('Pinned original floor-annotation PDF required')
    claims=[]
    with pymupdf.open(pdf) as doc:
        if len(doc)!=1 or doc[0].rotation:raise ValueError('One unrotated reviewed plan required')
        page=doc[0];blocks=page.get_text('dict')['blocks'];lines=[(i,j,l) for i,b in enumerate(blocks) for j,l in enumerate(b.get('lines',[]))]
        if len(lines)>10000:raise ValueError('Floor annotation work budget exceeded')
        polygons=[(r,shape(r['geometry_pdf_native'])) for r in buildings['records']]
        for block_number,line_number,line in lines:
            text=''.join(s['text'] for s in line['spans']).strip();m=re.fullmatch(r'FFL\s+(\d{3}\.\d{1,2})',text)
            if not m:continue
            if len(claims)>=128:raise ValueError('Floor claim budget exceeded')
            bbox=line['bbox'];point=Point((bbox[0]+bbox[2])/2,page.rect.height-(bbox[1]+bbox[3])/2)
            links=[r for r,g in polygons if g.covers(point)]
            claims.append({'text':text,'printed_level_m':float(m[1]),'source_block':block_number,'source_line':line_number,
                'bbox_display_points':list(bbox),'annotation_xy_nominal_m':[point.x*metres_per_point,point.y*metres_per_point],
                'source_building_ids':[r['id'] for r in links],'building_labels':sorted({l['text'] for r in links for l in r['labels']}),
                'association_basis':'text centre within source fill; not a surveyed floor anchor','vertical_datum_verified':False,
                'drawing_state':'proposed','visibility_independently_verified':False,'applied_to_world':False})
    return claims


def floor_terrain_comparison(claims,buildings,heights,unit,*,raw_sampler=None):
    polygons={r['id']:scale(shape(r['geometry_pdf_native']),xfact=unit,yfact=unit,origin=(0,0)) for r in buildings['records']}
    results=[];checks=0
    for claim in claims:
        row={**claim,'comparison_status':'unresolved_building_association','datum_basis':'conditional comparison only: source FFL datum has not been tied to ODN'}
        if len(claim['source_building_ids'])!=1:results.append(row);continue
        g=polygons[claim['source_building_ids'][0]];a,b,c,d=g.bounds;values=[];source_values=[]
        for x in range(math.floor(a),math.ceil(c)):
            for y in range(math.floor(b),math.ceil(d)):
                checks+=1
                if checks>MAX_CELLS:raise ValueError('Floor terrain-comparison budget exceeded')
                if g.covers(Point(x+.5,y+.5)):
                    if (x,y) not in heights:raise ValueError('Complete building terrain coverage required')
                    values.append(heights[x,y])
                    if raw_sampler is not None:
                        value=float(raw_sampler((x,y)))
                        if not math.isfinite(value):raise ValueError('Finite original terrain samples required')
                        source_values.append(value)
        if not values:raise ValueError('No one-metre building samples')
        row.update(comparison_status='conditional_ground_range_compared',sampled_building_cells=len(values),terrain_block_minimum_odn_m=min(values),
            terrain_block_maximum_odn_m=max(values),terrain_block_relief_m=max(values)-min(values),
            printed_ffl_minus_ground_block_range_m=[claim['printed_level_m']-max(values),claim['printed_level_m']-min(values)],
            final_floor_surface_verified=False)
        if source_values:
            row.update(terrain_source_minimum_odn_m=min(source_values),terrain_source_maximum_odn_m=max(source_values),
                printed_ffl_minus_original_terrain_range_m=[claim['printed_level_m']-max(source_values),claim['printed_level_m']-min(source_values)])
        results.append(row)
    return results


def walkable_cells(sampled):
    cells=set(sampled['paving'])|{k for k,r in sampled['plan_markers'].items() if r['role']=='queue_area'}
    cells|={k for k,r in sampled.get('expansion_cells',{}).items() if r['role'] in ('paving','passage')}
    cells-=set(sampled['markers'])|set(sampled['rocks'])
    cells-={k for k,r in sampled['plan_markers'].items() if r['role']!='queue_area'}
    if len(cells)>MAX_CELLS:raise ValueError('Walkable-source cell budget exceeded')
    return cells


def path_steps(cells,heights,affine,*,cancelled=lambda:False):
    if len(cells)>MAX_CELLS or not cells<=set(heights):raise ValueError('Complete bounded path terrain coverage required')
    counts=Counter();severe=[];pairs=0
    A,B,C,D,E,N=affine
    for x,y in sorted(cells):
        if cancelled():raise CancelledError('Path-step audit cancelled')
        for q in ((x+1,y),(x,y+1)):
            if q not in cells:continue
            pairs+=1;delta=abs(heights[x,y]-heights[q]);counts[str(delta)]+=1
            if delta>=2:
                mx=(x+q[0]+1)/2;my=(y+q[1]+1)/2
                severe.append({'source_cells_xy':[[x,y],list(q)],'ground_block_odn_m':[heights[x,y],heights[q]],'step_blocks':delta,
                    'bng_midpoint_en_m':[A*mx+B*my+E,C*mx+D*my+N],'status':'needs_grade_stair_or_source_boundary_review'})
    remaining=set(cells);components=[]
    for first in sorted(cells):
        if first not in remaining:continue
        if cancelled():raise CancelledError('Path connectivity audit cancelled')
        remaining.remove(first);queue=deque([first]);count=0
        while queue:
            k=queue.popleft();count+=1
            for q in ((k[0]+1,k[1]),(k[0]-1,k[1]),(k[0],k[1]+1),(k[0],k[1]-1)):
                if q in remaining and abs(heights[k]-heights[q])<=1:remaining.remove(q);queue.append(q)
        components.append(count)
    if len(severe)>10000:raise ValueError('Path hotspot report budget exceeded')
    severe.sort(key=lambda r:(-r['step_blocks'],r['source_cells_xy']))
    return {'candidate_walkable_cells':len(cells),'neighbour_pairs_checked':pairs,'step_histogram_blocks':dict(sorted(counts.items(),key=lambda r:int(r[0]))),
        'multi_block_step_pairs':len(severe),'maximum_step_blocks':max((int(k) for k in counts),default=0),
        'components_with_at_most_one_block_step':len(components),'component_sizes':sorted(components,reverse=True),
        'hotspots':severe,'route_playability_verified':False,'source_finished_grades_verified':False,
        'scope':'local adjacent source-floor cells only; excludes drawn ride/building/boundary overlays and does not infer a complete pedestrian network'}


def courtyard_comparison(roof_pdf,data,placement,refs):
    from .mutiny_bay_review import extract_roof,ROOF
    from .courtyard_plan_expansion import geometry
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);(root/'files').mkdir();shutil.copy2(roof_pdf,root/'files'/(ROOF+'.pdf'));roof=extract_roof(root)
    ground=shape(next(r for r in geometry()[0] if r['key']=='courtyard-floor')['geometry_nominal_local'])
    mapped=refs[geo.profile()['held_out_references']['courtyard_inner_way_id']]['geometry']
    return {'ground_plan_pdf_sha256':data['expansion']['source_proof']['source_pdf_sha256'],'roof_pdf_sha256':ROOF,
        'ground_nominal_area_m2':ground.area,'roof_inner_nominal_area_m2':roof['courtyard_nominal_area_m2'],'osm_inner_area_m2':mapped.area,
        'roof_minus_ground_area_fraction':roof['courtyard_nominal_area_m2']/ground.area-1,'ground_minus_osm_area_fraction':ground.area/mapped.area-1,
        'osm_area_as_fraction_of_ground':mapped.area/ground.area,'comparison_status':'similar_source_nominal_size_osm_extent_differs',
        'same_physical_edges_verified':False,'independent_registration_verified':False,'geometry_rescaled_or_moved':False,
        'reason':'Roof/eaves and floor/wall boundaries are different roles; cross-sheet nominal size agreement does not verify geographic location or require shrinking the plan.'}


def run(config,world_directory,pdf,roof_pdf,output,*,cancelled=lambda:False):
    output=Path(output)
    if output.exists():raise ValueError('Fresh surface-audit output required')
    world_directory=Path(world_directory);report=json.loads((world_directory/'quality-report.json').read_text())
    for key in ('osm','grid','dtm'):
        if file_hash(config[key+'_path'])!=config[key+'_sha256'] or report['source_pins'][key]!=config[key+'_sha256']:raise ValueError('Pinned geographic evidence changed')
    if report['implementation_sha256']!=file_hash(geo.__file__) or report['profile_sha256']!=file_hash(geo.PROFILE_PATH):raise ValueError('Geographic implementation changed; regenerate before auditing')
    world=world_directory/report['world']['file']
    if file_hash(world)!=report['world']['sha256']:raise ValueError('Saved geographic world changed')
    data=geometry_world.read_inputs(config['geometry_request'])
    if report['planning_source_pins']!={n:config['geometry_request'][n+'_sha256'] for n in data}:raise ValueError('Planning evidence differs from saved world')
    sampled=geometry_world.rasterize(data,cancelled=cancelled)
    from .horizontal_grid import OSTN15Transform
    project=OSTN15Transform('EPSG:4326','EPSG:27700',{'method':'ostn15-bng-v1','path':config['grid_path'],'sha256':config['grid_sha256']})
    placement,refs=geo.alignment(data,json.loads(Path(config['osm_path']).read_text()),project)
    if placement!=report['alignment']:raise ValueError('Saved alignment differs from recomputed source fit')
    heights,_=geo.terrain_heights(sampled,placement['nominal_local_xy_to_bng_en_affine'],config['dtm_path'],cancelled=cancelled)
    saved={tuple(r['source_cell_xy']):r['surface_odn_block_m'] for r in json.loads((world_directory/'terrain-samples.json').read_text())}
    if heights!=saved:raise ValueError('Saved terrain samples differ from pinned raster')
    unit=geo.profile()['source_metres_per_native_point'];claims=floor_claims(pdf,data['layout']['document_sha256'],data['buildings'],unit)
    import rasterio
    with rasterio.open(config['dtm_path']) as terrain_source:
        A,B,C,D,E,N=placement['nominal_local_xy_to_bng_en_affine']
        def raw_sample(k):
            x,y=k[0]+.5,k[1]+.5;value=next(terrain_source.sample([(A*x+B*y+E,C*x+D*y+N)],masked=True))[0]
            if np.ma.is_masked(value):raise ValueError('Original terrain nodata at building sample')
            return value
        levels=floor_terrain_comparison(claims,data['buildings'],heights,unit,raw_sampler=raw_sample)
    paths=path_steps(walkable_cells(sampled),heights,placement['nominal_local_xy_to_bng_en_affine'],cancelled=cancelled)
    courtyard=courtyard_comparison(roof_pdf,data,placement,refs)
    receipt={'version':'planning-surface-audit-v1','status':'source_floor_and_terrain_risks_reviewed','source_pdf_sha256':file_hash(pdf),
        'source_world_sha256':file_hash(world),'geographic_profile_sha256':file_hash(geo.PROFILE_PATH),'implementation_sha256':file_hash(__file__),
        'floor_claims':levels,'path_steps':paths,'courtyard_comparison':courtyard,'nearby_building_comparison':placement['held_out_map_checks']['nearby_building'],
        'world_blocks_changed':0,'floor_levels_applied':0,'source_vertical_datum_verified':False,'production_placement_eligible':False,
        'training_labels_generated':0,'minecraft_import_tested':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='surface-audit-',dir=output.parent) as temporary:
        root=Path(temporary)/'result';root.mkdir();atomic_json(root/'surface-audit.json',receipt)
        _images(root,world_directory,paths,claims,pdf,sampled)
        if file_hash(world)!=receipt['source_world_sha256']:raise ValueError('World changed during read-only audit')
        if file_hash(pdf)!=data['layout']['document_sha256'] or file_hash(roof_pdf)!=courtyard['roof_pdf_sha256']:raise ValueError('Original source PDF changed during audit')
        (root/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Wicker finished-floor and path review</title><h1>Finished floors and terrain steps</h1><p>Proposed FFL claims are compared conditionally with ODN ground blocks. Source floor datum remains unverified; no world geometry or levels are changed.</p><p><a href="surface-audit.json">Full audit</a></p><img style="max-width:100%" src="path-step-hotspots.png"><img style="max-width:100%" src="source-floor-annotations.png">')
        shutil.move(str(root),output)
    return receipt


def _images(root,world_directory,paths,claims,pdf,sampled):
    from PIL import Image,ImageDraw
    import pymupdf
    # Source-cell diagram follows exactly the same retained source grid as the world.
    a,b,c,d=sampled['bounds'];unit=4;im=Image.new('RGB',((c-a)*unit+48,(d-b)*unit+100),'#f7f6ef');draw=ImageDraw.Draw(im)
    from .rock_world_render import colour
    def p(k):return (24+(k[0]-a+.5)*unit,42+(d-k[1]-.5)*unit)
    for k in walkable_cells(sampled):
        x,y=p(k);draw.rectangle((x-2,y-2,x+1,y+1),fill='#c0c9b5')
    for k,r in sampled['plan_markers'].items():
        x,y=p(k);draw.rectangle((x-2,y-2,x+1,y+1),fill=colour(r['material']))
    for row in paths['hotspots']:
        x,y=p(row['source_cells_xy'][0]);draw.ellipse((x-3,y-3,x+3,y+3),fill='#d62828')
    draw.text((20,12),'Terrain-draped path review: red = adjacent source floor cells differing by two or more blocks',fill='black')
    draw.text((20,im.height-35),'Ground sampling / source interpretation review required. This is not a verified navigable network.',fill='black');im.save(root/'path-step-hotspots.png')
    with pymupdf.open(pdf) as doc:
        page=doc[0];clips=[]
        for claim in claims:
            r=pymupdf.Rect(claim['bbox_display_points']);r.x0-=30;r.x1+=30;r.y0-=30;r.y1+=20
            pix=page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=r);clips.append((claim,Image.frombytes('RGB',[pix.width,pix.height],pix.samples)))
    canvas=Image.new('RGB',(max([600]+[im.width for _,im in clips])+30,sum(im.height+45 for _,im in clips)+30),'white');draw=ImageDraw.Draw(canvas);y=10
    for claim,pic in clips:
        draw.text((10,y),', '.join(claim['building_labels'])+' | '+claim['text']+' | proposed source, datum unverified',fill='black');canvas.paste(pic,(10,y+24));y+=pic.height+45
    canvas.save(root/'source-floor-annotations.png')


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','world-directory','pdf','roof-pdf','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv);path=Path(args.config).resolve()
    if path.stat().st_size>32768:raise ValueError('Bounded geographic request required')
    config=json.loads(path.read_text())
    for name in ('osm','grid','dtm'):config[name+'_path']=str((path.parent/config[name+'_path']).resolve())
    for name in ('layout','paving','gaps','buildings','markings','expansion'):
        if name+'_path' in config['geometry_request']:config['geometry_request'][name+'_path']=str((path.parent/config['geometry_request'][name+'_path']).resolve())
    r=run(config,args.world_directory,args.pdf,args.roof_pdf,args.output)
    print(json.dumps({'status':r['status'],'floor_claims':len(r['floor_claims']),'multi_block_step_pairs':r['path_steps']['multi_block_step_pairs'],'world_blocks_changed':0}))


if __name__=='__main__':main()
