"""Small matched dated EA tile mosaics with native gaps and source identities."""
import io
from datetime import datetime
import json
import math
from pathlib import Path
import re
import zipfile

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.windows import Window
import requests
from pyproj.transformer import TransformerGroup

from .acquisition import ensure_ea_grid,USER_AGENT
from .survey import BASE
from .generation_cycles import atomic_json,file_hash


def select_tiles(catalogue):
    if catalogue.get('count')!=len(catalogue.get('results',[])) or catalogue.get('count',0)>2000:
        raise ValueError('Complete bounded survey catalogue required')
    tiles={}
    for e in catalogue['results']:
        product=e['product']['id']
        if product not in ('national_lidar_programme_dtm','national_lidar_programme_dsm') or e['resolution']['id']!='1':continue
        tile=e['tile']['id'];year=e['year']['id'];kind=product.rsplit('_',1)[-1]
        if not re.fullmatch('[A-Z]{2}[0-9]{4}',tile) or not re.fullmatch('20[0-9]{2}',year) or e['uri']!=f'{BASE}/{product}/{year}/1/{tile}':raise ValueError('Known dated survey tile URI required')
        group=tiles.setdefault(tile,{}).setdefault(year,{})
        if kind in group:raise ValueError('Duplicate survey product selection')
        group[kind]=e['uri']
    if not 1<=len(tiles)<=4:raise ValueError('One to four survey tiles required')
    common=set.intersection(*[{year for year,products in years.items() if set(products)=={'dtm','dsm'}} for years in tiles.values()])
    if not common:raise ValueError('No common year of matched terrain and surface tiles')
    year=max(common)
    return [(tile,year,tiles[tile][year]) for tile in sorted(tiles)]


def place(target,transform,values,source_transform):
    """Copy only finite native observations. Conflicting overlapping tiles fail."""
    if any(t.a!=1 or t.e!=-1 or t.b or t.d for t in (transform,source_transform)):
        raise ValueError('Native north-up one-metre survey grid required')
    left=source_transform.c-transform.c;top=transform.f-source_transform.f
    if abs(left-round(left))>1e-6 or abs(top-round(top))>1e-6:raise ValueError('Aligned native metre origins required')
    left,top=round(left),round(top);x0=max(0,left);y0=max(0,top);x1=min(target.shape[1],left+values.shape[1]);y1=min(target.shape[0],top+values.shape[0])
    if x1<=x0 or y1<=y0:return
    view=target[y0:y1,x0:x1];incoming=values[y0-top:y1-top,x0-left:x1-left];both=np.isfinite(view)&np.isfinite(incoming)
    if np.any(np.abs(view[both]-incoming[both])>1e-4):raise ValueError('Overlapping survey observations disagree')
    mask=np.isfinite(incoming);view[mask]=incoming[mask]


def acquire(bounds,catalogue_file,output):
    out=Path(output)
    if out.exists():raise ValueError('Fresh matched mosaic directory required')
    out.mkdir(parents=True);catalogue=json.loads(Path(catalogue_file).read_text());selected=select_tiles(catalogue)
    grid=ensure_ea_grid(out);group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Best metre-scale horizontal transform required')
    bbox=group.transformers[0].transform_bounds(*bounds,densify_pts=21);left,bottom=math.floor(bbox[0]),math.floor(bbox[1]);right,top=math.ceil(bbox[2]),math.ceil(bbox[3]);shape=(top-bottom,right-left)
    if shape[0]*shape[1]>8000000:raise ValueError('Mosaic native pixel budget exceeded')
    transform=from_origin(left,top,1,1);arrays={k:np.full(shape,np.nan,np.float32) for k in ('dtm','dsm')};surveys=[]
    for tile,year,urls in selected:
        identities={};receipts={}
        for kind,url in urls.items():
            raw=bytearray()
            with requests.get(url,headers={'User-Agent':USER_AGENT},stream=True,timeout=(10,120)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(1_000_000):
                    raw.extend(chunk)
                    if len(raw)>100_000_000:raise ValueError('Survey tile archive exceeds 100 MB budget')
            import hashlib
            receipt={'url':url,'archive_bytes':len(raw),'archive_sha256':hashlib.sha256(raw).hexdigest()}
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries=[e for e in archive.infolist() if e.filename.lower().endswith('.tif')]
                if len(entries)!=1 or entries[0].file_size>150_000_000:raise ValueError('One bounded survey GeoTIFF per tile product required')
                entry=entries[0];match=re.fullmatch(kind.upper()+'_'+tile+r'_(P_[0-9]+)_([0-9]{8})_([0-9]{8})\.tif',entry.filename)
                if not match or not match[2].startswith(year) or match[3]<match[2]:raise ValueError('Dated tile filename does not match catalogue')
                datetime.strptime(match[2],'%Y%m%d');datetime.strptime(match[3],'%Y%m%d')
                identities[kind]=match.groups();receipt['filename']=entry.filename
                with MemoryFile(archive.read(entry)) as memory,memory.open() as ds:
                    if ds.crs.to_epsg()!=27700 or ds.res!=(1.,1.) or ds.count!=1:raise ValueError('Native BNG metre survey required')
                    x0=max(left,ds.bounds.left);x1=min(right,ds.bounds.right);y0=max(bottom,ds.bounds.bottom);y1=min(top,ds.bounds.top)
                    if x1>x0 and y1>y0:
                        window=Window(round(x0-ds.transform.c),round(ds.transform.f-y1),round(x1-x0),round(y1-y0));values=ds.read(1,window=window,masked=True).filled(np.nan);place(arrays[kind],transform,values,ds.window_transform(window))
            receipts[kind]=receipt
        if identities['dtm']!=identities['dsm']:raise ValueError('Terrain/surface survey identity or dates differ within a tile')
        identity,start,end=identities['dtm'];surveys.append({'tile':tile,'survey_id':identity,'survey_start':start,'survey_end':end,'products':receipts})
    profile={'driver':'GTiff','count':1,'dtype':'float32','crs':'EPSG:27700','transform':transform,'width':shape[1],'height':shape[0],'nodata':-9999.,'compress':'deflate'}
    for kind,array in arrays.items():
        if not np.isfinite(array).any():raise ValueError('No valid observations in selected survey mosaic')
        with rasterio.open(out/('ea-national-'+kind+'.tif'),'w',**profile) as ds:ds.write(np.where(np.isfinite(array),array,-9999).astype(np.float32),1)
    source={'id':'ea-matched-tile-mosaic','version':'matched-native-survey-mosaic-v1','license':'OGL-UK-3.0',
        'attribution':'Contains Environment Agency information © Environment Agency and/or database right','vertical_datum':'ODN',
        'survey':{'common_catalogue_year':selected[0][1],'tiles':surveys,'same_survey_across_tiles':len({(s['survey_id'],s['survey_start'],s['survey_end']) for s in surveys})==1},
        'coordinate_transform':{'best_available':True,'accuracy_m':group.transformers[0].accuracy,'grid':grid},
        'finite_coverage_fraction':{kind:float(np.isfinite(array).mean()) for kind,array in arrays.items()},
        'gaps':'Missing observations stay nodata; full output-grid extent does not establish valid terrain coverage',
        'catalogue_sha256':file_hash(catalogue_file)}
    atomic_json(out/'acquisition.json',{'status':'downloaded','bounds_wgs84':bounds,'source':source});return source
