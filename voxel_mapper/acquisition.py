"""Automatic location and public terrain acquisition; retain every request outcome."""
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.transform import from_bounds

USER_AGENT = 'VoxelMapper/3.1 (https://github.com/CyanGdEv/Voxel-Mapping-V3)'
EA_WCS = 'https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs'


def resolve_location(location, output):
    response = requests.get('https://nominatim.openstreetmap.org/search', params={
        'q': location, 'format': 'jsonv2', 'limit': 5, 'polygon_geojson': 1},
        headers={'User-Agent': USER_AGENT}, timeout=45)
    response.raise_for_status()
    results = response.json()
    (output / 'geocoding.json').write_text(json.dumps(results, indent=2))
    parks = [r for r in results if r.get('type') == 'theme_park']
    candidates = parks or results
    if len(candidates) != 1:
        raise ValueError('Location is missing or ambiguous. Use a more specific park name/address, or a bounding box.')
    result = candidates[0]
    south, north, west, east = map(float, result['boundingbox'])
    return [west, south, east, north], result


def download_ea(bounds, output, surface=False):
    """Discover elevation coverage ID via WCS capabilities, then download native 1 m."""
    url = EA_WCS.replace('terrain-model-dtm', 'surface-model-dsm') if surface else EA_WCS
    response = requests.get(url, params={'service': 'WCS', 'version': '1.0.0', 'request': 'GetCapabilities'},
                            headers={'User-Agent': USER_AGENT}, timeout=45)
    response.raise_for_status()
    xml = ET.fromstring(response.content)
    ns = {'wcs': 'http://www.opengis.net/wcs'}
    coverages = [e.text for e in xml.findall('.//wcs:CoverageOfferingBrief/wcs:name', ns)
                 if e.text and 'Elevation' in e.text and 'Hillshade' not in e.text]
    if len(coverages) != 1:
        raise ValueError('EA WCS did not advertise one elevation coverage')
    transformer = Transformer.from_crs(4326, 27700, always_xy=True)
    west, south, east, north = bounds
    corners = [transformer.transform(x,y) for x,y in [(west,south),(west,north),(east,south),(east,north)]]
    bbox = [math.floor(min(x for x,y in corners))-2, math.floor(min(y for x,y in corners))-2,
            math.ceil(max(x for x,y in corners))+2, math.ceil(max(y for x,y in corners))+2]
    if (bbox[2]-bbox[0])*(bbox[3]-bbox[1]) > 8_000_000:
        raise ValueError('EA request exceeds 8 million native pixels; split area')
    params = {'service':'WCS', 'version':'1.0.0', 'request':'GetCoverage', 'coverage':coverages[0],
              'crs':'EPSG:27700', 'bbox':','.join(map(str,bbox)), 'format':'GeoTIFF', 'resx':1, 'resy':1}
    response = requests.get(url, params=params, headers={'User-Agent': USER_AGENT}, timeout=180)
    response.raise_for_status()
    if response.content[:2] not in (b'II', b'MM'):
        raise ValueError('EA returned a non-GeoTIFF response')
    path = output / ('ea-dsm.tif' if surface else 'ea-dtm.tif')
    path.write_bytes(response.content)
    with rasterio.open(path) as dataset:
        if not dataset.crs or dataset.count != 1:
            raise ValueError('Invalid EA elevation raster')
        values = dataset.read(1, masked=True)
        if values.count() == 0:
            raise ValueError('EA raster contains no elevation coverage')
    source = {'id':'ea-dsm' if surface else 'ea-dtm', 'url':url, 'license':'OGL-UK-3.0',
              'resolution_m':1, 'vertical_datum':'ODN', 'coverage_id':coverages[0],
              'attribution':'Contains Environment Agency information © Environment Agency and/or database right',
              'request_url':response.url}
    return {'path':str(path.resolve()), 'source_id':source['id'], 'units':'m', 'vertical_datum':'ODN'}, source


def download_global(bounds, output, spacing_m=30):
    """Automatically sample Mapzen at a bounded grid; this is coarse fallback terrain."""
    west, south, east, north = bounds
    latitude = (south+north)/2
    width = (east-west)*111320*max(.01,math.cos(math.radians(latitude)))
    height = (north-south)*111320
    cols, rows = max(2,math.ceil(width/spacing_m)), max(2,math.ceil(height/spacing_m))
    if cols*rows > 20_000:
        raise ValueError('Automatic terrain sample budget exceeded; split area')
    transform = from_bounds(west,south,east,north,cols,rows)
    locations = [(row,col,*rasterio.transform.xy(transform,row,col)) for row in range(rows) for col in range(cols)]
    values = np.full((rows,cols), -9999, dtype='float32')
    responses = []
    previous = 0.0
    for start in range(0,len(locations),100):
        delay = 1.05 - (time.monotonic()-previous)
        if delay > 0:
            time.sleep(delay)
        batch = locations[start:start+100]
        previous = time.monotonic()
        response = requests.get('https://api.opentopodata.org/v1/mapzen', params={
            'locations':'|'.join(f'{lat:.8f},{lon:.8f}' for row,col,lon,lat in batch),
            'interpolation':'bilinear', 'nodata_value':'null'}, headers={'User-Agent':USER_AGENT}, timeout=60)
        response.raise_for_status()
        data = response.json()
        responses.append(data)
        (output/'terrain-api-responses.json').write_text(json.dumps(responses))
        if data.get('status') != 'OK' or len(data.get('results',[])) != len(batch):
            raise ValueError('Elevation API returned an incomplete response')
        for point, result in zip(batch,data['results']):
            row,col,lon,lat = point
            returned = result.get('location',{})
            if abs(returned.get('lat',999)-lat) > 1e-6 or abs(returned.get('lng',999)-lon) > 1e-6 or result.get('dataset') != 'mapzen':
                raise ValueError('Elevation response coordinates or dataset do not match request')
            elevation = result.get('elevation')
            if elevation is not None and math.isfinite(float(elevation)):
                values[row,col] = float(elevation)
    path = output/'global-terrain.tif'
    with rasterio.open(path,'w',driver='GTiff',width=cols,height=rows,count=1,dtype='float32',
                       crs='EPSG:4326',transform=transform,nodata=-9999) as dataset:
        dataset.write(values,1)
    if np.all(values == -9999):
        raise ValueError('Automatic terrain provider returned no elevations')
    source = {'id':'mapzen', 'url':'https://www.opentopodata.org/datasets/mapzen/',
              'license':'Mixed sources; preserve Mapzen attribution', 'resolution_m':30,
              'attribution_url':'https://github.com/tilezen/joerd/blob/master/docs/attribution.md',
              'vertical_datum':'Mapzen mixed-source heights; datum not independently verified',
              'grid_spacing_m':spacing_m}
    return {'path':str(path.resolve()),'source_id':'mapzen','units':'m','vertical_datum':source['vertical_datum']}, source


def acquire_terrain(bounds, output):
    attempts = []
    west,south,east,north = bounds
    if -7.2 <= west < east <= 2.2 and 49.8 <= south < north <= 55.9:
        try:
            terrain, source = download_ea(bounds,output)
            attempts.append({'provider':'ea-dtm','status':'downloaded'})
            return terrain, source, attempts
        except (requests.RequestException, ValueError, ET.ParseError, rasterio.errors.RasterioError) as error:
            attempts.append({'provider':'ea-dtm','status':'unavailable','reason':str(error)})
    terrain, source = download_global(bounds,output)
    attempts.append({'provider':'mapzen','status':'downloaded','warning':'coarse mixed-source terrain; not survey quality'})
    return terrain, source, attempts
