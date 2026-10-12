"""Automatic, bounded acquisition of measured EA multibeam bed elevations."""
import hashlib
import datetime
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
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, shape

from .acquisition import USER_AGENT, ensure_ea_grid

METADATA = 'https://www.data.gov.uk/dataset/52b3a813-69c6-4b6f-8684-fd0bdc4aa71b/multibeam-bathymetry'
INDEX = 'https://environment.data.gov.uk/api/file/download?fileDataSetId=26cade53-0482-4656-a2de-db68cdaa154e&fileName=Multibeam_Bathymetry.geojson.zip'
BASE = 'https://environment.data.gov.uk/tiles/collections/survey'


def download(url, limit):
    with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(10,60), stream=True) as response:
        response.raise_for_status()
        payload = bytearray()
        for chunk in response.iter_content(1_000_000):
            payload.extend(chunk)
            if len(payload) > limit:
                raise ValueError('Bathymetry download exceeds byte budget')
    return bytes(payload)


def candidates(payload, bounds):
    """Index tile rectangles are discovery only, never proof of wet coverage."""
    found, count = {}, 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries)>100 or sum(e.file_size for e in entries)>30_000_000:
            raise ValueError('Bathymetry index exceeds resource budget')
        for entry in entries:
            if not entry.filename.endswith('.geojson'):
                continue
            data = json.loads(archive.read(entry))
            if data.get('crs',{}).get('properties',{}).get('name') != 'urn:ogc:def:crs:EPSG::27700':
                raise ValueError('Bathymetry index requires explicit EPSG:27700')
            for feature in data['features']:
                count += 1
                if count>100_000:
                    raise ValueError('Bathymetry catalogue feature budget exceeded')
                geometry = shape(feature['geometry'])
                if not geometry.is_valid or geometry.is_empty:
                    raise ValueError('Invalid bathymetry index geometry')
                if not geometry.intersects(box(*bounds)) or geometry.intersection(box(*bounds)).area<=0:
                    continue
                p = feature['properties']
                year,tile = str(p['year']),p['os_ref_5k']
                if not re.fullmatch(r'20\d{2}',year) or not re.fullmatch(r'[A-Z]{2}\d{4}',tile) or p['resolution']!=.5:
                    raise ValueError('Unsupported bathymetry tile identity or resolution')
                product = {'RIVERINE MULTIBEAM':'bathymetry_riverine_multibeam',
                           'COASTAL MULTIBEAM':'bathymetry_coastal_multibeam'}.get(p['srvy_type'])
                if not product:
                    raise ValueError('Unsupported bathymetry survey type')
                found.setdefault((year,product,tile),[]).append(p['filename'])
    return [{'year':k[0],'product':k[1],'tile':k[2], 'files':sorted(set(v)),
             'url':f'{BASE}/{k[1]}/{k[0]}/0.5/{k[2]}'}
            for k,v in sorted(found.items(),reverse=True)]


def crop_archive(payload, selection, bounds, output, max_pixels=8_000_000):
    left,bottom,right,top = (math.floor(bounds[0]*2)/2,math.floor(bounds[1]*2)/2,
                           math.ceil(bounds[2]*2)/2,math.ceil(bounds[3]*2)/2)
    width,height = round((right-left)*2),round((top-bottom)*2)
    if width<=0 or height<=0 or width*height>max_pixels:
        raise ValueError('Bathymetry crop exceeds pixel budget')
    transform = rasterio.transform.from_origin(left,top,.5,.5)
    result = np.full((height,width),-9999,dtype='float32')
    used = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries)>500 or sum(e.file_size for e in entries)>250_000_000:
            raise ValueError('Bathymetry archive expansion exceeds budget')
        if len({e.filename for e in entries})!=len(entries):
            raise ValueError('Ambiguous duplicate archive filenames')
        selected = [e for e in entries if e.filename in selection['files']]
        if {e.filename for e in selected}!=set(selection['files']):
            raise ValueError('Advertised bathymetry rasters missing from archive')
        # Within a selected year retain the newest finite measurement on overlap.
        for entry in sorted(selected,key=lambda e:e.filename.split('_')[-1]):
            match = re.fullmatch(r'[a-z]{2}\d{4}_(\d{8})mb\.asc',entry.filename)
            if not match or not match[1].startswith(selection['year']) or entry.file_size>100_000_000:
                raise ValueError('Invalid bathymetry raster identity')
            datetime.datetime.strptime(match[1],'%Y%m%d')
            with MemoryFile(archive.read(entry)) as memory, memory.open() as dataset:
                if dataset.driver!='AAIGrid' or dataset.count!=1 or dataset.res!=(.5,.5):
                    raise ValueError('Expected native half-metre ESRI ASCII bed raster')
                if dataset.crs and dataset.crs.to_epsg()!=27700:
                    raise ValueError('Bathymetry horizontal CRS conflicts with catalogue')
                overlap = box(*dataset.bounds).intersection(box(left,bottom,right,top))
                if overlap.is_empty or overlap.area<=0:
                    continue
                win = from_bounds(*overlap.bounds,dataset.transform)
                if any(abs(v-round(v))>1e-6 for v in (win.col_off,win.row_off,win.width,win.height)):
                    raise ValueError('Bathymetry grid is not aligned to half-metre crop')
                win=Window(*[round(v) for v in (win.col_off,win.row_off,win.width,win.height)])
                values=dataset.read(1,window=win,masked=True).astype('float32').filled(np.nan)
                dest=from_bounds(*overlap.bounds,transform)
                row,col=round(dest.row_off),round(dest.col_off)
                target=result[row:row+values.shape[0],col:col+values.shape[1]]
                finite=np.isfinite(values)
                if finite.any():
                    target[finite]=values[finite];used.append(entry.filename)
    measured=int(np.count_nonzero(result!=-9999))
    if not measured:
        raise ValueError('No finite measured bed samples in requested bounds')
    path=output/'ea-bathymetry.tif'
    with rasterio.open(path,'w',driver='GTiff',width=width,height=height,count=1,dtype='float32',
                       crs='EPSG:27700',transform=transform,nodata=-9999,compress='deflate') as dataset:
        dataset.write(result,1)
    return path,{'finite_pixels':measured,'finite_coverage_fraction':measured/result.size,
                 'survey_files':used,'overlap_method':'newest finite sample within selected year; no interpolation'}


def acquire_bathymetry(bounds, output, terrain_source):
    evidence={'provider':'ea-multibeam-bathymetry','status':'unavailable','attempts':[],
              'depth_policy':'absolute measured ODN bed elevations only; unknown remains unknown',
              'selection_policy':'first usable newest archive, at most four attempts; cross-archive mosaics unsupported'}
    if terrain_source.get('vertical_datum')!='ODN':
        evidence.update(status='not_supported',reason='Requires terrain in ODN; no vertical-datum guessing')
        return None,None,evidence
    try:
        ensure_ea_grid(output)
        group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
        if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
            raise ValueError('Best metre-scale horizontal transformation required')
        native=group.transformers[0].transform_bounds(*bounds,densify_pts=21)
        payload=download(INDEX,3_000_000)
        matches=candidates(payload,native)
        evidence.update(index_url=INDEX,index_sha256=hashlib.sha256(payload).hexdigest(),
                        matching_archives=len(matches),candidate_budget=4)
        (output/'bathymetry-discovery.json').write_text(json.dumps({**evidence,'candidates':matches},indent=2))
        for selection in matches[:4]:
            try:
                archive=download(selection['url'],100_000_000)
                path,coverage=crop_archive(archive,selection,native,output)
                source={'id':'ea-bathymetry','url':selection['url'],'metadata_url':METADATA,
                        'license':'OGL-UK-3.0','attribution':'Contains Environment Agency information © Environment Agency and/or database right',
                        'resolution_m':.5,'vertical_datum':'ODN','year':selection['year'],**coverage,
                        'coordinate_transform':{'best_available':True,'accuracy_m':group.transformers[0].accuracy},
                        'archive_sha256':hashlib.sha256(archive).hexdigest()}
                evidence.update(status='downloaded',selected=source)
                return {'path':str(path.resolve()),'source_id':source['id'],'units':'m',
                        'vertical_datum':'ODN','elevation_type':'bed_elevation'},source,evidence
            except (ValueError,requests.RequestException,rasterio.errors.RasterioError,zipfile.BadZipFile) as error:
                evidence['attempts'].append({'url':selection['url'],'reason':str(error)})
        evidence['reason']='No usable measured raster in checked catalogue coverage; no depths invented'
    except (ValueError,KeyError,TypeError,requests.RequestException,zipfile.BadZipFile) as error:
        evidence['reason']=str(error)
    return None,None,evidence
