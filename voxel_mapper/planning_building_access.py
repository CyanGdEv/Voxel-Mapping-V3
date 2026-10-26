"""Source-pinned architectural access review in the current planning frame.

Does not change the world or promote roof outlines to external walls.
"""
import argparse
from concurrent.futures import CancelledError
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from shapely.affinity import affine_transform,scale
from shapely.geometry import LineString,Point,Polygon,shape,mapping

from .drawing_page_tools import pixel_to_native
from .generation_cycles import atomic_json,file_hash
from . import planning_geo_preview as geo,planning_floor_preview as floor

PROFILE=Path(__file__).parent/'data/wicker-building-access.json'
UNIT=100*.0254/72


def rigid_candidates(source,target):
    """Preserve printed metric scale, enumerate rectangle half-turn ambiguity."""
    x=np.asarray(source.exterior.coords)[:-1];y=np.asarray(target.exterior.coords)[:-1]
    if x.shape!=(4,2) or y.shape!=(4,2) or not np.isfinite(x).all() or not np.isfinite(y).all() or min(source.area,target.area)<=0:
        raise ValueError('Finite nondegenerate four-corner outlines required')
    if source.exterior.is_ccw!=target.exterior.is_ccw:y=y[::-1]
    rows=[]
    for shift in range(4):
        q=np.roll(y,shift,axis=0);u,_,vt=np.linalg.svd((x-x.mean(0)).T@(q-q.mean(0)));r=u@vt
        if np.linalg.det(r)<0:continue
        t=q.mean(0)-x.mean(0)@r;err=np.linalg.norm(x@r+t-q,axis=1)
        rows.append({'corner_shift':shift,'affine':[r[0,0],r[1,0],r[0,1],r[1,1],*t],
                     'shop_corner_rms_m':float(np.sqrt(np.mean(err**2)))})
    return sorted(rows,key=lambda r:r['shop_corner_rms_m'])[:2]


def select_fit(roofs,targets):
    rows=rigid_candidates(roofs['shop_main_roof'],targets['Shop'])
    for row in rows:
        row['held_out_building_centroid_distances_m']={label:affine_transform(roofs[role],row['affine']).centroid.distance(targets[label].centroid)
            for role,label in [('station_main_roof','Station'),('maintenance_main_roof','Maintenance')]}
    passing=[r for r in rows if r['shop_corner_rms_m']<.25 and max(r['held_out_building_centroid_distances_m'].values())<1]
    if len(passing)!=1:raise ValueError('No unique fixed-scale drawing correspondence; preserve ambiguity')
    return passing[0],rows


def source_points(page,pix,points,furniture=None):
    import pymupdf
    xy=np.asarray(points,dtype=float)
    if xy.ndim!=2 or xy.shape[1]!=2 or not 2<=len(xy)<=8 or not np.isfinite(xy).all() or np.any(xy<0) or np.any(xy>=[pix.width,pix.height]):
        raise ValueError('Bounded finite source pixel coordinates required')
    matrix=pymupdf.Matrix(pixel_to_native(page,pix.width,pix.height))
    native=np.asarray([list(pymupdf.Point(*p)*matrix) for p in xy])
    if furniture is not None:native=(native-furniture[2])@np.linalg.inv(furniture[:2])
    return native*UNIT


def hotspot_links(hotspots,features,floors):
    rows=[]
    for step in hotspots:
        cells=[tuple(k) for k in step['source_cells_xy']];inside=[k for k in cells if k in floors]
        if len(inside)!=1:raise ValueError('Each perimeter pair must have exactly one floor cell')
        labels=floors[inside[0]]['labels'];point=Point(np.mean(np.asarray(cells),axis=0)+.5)
        nearby=[{'feature_id':f['id'],'role':f['role'],'distance_m':point.distance(shape(f['geometry_nominal_local']))}
                for f in features if f['building'] in labels]
        rows.append({**step,'building_labels':labels,'source_access_distances':sorted(nearby,key=lambda r:(r['distance_m'],r['feature_id'])),
                     'doorway_identified':False,'geometry_changed':False,
                     'decision':'Proximity alone does not identify an entrance or prescribe a stair connection.'})
    return rows


def run(config,preview_directory,pdf_directory,evidence_directory,output,*,cancelled=lambda:False):
    import hashlib
    import pymupdf
    from PIL import Image,ImageDraw
    output=Path(output);preview_directory=Path(preview_directory);pdf_directory=Path(pdf_directory);evidence_directory=Path(evidence_directory)
    if output.exists():raise ValueError('Fresh architectural access review output required')
    if cancelled():raise CancelledError('Access review cancelled')
    profile=json.loads(PROFILE.read_text());report=json.loads((preview_directory/'quality-report.json').read_text())
    if report['implementation_sha256']!=file_hash(floor.__file__) or report['geographic_implementation_sha256']!=file_hash(geo.__file__):raise ValueError('Current pinned floor/geographic implementations required')
    world=preview_directory/report['world']['file'];world_sha=file_hash(world)
    if world_sha!=report['world']['sha256']:raise ValueError('Pinned floor world required')
    from . import planning_geometry_world as geometry_world
    data=geometry_world.read_inputs(config['geometry_request'])
    if report['planning_source_pins']!={n:config['geometry_request'][n+'_sha256'] for n in data}:raise ValueError('Planning source differs from saved world')
    inputs={}
    for n,sha in profile['review_input_sha256'].items():
        p=evidence_directory/n
        if p.stat().st_size>2_000_000 or file_hash(p)!=sha:raise ValueError('Architectural review source pin mismatch')
        inputs[n]=json.loads(p.read_text())
    furniture=np.asarray(inputs['wicker-shop-floor-scale-review.json']['roof_to_floor_matrix_row_convention'])
    if furniture.shape!=(3,2) or inputs['wicker-shop-floor-scale-review.json']['heldout_max_residual_pdf_points']>.25:raise ValueError('Reviewed drawing-furniture normalization required')
    roofs={};walls={};features=[];source_pins={};images={}
    for key in ['floor_sheet','roof_sheet']:
        if cancelled():raise CancelledError('Access review cancelled')
        annotation=profile[key];sha=annotation['source_sha256'];pdf=pdf_directory/(sha+'.pdf')
        if pdf.stat().st_size>24_000_000 or file_hash(pdf)!=sha:raise ValueError('Original architectural PDF hash mismatch')
        source_pins[key]=sha
        with pymupdf.open(pdf) as doc:
            if len(doc)!=1 or doc[0].rotation!=90:raise ValueError('Reviewed single rotated architectural sheet required')
            page=doc[0];pix=page.get_pixmap(matrix=pymupdf.Matrix(1888/page.rect.width,1888/page.rect.width),alpha=False)
            if [pix.width,pix.height]!=annotation['render_size_pixels'] or hashlib.sha256(pix.samples).hexdigest()!=annotation['render_samples_sha256']:raise ValueError('Annotated architectural render mismatch')
            image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);draw=ImageDraw.Draw(image)
            normalized=furniture if key=='floor_sheet' else None
            for role,points in annotation['outlines_pixels'].items():
                g=Polygon(source_points(page,pix,points,normalized));(walls if normalized is not None else roofs)[role]=g
            if key=='floor_sheet':
                for feature in profile['features']:
                    xy=source_points(page,pix,feature['pixels'],furniture);g=LineString(xy) if feature['role']=='door_opening' else Polygon(xy)
                    features.append({**feature,'source_pdf_sha256':sha,'geometry_roof_sheet_metres':mapping(g),'physical_access_verified':False,'threshold_level_m':None})
                    draw.line([tuple(p) for p in feature['pixels']]+([tuple(feature['pixels'][0])] if len(feature['pixels'])>2 else []),fill='#d12e84',width=4)
                    draw.text(tuple(feature['pixels'][0]),feature['id'],fill='#a00050')
                # Existing reviewed shop trace is in the same unrotated native floor frame.
                for opening in inputs['wicker-shop-local-floor.json']['openings']:
                    native=np.asarray(opening['raw_native_endpoints']);xy=((native-furniture[2])@np.linalg.inv(furniture[:2]))*UNIT
                    features.append({'id':'shop-'+opening['id'],'building':'Shop','role':'door_opening','source_pdf_sha256':sha,
                        'geometry_roof_sheet_metres':mapping(LineString(xy)),'physical_access_verified':False,'threshold_level_m':None,
                        'interpretation':opening['drawing_role']})
                local=inputs['wicker-shop-local-floor.json'];native=np.asarray(local['native_outer_corners'])
                walls['shop_outer_walls']=Polygon(((native-furniture[2])@np.linalg.inv(furniture[:2]))*UNIT)
            images[key]=image
    targets={label:scale(shape(r['geometry_pdf_native']),xfact=geo.profile()['source_metres_per_native_point'],yfact=geo.profile()['source_metres_per_native_point'],origin=(0,0))
             for r in data['buildings']['records'] for label in [l['text'] for l in r['labels']] if label in ['Shop','Station','Maintenance']}
    fit,hypotheses=select_fit(roofs,targets);affine=fit['affine']
    for feature in features:
        g=affine_transform(shape(feature.pop('geometry_roof_sheet_metres')),affine);feature['geometry_nominal_local']=mapping(g)
        if g.geom_type=='LineString':feature['sampled_opening_width_m']=g.length
        else:feature['sampled_outline_area_m2']=g.area
    floor_rows=json.loads((preview_directory/'floor-cells.json').read_text())
    if len(floor_rows)!=report['floor_cells']:raise ValueError('Floor receipt coverage mismatch')
    receipt_pins={n:file_hash(preview_directory/n) for n in ['quality-report.json','floor-cells.json']}
    floors={tuple(r['source_cell_xy']):r for r in floor_rows}
    if len(floors)!=len(floor_rows):raise ValueError('Duplicate floor receipt cells')
    comparisons=[]
    for label in ['Shop','Station','Maintenance']:
        wall=affine_transform(walls[label.lower()+'_outer_walls'],affine);roof=affine_transform(roofs[label.lower()+'_main_roof'],affine)
        samples=[k for k,v in floors.items() if label in v['labels']]
        outside=sum(not wall.covers(Point(k[0]+.5,k[1]+.5)) for k in samples)
        comparisons.append({'building':label,'current_plate_source_area_m2':targets[label].area,'architectural_roof_iou':targets[label].intersection(roof).area/targets[label].union(roof).area,
            'architectural_wall_area_m2':wall.area,'existing_floor_sample_cells':len(samples),'floor_samples_outside_architectural_wall':outside,
            'wall_geometry_nominal_local':mapping(wall),'decision':'Current plate follows landscape roof envelope; outer-wall trace remains a separate proposed source role.'})
    links=hotspot_links(report['floor_perimeter_multi_block_steps'],features,floors)
    result={'version':'planning-building-access-review-v1','status':'source_access_and_wall_roles_reviewed','world_geometry_additions':0,
        'source_floor_datum_verified':False,'building_access_verified':False,'minecraft_import_tested':False,'source_pins':source_pins,
        'review_input_sha256':profile['review_input_sha256'],'profile_sha256':file_hash(PROFILE),'implementation_sha256':file_hash(__file__),
        'reviewed_floor_preview_sha256':world_sha,'reviewed_floor_report_sha256':file_hash(preview_directory/'quality-report.json'),
        'reviewed_floor_cells_sha256':file_hash(preview_directory/'floor-cells.json'),'planning_source_pins':report['planning_source_pins'],
        'drawing_correspondence':fit,'competing_half_turn_hypotheses':hypotheses,'geographic_registration_verified':False,
        'source_annotation_basis':profile['interpretation'],'drawing_furniture_normalization_is_provisional':True,
        'features':features,'building_outline_role_comparisons':comparisons,'unresolved_perimeter_transitions':links,
        'limitations':['Drawing agreement is not independent physical registration.','The two station flights are proposed plan traces; riser count, landing connections and absolute heights remain unset.',
            'A landscape roof envelope is not an external wall or an established walkable floor perimeter.','No route, ramp gradient, headroom or Minecraft-client navigation is verified.']}
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='building-access-',dir=output.parent) as temp:
        stage=Path(temp)/'review';stage.mkdir()
        images['floor_sheet'].save(stage/'architectural-access-source.png')
        _overview(stage,comparisons,features,links)
        # EPSG:27700 is a projected review GeoJSON, not RFC7946 longitude/latitude.
        bng=report['alignment']['nominal_local_xy_to_bng_en_affine']
        collection={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:27700'}},'features':[
            {'type':'Feature','geometry':mapping(affine_transform(shape(f['geometry_nominal_local']),bng)),
             'properties':{k:v for k,v in f.items() if k!='geometry_nominal_local'}} for f in features]}
        atomic_json(stage/'access-bng.geojson',collection)
        if cancelled():raise CancelledError('Access review cancelled')
        if file_hash(world)!=world_sha:raise ValueError('Original floor world changed')
        if any(file_hash(preview_directory/n)!=sha for n,sha in receipt_pins.items()):raise ValueError('Floor review inputs changed')
        if any(file_hash(pdf_directory/(sha+'.pdf'))!=sha for sha in source_pins.values()):raise ValueError('Architectural PDFs changed')
        if any(file_hash(evidence_directory/n)!=sha for n,sha in profile['review_input_sha256'].items()):raise ValueError('Architectural review inputs changed')
        geometry_world.read_inputs(config['geometry_request'])
        atomic_json(stage/'access-review.json',result)
        (stage/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Wicker architectural access review</title><h1>Proposed architectural access and wall roles</h1><p>Read-only review; original world unchanged. Magenta: openings/stair outlines. Red: unresolved station perimeter samples. Roof-based floor plates and source wall traces remain separate.</p><img style="max-width:100%" src="access-overview.png"><p><a href="access-review.json">Evidence and assumptions</a></p><a href="architectural-access-source.png">Annotated original floor-plan render</a>')
        shutil.move(stage,output)
    return result


def _overview(output,comparisons,features,links):
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(1200,940),'#faf9f3');draw=ImageDraw.Draw(image)
    def xy(p):return (40+(p[0]-65)*15,820-(p[1]-85)*15)
    for r in comparisons:
        g=shape(r['wall_geometry_nominal_local']);draw.line([xy(p) for p in g.exterior.coords],fill='#2875a1',width=3)
        draw.text(xy(g.centroid.coords[0]),r['building'],fill='black')
    for f in features:
        g=shape(f['geometry_nominal_local']);points=list(g.exterior.coords) if g.geom_type=='Polygon' else list(g.coords)
        draw.line([xy(p) for p in points],fill='#cb3287',width=4);draw.text(xy(points[0]),f['id'],fill='#882056')
    for s in links:
        p=np.mean(s['source_cells_xy'],axis=0)+.5;x,y=xy(p);draw.ellipse((x-5,y-5,x+5,y+5),fill='#e32929')
    draw.text((20,18),'Proposed source wall outlines (blue), openings / stairs (magenta), unresolved station edge (red)',fill='black')
    draw.text((20,40),'Fixed-scale drawing correspondence; source datum / access levels unverified. Original world unchanged.',fill='black')
    image.save(output/'access-overview.png')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ['config','preview-directory','pdf-directory','evidence-directory','output']:parser.add_argument('--'+n,required=True)
    args=parser.parse_args(argv);p=Path(args.config).resolve()
    if p.stat().st_size>32768:raise ValueError('Bounded config required')
    config=json.loads(p.read_text())
    for n in ['layout','paving','gaps','buildings','markings','expansion']:config['geometry_request'][n+'_path']=str((p.parent/config['geometry_request'][n+'_path']).resolve())
    r=run(config,args.preview_directory,args.pdf_directory,args.evidence_directory,args.output)
    print(json.dumps({'features':len(r['features']),'unresolved_perimeter_pairs':len(r['unresolved_perimeter_transitions']),'world_geometry_additions':0}))


if __name__=='__main__':main()
