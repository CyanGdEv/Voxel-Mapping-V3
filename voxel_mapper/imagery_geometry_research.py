"""Imagery-derived geometry candidates outside explicitly protected plan coverage."""
import argparse
from collections import Counter
from html import escape
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image
from pyproj import Transformer
from affine import Affine
from rasterio.features import rasterize, shapes
from rasterio.transform import from_bounds
from scipy import ndimage
from shapely.geometry import shape, mapping, box, Polygon
from shapely.ops import transform, unary_union

from . import aerial_material_research as aerial, map_planning_research as maps, web_evidence as web
from .generation_cycles import atomic_json, file_hash
from .desktop_memory import digest

VERSION='imagery-gap-geometry-v1'
COLOURS={'building':(225,115,40),'water':(50,150,240),'paving':(240,205,55),
    'unclassified_hard_surface':(160,160,160),'unclassified_blue_surface':(120,90,190),'queue':(245,70,140)}


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{
        'version','site_id','site','imagery','map_source','protected_plan_coverage','options','semantic_model'}:
        raise ValueError('Versioned imagery gap-geometry request required')
    if not isinstance(config.get('imagery'),dict):raise ValueError('Aerial imagery request required')
    aerial.validate(config['imagery'])
    if config.get('site_id')!=config['imagery']['site_id'] or config.get('site')!=config['imagery']['site']:
        raise ValueError('Imagery and gap-geometry site identities must agree')
    if 'map_source' in config:maps.validate_source(config['map_source'])
    coverage=config.get('protected_plan_coverage')
    if coverage is not None:
        if not isinstance(coverage,dict) or set(coverage)!={'file','sha256','crs'}:raise ValueError('Pinned protected plan coverage and CRS required')
        if not isinstance(coverage['file'],str) or not maps.re.fullmatch('[0-9a-f]{64}',coverage['sha256']):raise ValueError('Protected coverage file and pin required')
        Transformer.from_crs(coverage['crs'],3857,always_xy=True)
    if 'semantic_model' in config:
        spec=config['semantic_model']
        if not isinstance(spec,dict) or set(spec)!={'file','sha256'} or not isinstance(spec['file'],str) or not maps.re.fullmatch('[0-9a-f]{64}',spec['sha256']):raise ValueError('Pinned semantic model required')
    settings=config.get('options',{})
    limits={'min_area_m2':(1.,100.,6.),'max_growth_m':(.25,8.,3.),'colour_distance':(5.,35.,18.),
        'max_features':(1,512,256),'simplify_pixels':(0.,2.,.5)}
    if not isinstance(settings,dict) or set(settings)-set(limits):raise ValueError('Known geometry extraction options required')
    result={}
    for key,(low,high,default) in limits.items():
        value=settings.get(key,default)
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high or (key=='max_features' and type(value) is not int):
            raise ValueError('Bounded geometry extraction settings required')
        result[key]=value
    return result


def protected_coverage(spec):
    if spec is None:return Polygon(),None
    path=Path(spec['file'])
    if not path.is_file() or path.stat().st_size>2000000 or file_hash(path)!=spec['sha256']:raise ValueError('Protected plan coverage changed or exceeded budget')
    data=json.loads(path.read_text());features=data.get('features',[])
    if data.get('type')!='FeatureCollection' or not isinstance(features,list) or len(features)>500:raise ValueError('Bounded protected coverage FeatureCollection required')
    project=Transformer.from_crs(spec['crs'],3857,always_xy=True);geoms=[]
    for feature in features:
        geom=shape(feature['geometry'])
        if geom.geom_type not in ('Polygon','MultiPolygon') or not geom.is_valid or geom.is_empty or geom.has_z:raise ValueError('Valid protected 2D polygons required')
        projected=transform(project.transform,geom)
        if not projected.is_valid or not np.isfinite(projected.bounds).all():raise ValueError('Finite projected coverage required')
        geoms.append(projected)
    if file_hash(path)!=spec['sha256']:raise ValueError('Protected plan coverage changed while reading')
    return unary_union(geoms) if geoms else Polygon(),spec['sha256']


def _mask(geoms,size,affine):
    items=[(mapping(g),1) for g in geoms if not g.is_empty]
    return rasterize(items,out_shape=size,transform=affine,fill=0,dtype='uint8').astype(bool) if items else np.zeros(size,bool)


def reference_rows(path):
    # Reuse validated OSM polygon/relation/hole parsing; no guessed closures.
    maps._xml(Path(path).read_bytes())
    from .osm_provisional_alignment import osm_collection
    collection,pin,skipped=osm_collection(path);project=Transformer.from_crs(4326,3857,always_xy=True)
    result=[]
    for feature in collection['features']:
        p=feature['properties'];kind=None
        if p.get('footway')=='queue' or p.get('queue')=='yes':kind='queue'
        elif p.get('building','no')!='no' or p.get('building:part','no')!='no':kind='building'
        elif p.get('natural')=='water' or p.get('water'):kind='water'
        elif p.get('highway') in ('footway','pedestrian','path','steps') or p.get('area:highway') in ('pedestrian','footway'):kind='paving'
        if kind is None:continue
        geom=transform(project.transform,shape(feature['geometry']))
        if geom.is_empty or not geom.is_valid or geom.has_z:continue
        if kind in ('building','water') and geom.geom_type not in ('Polygon','MultiPolygon'):continue
        result.append({'id':feature['id'],'kind':kind,'geometry':geom,'tags':p})
    return result,pin,skipped


def extract(rgba,extent,bounds,refs,protected,options,*,footer=32,cancelled=lambda:False,deadline=None):
    deadline=deadline or time.monotonic()+180;height,width=rgba.shape[:2]
    if width*height>4000000:raise ValueError('Geometry raster pixel budget exceeded')
    affine=from_bounds(*aerial._extent(extent),width,height);size=(height,width)
    project=Transformer.from_crs(4326,3857,always_xy=True);inverse=Transformer.from_crs(3857,4326,always_xy=True)
    aoi=transform(project.transform,box(*bounds));scale=math.cos(math.radians((bounds[1]+bounds[3])/2))
    pixel=max(abs(affine.a),abs(affine.e));valid=(rgba[:,:,3]==255)&_mask([aoi],size,affine)
    valid[max(0,height-footer):,:]=False
    blocked=_mask([protected],size,affine);valid&=~blocked
    rgb=ndimage.median_filter(rgba[:,:,:3],size=(3,3,1)).astype(np.float32)
    lab=aerial._lab(rgb).astype(np.float32);luminance=rgb@np.array([.2126,.7152,.0722],np.float32)
    green=(rgb[:,:,1]>rgb[:,:,0]*1.10)&(rgb[:,:,1]>rgb[:,:,2]*1.08)
    blue=(rgb[:,:,2]>rgb[:,:,0]*1.12)&(rgb[:,:,2]>rgb[:,:,1]*1.08)
    shadow=luminance<45;labels=np.zeros(size,np.uint8);proposals=[];held=[]
    refs=[r for r in refs if r['geometry'].intersects(aoi)]
    if len(refs)>512:raise ValueError('Map-reference geometry budget exceeded')
    building_masks=_mask([r['geometry'] for r in refs if r['kind']=='building'],size,affine)
    walking=_mask([r['geometry'].buffer(2*pixel) if 'LineString' in r['geometry'].geom_type else r['geometry'] for r in refs if r['kind'] in ('paving','queue')],size,affine)
    def check():aerial._check(cancelled,deadline)
    def polygons(mask,kind,reference=None):
        check();found=[]
        for number,(geometry,value) in enumerate(shapes(mask.astype(np.uint8),mask=mask,transform=affine,connectivity=4)):
            if number%128==0:check()
            if not value:continue
            g=shape(geometry)
            if g.area*scale**2<options['min_area_m2']:continue
            g=g.simplify(pixel*options['simplify_pixels'],preserve_topology=True).intersection(aoi).difference(protected)
            if g.is_empty or not g.is_valid or g.geom_type not in ('Polygon','MultiPolygon'):continue
            if g.area*scale**2<options['min_area_m2']:continue
            if len(json.dumps(mapping(g)))>1000000:held.append({'kind':kind,'reason':'polygon_geometry_byte_budget'});continue
            if kind=='unclassified_hard_surface' and np.any(walking&mask):
                # Test this component rather than unrelated walking pixels.
                component=_mask([g],size,affine)
                actual_kind='paving' if np.any(component&walking) else kind
            else:actual_kind=kind
            props={'kind':actual_kind,'geometry_source':'rgb_colour_region',
                'boundary_role':'roof_colour_region_not_ground_footprint' if actual_kind=='building' else 'visible_colour_region_boundary',
                'reference_id':reference,'approx_ground_area_m2':round(g.area*scale**2,3),
                'coverage_status':'outside_supplied_protected_plan_coverage','protected_plan_overlap_m2':g.intersection(protected).area,
                'physical_identity_verified':False,'registration_verified':False,'training_eligible':False,
                'extraction_is_complete':False}
            found.append({'type':'Feature','geometry':mapping(transform(inverse.transform,g)),'properties':props})
        return found
    # Map polygons seed class identity. Region growth is constrained by both
    # RGB evidence and a small reference neighbourhood, not copied as new outlines.
    for index,ref in enumerate(sorted(refs,key=lambda r:(r['kind'],r['id']))):
        check()
        if ref['kind'] not in ('building','water'):continue
        window=ref['geometry'].buffer(options['max_growth_m']/scale).intersection(aoi)
        if window.is_empty:continue
        minx,miny,maxx,maxy=window.bounds
        c0=max(0,int((minx-affine.c)/affine.a));c1=min(width,int(math.ceil((maxx-affine.c)/affine.a)))
        r0=max(0,int((maxy-affine.f)/affine.e));r1=min(height,int(math.ceil((miny-affine.f)/affine.e)))
        if c1<=c0 or r1<=r0:continue
        local_affine=affine*Affine.translation(c0,r0);local_size=(r1-r0,c1-c0)
        seed=_mask([ref['geometry']],local_size,local_affine);interior=ndimage.binary_erosion(seed,iterations=2)
        if interior.sum()<16:interior=seed
        available=valid[r0:r1,c0:c1].copy()
        if ref['kind']=='building':available&=~green[r0:r1,c0:c1]&~shadow[r0:r1,c0:c1]
        core=interior&available
        if core.sum()<16:held.append({'reference_id':ref['id'],'reason':'insufficient_visible_seed_pixels'});continue
        prototype=np.median(lab[r0:r1,c0:c1][core],axis=0)
        allowed=(np.linalg.norm(lab[r0:r1,c0:c1]-prototype,axis=2)<=options['colour_distance'])&available
        allowed&=_mask([window],local_size,local_affine)
        allowed&=labels[r0:r1,c0:c1]==0
        grown=ndimage.binary_propagation(core&allowed,mask=allowed)
        mask=np.zeros(size,bool);mask[r0:r1,c0:c1]=grown
        candidates=polygons(mask,ref['kind'],ref['id']);proposals.extend(candidates)
        if candidates:labels[mask]=1 if ref['kind']=='building' else 2
    # Anonymous hard/blue surfaces remain candidates; colour alone cannot
    # identify an unmapped building, pond, or queue.
    hard=valid&~green&~shadow&~blue&~building_masks&(labels==0)
    proposals.extend(polygons(hard,'unclassified_hard_surface'))
    proposals.extend(polygons(valid&blue&(labels==0),'unclassified_blue_surface'))
    queues=[]
    for ref in refs:
        if ref['kind']!='queue' or ref['geometry'].geom_type not in ('LineString','MultiLineString'):continue
        geom=ref['geometry'].intersection(aoi).difference(protected)
        if geom.is_empty or geom.geom_type not in ('LineString','MultiLineString'):continue
        probe=_mask([geom.buffer(2*pixel)],size,affine);visible=probe&valid&~green&~shadow&~building_masks&(labels!=1)
        fraction=float(visible.sum()/max(1,probe.sum()))
        queues.append({'type':'Feature','id':ref['id'],'geometry':mapping(transform(inverse.transform,geom)),
            'properties':{'kind':'queue','reference_id':ref['id'],'geometry_source':'mapped_queue_centreline',
                'rgb_visible_support_fraction':round(fraction,4),'rgb_support_status':('mapped_reference_covered_not_visible' if ref['tags'].get('covered') in ('yes','true','1') or ref['tags'].get('tunnel')=='yes' else 'supported_colour_context' if fraction>=.35 else 'occluded_or_unsupported'),
                'width_inferred':False,'switchbacks_invented':False,'registration_verified':False,'physical_identity_verified':False,
                'training_eligible':False,'protected_plan_overlap_m':geom.intersection(protected).length}})
    proposals.sort(key=lambda f:(f['properties']['kind'].startswith('unclassified'),-f['properties']['approx_ground_area_m2']))
    total=0;selected=[]
    for feature in proposals[:options['max_features']]:
        size_bytes=len(json.dumps(feature))
        if total+size_bytes>8000000:break
        selected.append(feature);total+=size_bytes
    truncated=len(proposals)-len(selected);proposals=selected
    for i,f in enumerate(proposals):f['id']='rgb-region-'+str(i)
    return proposals,queues,{'references_in_area':len(refs),'map_reference_counts':dict(Counter(r['kind'] for r in refs)),'protected_pixels_excluded':int(blocked.sum()),
        'shadow_pixels_unresolved':int((valid&shadow).sum()),'withheld_references':held[:128],
        'deferred_candidates':truncated,'queue_anchors':len(queues),'queue_lines_with_rgb_support':sum(q['properties']['rgb_support_status']=='supported_colour_context' for q in queues)}


def run(config,output,cache,*,cancelled=lambda:False,progress=lambda v:None,parent_budget=None,run_deadline=None):
    options=validate(config);output=Path(output)
    if output.exists():raise ValueError('Fresh imagery-geometry output required')
    output.mkdir(parents=True);atomic_json(output/'config.json',config)
    deadline=min(time.monotonic()+600,run_deadline or float('inf'));budget=web.Budget(64000000,parent=parent_budget)
    rgb=aerial.run(config['imagery'],output/'aerial',cache,cancelled=cancelled,progress=progress,parent_budget=budget,run_deadline=deadline)
    if rgb['status']!='aerial_rgb_sampled':raise ValueError('Available georeferenced RGB imagery required for geometry research')
    protected,pin=protected_coverage(config.get('protected_plan_coverage'));refs=[];map_meta=None;map_skipped=[];map_error=None
    if 'map_source' in config:
        try:
            path,map_meta=maps.acquire(config['map_source'],cache,cancelled=cancelled,deadline=deadline,budget=budget)
            refs,map_pin,map_skipped=reference_rows(path)
            if map_pin!=map_meta['body_sha256']:raise ValueError('Map reference bytes changed')
            shutil.copy2(path,output/'osm.xml')
            if file_hash(output/'osm.xml')!=map_pin:raise ValueError('Map snapshot changed while retaining evidence')
        except (web.WebError,ValueError,OSError) as error:
            map_error=str(error);refs=[];map_meta=None
    if file_hash(output/'aerial/source-image.bin')!=rgb['imagery']['image_sha256']:raise ValueError('Original aerial image changed before geometry extraction')
    if pin:
        shutil.copy2(config['protected_plan_coverage']['file'],output/'protected-plan-original.geojson')
        if file_hash(output/'protected-plan-original.geojson')!=pin:raise ValueError('Protected coverage changed while retaining evidence')
    with Image.open(output/'aerial/source-image.bin') as image:rgba=np.asarray(image.convert('RGBA'))
    features,queues,summary=extract(rgba,rgb['imagery']['extent_epsg3857'],config['imagery']['bounds_wgs84'],refs,protected,options,footer=config['imagery'].get('exclude_footer_pixels',32),cancelled=cancelled,deadline=deadline)
    if file_hash(output/'aerial/source-image.bin')!=rgb['imagery']['image_sha256']:raise ValueError('Original aerial image changed during geometry extraction')
    for feature in features+queues:feature['properties'].update(image_sha256=rgb['imagery']['image_sha256'],map_sha256=map_meta['body_sha256'] if map_meta else None,protected_plan_coverage_sha256=pin)
    (output/'geometry-candidates.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},separators=(',',':'))+'\n')
    atomic_json(output/'queue-centrelines.geojson',{'type':'FeatureCollection','features':queues})
    inverse=Transformer.from_crs(3857,4326,always_xy=True)
    atomic_json(output/'protected-coverage.geojson',{'type':'FeatureCollection','features':[] if protected.is_empty else [{'type':'Feature','geometry':mapping(transform(inverse.transform,protected)),'properties':{'role':'supplied_protected_plan_coverage'}}]})
    forward=Transformer.from_crs(4326,3857,always_xy=True);affine=from_bounds(*rgb['imagery']['extent_epsg3857'],rgba.shape[1],rgba.shape[0])
    overlay=np.zeros_like(rgba);overlay[:,:,3]=0
    for kind,colour in COLOURS.items():
        selected=[transform(forward.transform,shape(f['geometry'])) for f in features+queues if f['properties']['kind']==kind]
        selected=[g.buffer(abs(affine.a)*1.5) if 'LineString' in g.geom_type else g for g in selected]
        mask=_mask(selected,rgba.shape[:2],affine);overlay[mask]=[*colour,105]
    Image.alpha_composite(Image.fromarray(rgba),Image.fromarray(overlay)).convert('RGB').save(output/'overlay.png')
    counts=dict(Counter(f['properties']['kind'] for f in features));sources=list(rgb['sources'])
    if map_meta:sources.append({'url':map_meta['source_url'],'body_sha256':map_meta['body_sha256'],'citation_id':'M'+map_meta['body_sha256'][:12],'source_evidence_verified':False,'training_labels_generated':0})
    learned=None
    if 'semantic_model' in config:
        from .aerial_semantic_learning import infer
        spec=config['semantic_model']
        learned=infer(output/'aerial/source-image.bin',rgb['imagery'],spec['file'],output/'learned-semantics',
            model_sha256=spec['sha256'],cancelled=cancelled)
        data=json.loads((output/'learned-semantics/semantic-candidates.geojson').read_text());clipped=[]
        aoi=transform(forward.transform,box(*config['imagery']['bounds_wgs84']))
        for feature in data['features']:
            geom=transform(forward.transform,shape(feature['geometry'])).intersection(aoi).difference(protected)
            if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon','MultiPolygon'):continue
            feature['geometry']=mapping(transform(inverse.transform,geom));feature['properties']['protected_plan_overlap_m2']=geom.intersection(protected).area
            feature['properties']['coverage_status']='outside_supplied_protected_plan_coverage';clipped.append(feature)
        atomic_json(output/'learned-semantic-candidates.geojson',{'type':'FeatureCollection','features':clipped})
        learned['protected_candidate_counts']=dict(Counter(f['properties']['class'] for f in clipped))
        learned['protected_file_sha256']=file_hash(output/'learned-semantic-candidates.geojson')
    report={'version':VERSION,'status':'imagery_gap_geometry_candidates','site_id':config['site_id'],'site':config['site'],
        'request_sha256':digest(config),'extraction_options':options,'learned_semantics':learned,'candidate_counts':counts,'queue_reference_lines':len(queues),**summary,'map_error':map_error,
        'map_parse_gaps':map_skipped[:32],'image_sha256':rgb['imagery']['image_sha256'],'imagery':rgb['imagery'],
        'map_snapshot':map_meta,'protected_plan_coverage_sha256':pin,'protected_coverage_supplied':pin is not None,
        'candidate_file_sha256':file_hash(output/'geometry-candidates.geojson'),'queue_file_sha256':file_hash(output/'queue-centrelines.geojson'),
        'sources':sources,'network_bytes':budget.spent,'geometry_verified':False,'registration_verified':False,
        'model_weights_updated':False,'training_labels_generated':0,'world_blocks_generated':0,'production_eligible':False,
        'limitations':['Pixel colour regions are draft visible-surface outlines, not surveyed building footprints or complete paving.',
            'Map tags seed building/water/queue identity; anonymous hard and blue surfaces remain unclassified.',
            'Queue geometry retains explicit mapped centre lines; no unmapped switchbacks or widths are invented.',
            'Protected supplied plan coverage is excluded; absence of a supplied plan is not proof that no application exists.',
            'Capture dates, positional accuracy, canopy/shadow occlusion and roof displacement limit physical registration.']}
    atomic_json(output/'report.json',report)
    legend=' · '.join('<span style="color:rgb'+str(colour)+'">'+escape(kind.replace('_',' '))+'</span>' for kind,colour in COLOURS.items())
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Imagery gap geometry</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}img{width:100%;max-width:1024px}</style><h1>'+escape(config['site'])+'</h1><p>Draft imagery regions outside supplied protected plan coverage. Map-supported semantics remain unverified.</p><p>'+legend+'</p><img src="overlay.png"><p>'+escape(rgb['imagery'].get('attribution',''))+' · © OpenStreetMap contributors (ODbL-1.0)</p><p><a href="geometry-candidates.geojson">Geometry candidates</a> · <a href="queue-centrelines.geojson">Mapped queue lines</a> · <a href="aerial/index.html">RGB/source metadata</a></p><pre>'+escape(json.dumps(counts,indent=2))+'</pre>',encoding='utf-8')
    if learned is not None:
        path=output/'index.html';page=path.read_text();page=page.replace('</h1>','</h1><p><a href="learned-semantic-candidates.geojson">Learned semantic candidates outside protected coverage</a> · <a href="learned-semantics/index.html">Inspect raw RGB model predictions</a></p>',1);path.write_text(page,encoding='utf-8')
    return report


def resolve_paths(config,base):
    for field,key in [('map_source','snapshot_path'),('protected_plan_coverage','file'),('semantic_model','file')]:
        if key in config.get(field,{}):config[field][key]=str((Path(base)/config[field][key]).resolve())
    return config


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['config','output','cache']:p.add_argument('--'+key,required=True)
    args=p.parse_args(argv);path=Path(args.config).resolve();config=resolve_paths(json.loads(path.read_text()),path.parent)
    print(json.dumps(run(config,args.output,args.cache)))


if __name__=='__main__':main()
