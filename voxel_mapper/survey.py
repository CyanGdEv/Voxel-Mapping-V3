"""Bounded automatic matched, dated EA National LIDAR elevation pairs."""
import datetime
import hashlib
import io
import json
import math
import re
import zipfile

import numpy as np
import rasterio
import requests
from pyproj.transformer import TransformerGroup
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds, Window
from shapely.geometry import box, mapping

from .acquisition import USER_AGENT, ensure_ea_grid

BASE='https://environment.data.gov.uk/tiles/collections/survey'
METADATA='https://environment.data.gov.uk/dataset/2e8d0733-4f43-48b4-9e51-631c25d1b0a9'


def select_pair(data):
    if data.get('count')!=len(data.get('results',[])) or data.get('count',0)>2000:
        raise ValueError('Incomplete or oversized survey catalogue response')
    candidates={}
    for entry in data['results']:
        product=entry['product']['id']
        if product not in ('national_lidar_programme_dtm','national_lidar_programme_dsm') or entry['resolution']['id']!='1':
            continue
        year,tile=entry['year']['id'],entry['tile']['id']
        if not re.fullmatch(r'20\d{2}',year) or int(year)<=2022 or not re.fullmatch(r'[A-Z]{2}\d{4}',tile):
            continue
        url=f'{BASE}/{product}/{year}/1/{tile}'
        if entry['uri']!=url:
            raise ValueError('Unexpected survey download URI')
        candidates.setdefault((year,tile),{})[product.rsplit('_',1)[-1]]=url
    pairs=[(key,value) for key,value in candidates.items() if set(value)=={'dtm','dsm'}]
    if not pairs:
        raise ValueError('No newer matched one-metre National LIDAR pair advertised')
    latest=max(key[0] for key,_ in pairs)
    pairs=[p for p in pairs if p[0][0]==latest]
    if len(pairs)!=1:
        raise ValueError('Multiple survey tiles require a supported mosaic; composite fallback retained')
    return pairs[0]


def crop_pair(archives,bbox,output,year,tile):
    arrays={};profiles={};identities={};files={};coverage={}
    for kind,payload in archives.items():
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries=[e for e in archive.infolist() if e.filename.lower().endswith('.tif')]
            if len(entries)!=1 or entries[0].file_size>150_000_000:
                raise ValueError('One bounded elevation GeoTIFF per product required')
            entry=entries[0]
            match=re.fullmatch(kind.upper()+r'_'+tile+r'_(P_\d+)_(\d{8})_(\d{8})\.tif',entry.filename)
            if not match:
                raise ValueError('Survey raster filename does not identify selected tile and dated product')
            start,end=[datetime.datetime.strptime(v,'%Y%m%d').date() for v in match.groups()[1:]]
            if start.year!=int(year) or end<start:
                raise ValueError('Survey filename dates conflict with advertised year')
            identities[kind]=match.groups()
            files[kind]=entry.filename
            with MemoryFile(archive.read(entry)) as memory, memory.open() as dataset:
                if dataset.crs is None or dataset.crs.to_epsg()!=27700 or dataset.count!=1 or dataset.res!=(1,1):
                    raise ValueError('Native one-metre British National Grid elevation required')
                if not box(*dataset.bounds).covers(box(*bbox)):
                    raise ValueError('Dated survey does not cover requested bounds')
                window=from_bounds(*bbox,dataset.transform)
                left,top=math.floor(window.col_off),math.floor(window.row_off)
                right,bottom=math.ceil(window.col_off+window.width),math.ceil(window.row_off+window.height)
                window=Window(left,top,right-left,bottom-top)
                if window.width*window.height>8_000_000:
                    raise ValueError('Survey crop exceeds native pixel budget')
                values=dataset.read(1,window=window,masked=True)
                finite=np.isfinite(values.filled(np.nan))
                coverage[kind]=float(finite.sum()/values.size)
                if (kind=='dtm' and coverage[kind]<.99) or finite.sum()<4:
                    raise ValueError('Survey lacks required finite terrain/surface coverage')
                arrays[kind]=values
                profiles[kind]={'driver':'GTiff','count':1,'dtype':'float32','crs':dataset.crs,
                    'transform':dataset.window_transform(window),'width':values.shape[1],
                    'height':values.shape[0],'nodata':-9999,'compress':'deflate'}
    if identities['dtm']!=identities['dsm'] or profiles['dtm']!=profiles['dsm']:
        raise ValueError('Terrain/surface survey identity, date or raster grid mismatch')
    for kind in ('dtm','dsm'):
        with rasterio.open(output/f'ea-national-{kind}.tif','w',**profiles[kind]) as dataset:
            dataset.write(arrays[kind].filled(-9999).astype('float32'),1)
    return {'survey_id':identities['dtm'][0],'survey_start':identities['dtm'][1],
            'survey_end':identities['dtm'][2],'archive_files':files,'finite_coverage_fraction':coverage,
            'terrain_coverage_threshold':.99,'surface_gaps':'Preserved as nodata; building/bridge coverage gates apply; no interpolation'}


def download_latest_pair(bounds,output):
    headers={'User-Agent':USER_AGENT}
    response=requests.post(BASE+'/search',json=mapping(box(*bounds)),
                           headers={**headers,'Content-Type':'application/geo+json'},timeout=(10,35))
    response.raise_for_status()
    if len(response.content)>2_000_000:
        raise ValueError('Survey catalogue response exceeds budget')
    data=response.json()
    (output/'national-survey-catalogue.json').write_text(json.dumps(data,indent=2))
    (year,tile),urls=select_pair(data)
    grid=ensure_ea_grid(output)
    group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
        raise ValueError('Best metre-scale datum transformation required for dated survey crops')
    projector=group.transformers[0]
    bbox=projector.transform_bounds(*bounds,densify_pts=21)
    archives={}
    for kind,url in urls.items():
        with requests.get(url,headers=headers,timeout=(10,120),stream=True) as download:
            download.raise_for_status()
            payload=bytearray()
            for chunk in download.iter_content(1_000_000):
                payload.extend(chunk)
                if len(payload)>100_000_000:
                    raise ValueError('Survey archive download exceeds 100 MB budget')
            archives[kind]=bytes(payload)
    try:
        survey=crop_pair(archives,bbox,output,year,tile)
    except zipfile.BadZipFile as error:
        raise ValueError('Survey download is not a valid ZIP archive') from error
    return describe_pair(archives,survey,output,year,urls,{'best_available':True,'accuracy_m':projector.accuracy,'grid':grid})


def describe_pair(archives,survey,output,year,urls,coordinate_transform):
    """Retain reusable descriptors after validated acquisition, before OSM runs."""
    sources={};configs={}
    for kind in ('dtm','dsm'):
        sources[kind]={'id':'ea-'+kind,'url':urls[kind],'metadata_url':METADATA,'license':'OGL-UK-3.0',
            'attribution':'Contains Environment Agency information © Environment Agency and/or database right',
            'resolution_m':1,'vertical_datum':'ODN','product':'National LIDAR '+('DTM' if kind=='dtm' else 'last-return DSM'),
            'product_period':year,'survey':survey,'archive_sha256':hashlib.sha256(archives[kind]).hexdigest(),
            'coordinate_transform':coordinate_transform}
        configs[kind]={'path':str((output/f'ea-national-{kind}.tif').resolve()),'source_id':'ea-'+kind,'units':'m','vertical_datum':'ODN'}
    sources['dtm']['paired_surface']={'config':configs['dsm'],'source':sources['dsm']}
    (output/'national-survey-pair.json').write_text(json.dumps({'terrain':configs['dtm'],'source':sources['dtm']},indent=2))
    return configs['dtm'],sources['dtm']
