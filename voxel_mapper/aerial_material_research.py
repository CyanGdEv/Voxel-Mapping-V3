"""Georeferenced aerial RGB observations and tentative block-palette candidates."""
import argparse
from concurrent.futures import CancelledError
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlencode

import numpy as np
from PIL import Image
from pyproj import Transformer
import requests

from . import web_evidence as web, research_sources
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash
from .paving_palette import PALETTES

VERSION='aerial-material-research-v1'
ESRI='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'
BING='https://dev.virtualearth.net/REST/v1/Imagery/Map/Aerial'


def validate(config):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{
        'version','site','site_id','provider','bounds_wgs84','width','height','grid','exclude_footer_pixels','offline'}:
        raise ValueError('Versioned aerial RGB research configuration required')
    from .web_focus import profile
    profile({'site':config.get('site')})
    if not isinstance(config.get('site_id'),str) or not 1<=len(config['site_id'])<=80:raise ValueError('Public site identity required')
    if config.get('provider') not in ('esri_world_imagery','bing_aerial'):raise ValueError('Known aerial imagery provider required')
    b=config.get('bounds_wgs84')
    if (not isinstance(b,list) or len(b)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in b)
            or not -180<=b[0]<b[2]<=180 or not -85<b[1]<b[3]<85
            or b[2]-b[0]>.02 or b[3]-b[1]>.02):raise ValueError('Small finite aerial WGS84 bounds required')
    for key,default,low,high in [('width',1024,128,2048),('height',1024,128,2048),('grid',16,4,32),('exclude_footer_pixels',32,0,64)]:
        value=config.get(key,default)
        if type(value) is not int or not low<=value<=high:raise ValueError('Bounded aerial dimensions/grid/footer required')
    if config.get('width',1024)*config.get('height',1024)>4000000:raise ValueError('Aerial pixel budget exceeded')
    if type(config.get('offline',False)) is not bool:raise ValueError('Explicit aerial offline mode required')


def _check(cancelled,deadline):
    if cancelled():raise CancelledError('Aerial RGB research cancelled')
    if time.monotonic()>=deadline:raise web.WebError('deadline','Aerial research deadline reached')


def _extent(value):
    if not isinstance(value,list) or len(value)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value) or value[0]>=value[2] or value[1]>=value[3]:
        raise ValueError('Finite nonempty imagery extent required')
    return value


def _bing_get(params,key,*,cancelled,deadline,budget,session=None):
    # Never pass a credential-bearing request through the public web receipt cache.
    _check(cancelled,deadline);web._public_dns(BING,web.socket.getaddrinfo)
    own=session is None;client=session or requests.Session()
    try:
        client.cookies.clear()
        try:
            response=client.get(BING,params={**params,'key':key},auth=web._NoOriginAuth(),stream=True,
                allow_redirects=False,headers={'User-Agent':'VoxelMapperV3 aerial RGB research'},timeout=(5,15))
            try:
                if response.status_code!=200:raise web.WebError('bing_http_status','Bing imagery request did not return 200',http_status=response.status_code)
                data=bytearray()
                for chunk in response.iter_content(65536):
                    _check(cancelled,deadline);budget.take(len(chunk));data.extend(chunk)
                    if len(data)>16000000:raise ValueError('Bing response byte budget exceeded')
                return bytes(data)
            finally:response.close()
        except requests.RequestException as error:
            # Request exception strings can contain the URL/key; do not retain them.
            raise web.WebError('bing_transport_unavailable','Bing imagery transport failed') from None
    finally:
        if own:client.close()


def acquire(config,cache,*,cancelled,deadline,budget):
    b=config['bounds_wgs84'];width=config.get('width',1024);height=config.get('height',1024)
    if config['provider']=='esri_world_imagery':
        query={'bbox':','.join(map(str,b)),'bboxSR':4326,'imageSR':3857,'size':str(width)+','+str(height),'format':'png','f':'json'}
        endpoint=ESRI+'/export?'+urlencode(query);approved=['server.arcgisonline.com']
        meta=web.fetch(endpoint,cache,approved,offline=config.get('offline',False),refresh=False,
            budget=budget,cancelled=cancelled,deadline=deadline)
        source=meta['source'];data=research_sources.bounded_json(web._body_path(Path(cache),source).read_bytes())
        if 'error' in data:raise ValueError('Aerial imagery export returned an error')
        ext=data['extent'];wkid=ext.get('spatialReference',{}).get('latestWkid',ext.get('spatialReference',{}).get('wkid'))
        if wkid not in (3857,102100,102113):raise ValueError('Expected Web Mercator imagery extent')
        extent=_extent([ext[k] for k in ['xmin','ymin','xmax','ymax']])
        target=web.url(data['href'],approved)
        image=web.fetch(target,cache,approved,offline=config.get('offline',False),refresh=False,
            budget=budget,cancelled=cancelled,deadline=deadline)
        if image['source']['format']!='image':raise ValueError('Provider export is not a verified RGB image')
        # Point metadata can report capture date/resolution/accuracy; do not
        # apply one point's date to a whole multi-source imagery mosaic.
        provenance=[];metadata_error=None;extra_sources=[]
        point_url=ESRI+'/identify?'+urlencode({'geometry':str((b[0]+b[2])/2)+','+str((b[1]+b[3])/2),
            'geometryType':'esriGeometryPoint','sr':4326,'tolerance':1,'mapExtent':','.join(map(str,b)),
            'imageDisplay':str(width)+','+str(height)+',96','returnGeometry':'false','layers':'all','f':'json'})
        try:
            point=web.fetch(point_url,cache,approved,offline=config.get('offline',False),refresh=False,
                budget=budget,cancelled=cancelled,deadline=deadline)['source']
            original=research_sources.bounded_json(web._body_path(Path(cache),point).read_bytes());seen=set()
            for item in original.get('results',[])[:32]:
                attrs=item.get('attributes',{});record={k:attrs[k] for k in ['DATE (YYYYMMDD)','SRC_DATE2','RESOLUTION (M)','ACCURACY (M)','SOURCE','SOURCE_INFO','DESCRIPTION'] if k in attrs}
                pin=digest(record)
                if record and pin not in seen:provenance.append(record);seen.add(pin)
            extra_sources.append(point)
        except (web.WebError,ValueError) as error:metadata_error=str(error)
        return web._body_path(Path(cache),image['source']),{
            'provider':config['provider'],'image_sha256':image['source']['body_sha256'],'extent_epsg3857':extent,
            'width':data['width'],'height':data['height'],'metadata_sha256':source['body_sha256'],
            'metadata_url':endpoint,'image_url':target,'capture_date':None,'capture_date_status':'not_supplied_by_export',
            'attribution':'Esri World Imagery and its imagery providers','attribution_url':ESRI,
            'point_source_metadata':provenance,'point_metadata_url':point_url,'point_metadata_error':metadata_error,
            'point_metadata_applies_to_whole_image':False,'registration_verified':False,'sources':[source,image['source'],*extra_sources]}
    params={'mapArea':','.join(map(str,[b[1],b[0],b[3],b[2]])),'mapSize':str(width)+','+str(height),'format':'png'}
    folder=Path(cache)/'bing-aerial'/digest(params);receipt=folder/'receipt.json';path=folder/'image.png';metadata=folder/'metadata.json'
    if receipt.exists():
        record=json.loads(receipt.read_text())
        if (digest({k:v for k,v in record.items() if k!='artifact_sha256'})!=record.get('artifact_sha256') or
                file_hash(path)!=record['image_sha256'] or file_hash(metadata)!=record['metadata_sha256']):raise ValueError('Retained Bing imagery changed')
        original=research_sources.bounded_json(metadata.read_bytes())['resourceSets'][0]['resources'][0]
        south,west,north,east=original['bbox'];project=Transformer.from_crs(4326,3857,always_xy=True)
        x0,y0=project.transform(west,south);x1,y1=project.transform(east,north)
        if (record['extent_epsg3857']!=_extent([x0,y0,x1,y1]) or record['width']!=original['imageWidth'] or record['height']!=original['imageHeight']):
            raise ValueError('Bing cached georeferencing differs from original metadata')
        return path,record
    if config.get('offline'):raise web.WebError('offline_cache_miss','No retained Bing imagery for this area')
    key=os.environ.get('BING_MAPS_KEY','')
    if not key:return None,{'status':'awaiting_bing_maps_key','provider':'bing_aerial','sources':[]}
    raw=_bing_get({**params,'mapMetadata':1},key,cancelled=cancelled,deadline=deadline,budget=budget)
    if key.encode() in raw:raise ValueError('Credential-bearing metadata response not retained')
    data=research_sources.bounded_json(raw)
    if data.get('statusCode')!=200 or data.get('authenticationResultCode')!='ValidCredentials':raise ValueError('Bing imagery metadata was not authorized')
    item=data['resourceSets'][0]['resources'][0];south,west,north,east=item['bbox']
    _extent([west,south,east,north]);project=Transformer.from_crs(4326,3857,always_xy=True)
    x0,y0=project.transform(west,south);x1,y1=project.transform(east,north)
    extent=_extent([x0,y0,x1,y1])
    image=_bing_get(params,key,cancelled=cancelled,deadline=deadline,budget=budget)
    if web._extract(image,'image/png',BING)['format']!='image':raise ValueError('Bing did not return verified image bytes')
    folder.mkdir(parents=True,exist_ok=True);metadata.write_bytes(raw);path.write_bytes(image)
    record={'provider':'bing_aerial','image_sha256':file_hash(path),'metadata_sha256':file_hash(metadata),
        'metadata_url':BING,'image_url':BING,'extent_epsg3857':extent,'width':item['imageWidth'],'height':item['imageHeight'],
        'capture_date':None,'capture_date_status':'not_supplied_by_static_map_metadata',
        'attribution':data.get('copyright','Microsoft and imagery providers'),'attribution_url':'https://www.bing.com/maps',
        'registration_verified':False,'sources':[]}
    record['artifact_sha256']=digest(record)
    atomic_json(receipt,record);return path,record


def _lab(rgb):
    rgb=np.asarray(rgb,dtype=float)/255
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=linear@np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]).T
    xyz=xyz/np.array([.95047,1.,1.08883]);f=np.where(xyz>.008856, np.cbrt(xyz),7.787*xyz+16/116)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)


def _palette_candidates(rgb):
    choices=[]
    for name,p in PALETTES.items():
        colours=np.array([[int(c[i:i+2],16) for i in (1,3,5)] for c in p['colours']])
        weights=np.asarray(p.get('weights',[1]*len(colours)),float);colour=np.average(colours,axis=0,weights=weights)
        distance=float(np.linalg.norm(_lab(rgb)-_lab(colour)))
        choices.append({'palette':name,'blocks':p['blocks'],'delta_e76':round(distance,3)})
    return sorted(choices,key=lambda r:(r['delta_e76'],r['palette']))[:3]


def sample(path,receipt,grid=16,footer=32,*,cancelled=lambda:False,deadline=None):
    deadline=deadline or time.monotonic()+60
    if file_hash(path)!=receipt['image_sha256']:raise ValueError('Aerial source changed before sampling')
    with Image.open(path) as image:
        if image.width*image.height>4000000 or getattr(image,'n_frames',1)!=1:raise ValueError('Bounded still RGB imagery required')
        if image.size!=(receipt['width'],receipt['height']):raise ValueError('Image dimensions differ from export metadata')
        rgba=np.asarray(image.convert('RGBA'));rgb=rgba[:,:,:3]
    height,width=rgb.shape[:2];extent=_extent(receipt['extent_epsg3857']);x0,y0,x1,y1=extent
    transform=Transformer.from_crs(3857,4326,always_xy=True);rows=[]
    for gy in range(grid):
        for gx in range(grid):
            _check(cancelled,deadline)
            left=gx*width//grid;right=(gx+1)*width//grid;top=gy*height//grid;bottom=(gy+1)*height//grid
            keep=rgba[top:bottom,left:right,3]==255
            if bottom>height-footer:keep[max(0,height-footer-top):,:]=False
            pixels=rgb[top:bottom,left:right][keep]
            cell={'id':f'rgb-{gx}-{gy}','pixel_box':[left,top,right,bottom],'image_sha256':receipt['image_sha256'],
                'material_verified':False,'training_eligible':False}
            if len(pixels)<16:rows.append({**cell,'status':'insufficient_opaque_pixels'});continue
            # Deterministic bounded samples preserve colour observations, not guessed labels.
            pixels=pixels[::max(1,math.ceil(len(pixels)/4096))].astype(float);median=np.median(pixels,axis=0)
            luminance=pixels@np.array([.2126,.7152,.0722]);shadow=float(np.mean(luminance<45))
            green=float(np.mean((pixels[:,1]>pixels[:,0]*1.10)&(pixels[:,1]>pixels[:,2]*1.08)))
            blue=float(np.mean((pixels[:,2]>pixels[:,0]*1.12)&(pixels[:,2]>pixels[:,1]*1.08)))
            warm=float(np.mean((pixels[:,0]>pixels[:,1]*1.12)&(pixels[:,1]>pixels[:,2]*1.02)))
            cue=('shadow_or_dark_surface' if shadow>.35 else 'vegetation_colour' if green>.45 else
                'blue_surface_or_water' if blue>.45 else 'warm_brown_or_red_surface' if warm>.45 else 'neutral_or_mixed_surface')
            west=x0+left/width*(x1-x0);east=x0+right/width*(x1-x0);north=y1-top/height*(y1-y0);south=y1-bottom/height*(y1-y0)
            ring=[list(transform.transform(x,y)) for x,y in [(west,south),(east,south),(east,north),(west,north),(west,south)]]
            candidates=_palette_candidates(median)
            rows.append({**cell,'status':'rgb_observation_only','sampled_pixels':len(pixels),'median_rgb':median.round(2).tolist(),
                'rgb_iqr':(np.percentile(pixels,75,axis=0)-np.percentile(pixels,25,axis=0)).round(2).tolist(),
                'shadow_fraction':round(shadow,4),'green_fraction':round(green,4),'blue_fraction':round(blue,4),
                'colour_cue':cue,'block_palette_candidates':candidates,
                'palette_use_withheld':cue in ('shadow_or_dark_surface','vegetation_colour','blue_surface_or_water'),
                'geometry':{'type':'Polygon','coordinates':[ring]},'geometry_role':'imagery_sample_cell_not_object_boundary'})
    if file_hash(path)!=receipt['image_sha256']:raise ValueError('Aerial source changed during sampling')
    return rows


def run(config,output,cache,*,cancelled=lambda:False,progress=lambda v:None,parent_budget=None,run_deadline=None,fetch=None):
    validate(config);output=Path(output)
    if output.exists():raise ValueError('Fresh aerial RGB output required')
    output.mkdir(parents=True);atomic_json(output/'config.json',config)
    deadline=min(time.monotonic()+180,run_deadline or float('inf'));budget=web.Budget(32000000,parent=parent_budget)
    b=config['bounds_wgs84'];viewer='https://www.bing.com/maps?'+urlencode({'cp':str((b[1]+b[3])/2)+'~'+str((b[0]+b[2])/2),'lvl':19,'style':'a'})
    progress({'progress':.05,'message':'Reading aerial RGB imagery and its map extent'})
    path,receipt=(fetch or acquire)(config,cache,cancelled=cancelled,deadline=deadline,budget=budget)
    rows=[];sources=[]
    if path is not None:
        rows=sample(path,receipt,config.get('grid',16),config.get('exclude_footer_pixels',32),cancelled=cancelled,deadline=deadline)
        target=output/'source-image.bin';shutil.copy2(path,target)
        if file_hash(target)!=receipt['image_sha256']:raise ValueError('Original imagery changed while retaining evidence')
        with Image.open(path) as image:image.convert('RGB').save(output/'rgb-preview.png')
        sources=[{k:r[k] for k in ['url','body_sha256','citation_id','source_evidence_verified','training_labels_generated']} for r in receipt['sources']]
        if config['provider']=='bing_aerial':sources=[{'url':BING,'body_sha256':receipt['image_sha256'],'citation_id':'I'+receipt['image_sha256'][:12],'source_evidence_verified':False,'training_labels_generated':0}]
    cells=[];table=[]
    if path is not None:
        for row in rows:
            if 'median_rgb' not in row:continue
            left,top,right,bottom=row['pixel_box'];colour=','.join(str(round(v)) for v in row['median_rgb'])
            title=escape(row['id']+' '+row['colour_cue'].replace('_',' ')+' RGB '+str(row['median_rgb']))
            cells.append(f'<rect x="{left}" y="{top}" width="{right-left}" height="{bottom-top}" fill="rgb({colour})"><title>{title}</title></rect>')
            ranked=', '.join(p['palette'] for p in row['block_palette_candidates'])
            table.append('<tr><td>'+escape(row['id'])+'</td><td>'+escape(str(row['median_rgb']))+'</td><td>'+escape(row['colour_cue'].replace('_',' '))+'</td><td>'+escape(ranked)+'</td></tr>')
        visual='<div class="images"><figure><img src="rgb-preview.png"><figcaption>Provider RGB imagery</figcaption></figure><figure><svg viewBox="0 0 '+str(receipt['width'])+' '+str(receipt['height'])+'">'+''.join(cells)+'</svg><figcaption>Median RGB per cell; not a material map</figcaption></figure></div>'
    else:visual='<p>'+escape(receipt['status'].replace('_',' '))+'</p>'
    page='<!doctype html><meta charset="utf-8"><title>Aerial RGB observations</title><style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:0 16px;color:#253341}.images{display:flex;flex-wrap:wrap}figure{margin:12px;width:46%}img,svg{width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccd3da;padding:6px}</style><h1>'+escape(config['site'])+'</h1><p>Aerial colour observations and tentative palette matches. Materials and physical alignment remain unverified.</p>'+visual+'<p>'+escape(receipt.get('attribution','Bing Maps'))+' · <a href="'+escape(viewer,quote=True)+'">View area on Bing Maps</a></p><table><thead><tr><th>Cell</th><th>Median RGB</th><th>Colour clue</th><th>Palette candidates</th></tr></thead><tbody>'+''.join(table)+'</tbody></table>'
    (output/'index.html').write_text(page,encoding='utf-8')
    atomic_json(output/'sample-cells.geojson',{'type':'FeatureCollection','features':[
        {'type':'Feature','id':r['id'],'geometry':r['geometry'],'properties':{k:v for k,v in r.items() if k!='geometry'}} for r in rows if 'geometry' in r]})
    atomic_json(output/'imagery-receipt.json',receipt)
    with (output/'material-candidates.jsonl').open('w') as stream:
        for row in rows:stream.write(json.dumps(row,sort_keys=True)+'\n')
    report={'version':VERSION,'status':'aerial_rgb_sampled' if path is not None else receipt['status'],
        'provider':config['provider'],'site_id':config['site_id'],'site':config['site'],'bing_viewer_url':viewer,
        'imagery':{k:v for k,v in receipt.items() if k!='sources'},'sample_cells':len(rows),
        'colour_cue_counts':{cue:sum(r.get('colour_cue','insufficient_pixels')==cue for r in rows) for cue in sorted({r.get('colour_cue','insufficient_pixels') for r in rows})},
        'candidate_file':'material-candidates.jsonl','candidate_file_sha256':file_hash(output/'material-candidates.jsonl'),
        'sources':sources,'network_bytes':budget.spent,'model_weights_updated':False,'training_labels_generated':0,
        'material_assignments_accepted':0,'registration_verified':False,'world_blocks_generated':0,'production_eligible':False,
        'limitations':['RGB/Lab palette distances are colour-similarity candidates, not verified materials or calibrated probabilities.',
            'Shadows, vegetation, water, roofs, lighting, capture date and resampling affect colour; ambiguous candidates are withheld.',
            'Provider extent georeferences sample cells, not individual paths/buildings; physical registration remains unverified.',
            'Original imagery and provider attribution are retained; these observations do not bypass reviewed orthophoto material acceptance.']}
    atomic_json(output/'report.json',report);return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['config','output','cache']:p.add_argument('--'+name,required=True)
    args=p.parse_args(argv);print(json.dumps(run(json.loads(Path(args.config).read_text()),args.output,args.cache)))


if __name__=='__main__':main()
