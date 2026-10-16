"""Retain exact dated terrain windows and an OSM snapshot for a 192 m pilot."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds
from pyproj import CRS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.cli import parse_osm
from voxel_mapper.horizontal_grid import OSTN15Transform
from voxel_mapper.transport import TRANSPORT_KINDS

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'dtm': ('115d6c9b030fe18c2dff2cbebd7a87198c28c5f70f6327ca2e7d2dd2c7162b79',
            '57becd3683c8492b645472d936ff0d714acd5d037326a6c6f0b6050e04eb2493'),
    'dsm': ('8ed17ab23fefdd981751bee5a8df9ab4cbdb36efc42c190656b53eae2aab1329',
            'caca385431739d291ab92f839e26840eee76650ab5593088a48dbfeac04907af'),
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def normalize_osm(data):
    root = ET.fromstring(data)
    if root.tag != 'osm' or len(root) > 100_000:
        raise ValueError('Bounded OSM map snapshot required')
    nodes = {int(node.attrib['id']): {'type': 'node', 'id': int(node.attrib['id']),
             'lon': float(node.attrib['lon']), 'lat': float(node.attrib['lat']),
             'tags': {tag.attrib['k']: tag.attrib['v'] for tag in node.findall('tag')}}
             for node in root.findall('node')}
    ways = {}
    for way in root.findall('way'):
        refs = [int(node.attrib['ref']) for node in way.findall('nd')]
        ways[int(way.attrib['id'])] = {'type': 'way', 'id': int(way.attrib['id']), 'nodes': refs,
            'geometry': [{'lon': nodes[n]['lon'], 'lat': nodes[n]['lat']} for n in refs],
            'tags': {tag.attrib['k']: tag.attrib['v'] for tag in way.findall('tag')}}
    relations = []
    for relation in root.findall('relation'):
        relations.append({'type': 'relation', 'id': int(relation.attrib['id']),
            'tags': {tag.attrib['k']: tag.attrib['v'] for tag in relation.findall('tag')},
            'members': [{'type': member.attrib['type'], 'ref': int(member.attrib['ref']),
                         'role': member.attrib.get('role', ''),
                         'geometry': ways.get(int(member.attrib['ref']), {}).get('geometry', [])}
                        for member in relation.findall('member')]})
    return {'source_xml_sha256': hashlib.sha256(data).hexdigest(),
            'elements': list(nodes.values()) + list(ways.values()) + relations}


def retain(dtm_archive, dsm_archive, osm_map, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh retention output directory required')
    core = json.loads((ROOT / 'examples/wicker-component-review-config.json').read_text())
    west, south, east, north = core['bbox']
    origin = [(west + east) / 2, (south + north) / 2]
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={origin[1]} +lon_0={origin[0]} +datum=WGS84 +units=m')
    from pyproj import Transformer
    geographic = Transformer.from_crs(crs, 4326, always_xy=True)
    west, south = geographic.transform(-96, -96)
    east, north = geographic.transform(96, 96)
    bbox = [west, south, east, north]
    operation = {'method': 'ostn15-bng-v1', 'path': str(ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid.tif'),
                 'sha256': '48dc9fd95196e22d987353bc128186890fc5283d0bc82c7fc1d0e461cdfa3117'}
    to_bng = OSTN15Transform(crs, 27700, operation)
    corners = [to_bng.transform(x, z) for x, z in [(-96, -96), (-96, 96), (96, -96), (96, 96)]]
    bounds = [math.floor(min(p[0] for p in corners)) - 4, math.floor(min(p[1] for p in corners)) - 4,
              math.ceil(max(p[0] for p in corners)) + 4, math.ceil(max(p[1] for p in corners)) + 4]
    output.mkdir(parents=True)
    receipts = {}
    for kind, archive_path in [('dtm', dtm_archive), ('dsm', dsm_archive)]:
        if sha(archive_path) != EXPECTED[kind][0]:
            raise ValueError('Original EA archive checksum mismatch: ' + kind)
        with zipfile.ZipFile(archive_path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith('.tif')]
            if len(names) != 1:
                raise ValueError('One original raster required per EA archive')
            data = archive.read(names[0])
        if hashlib.sha256(data).hexdigest() != EXPECTED[kind][1]:
            raise ValueError('Original EA raster checksum mismatch: ' + kind)
        with MemoryFile(data) as memory, memory.open() as source:
            if source.crs.to_epsg() != 27700 or source.res != (1, 1):
                raise ValueError('Original native one-metre BNG raster required')
            window = from_bounds(*bounds, source.transform).round_offsets().round_lengths()
            if (window.col_off < 0 or window.row_off < 0
                    or window.col_off + window.width > source.width
                    or window.row_off + window.height > source.height):
                raise ValueError('Requested crop is outside the retained survey raster')
            values = source.read(1, window=window)
            if values.shape != (int(window.height), int(window.width)):
                raise ValueError('Incomplete native raster window')
            profile = source.profile.copy()
            profile.update(width=int(window.width), height=int(window.height),
                           transform=source.window_transform(window), compress='deflate', predictor=3)
            path = output / ('ea-buffer-' + kind + '.tif')
            with rasterio.open(path, 'w', **profile) as target:
                target.write(values, 1)
            with rasterio.open(path) as retained:
                assert np.array_equal(values, retained.read(1), equal_nan=True)
            receipts[kind] = {'archive_sha256': EXPECTED[kind][0], 'original_raster_sha256': EXPECTED[kind][1],
                'archive_member': names[0], 'crop_sha256': sha(path), 'bounds_bng_m': bounds,
                'dimensions_pixels': [int(window.width), int(window.height)], 'resampling': 'none',
                'native_samples_equal': True, 'nodata_preserved': source.nodata,
                'survey_date': '2022-01-05', 'survey_id': 'P_10682',
                'url': f'https://environment.data.gov.uk/tiles/collections/survey/national_lidar_programme_{kind}/2022/1/SK0540'}
    xml = Path(osm_map).read_bytes()
    if len(xml) > 32_000_000:
        raise ValueError('OSM snapshot byte budget exceeded')
    returned = ET.fromstring(xml).find('bounds')
    if returned is None:
        raise ValueError('OSM map response bounds required')
    returned_bbox = [float(returned.attrib[key]) for key in ('minlon', 'minlat', 'maxlon', 'maxlat')]
    if any(abs(a - b) > 5e-8 for a, b in zip(returned_bbox, bbox)):
        raise ValueError('OSM map response does not match the buffered request bounds')
    raw = normalize_osm(xml)
    collection, skipped = parse_osm(raw)
    retained, omitted = [], []
    for feature in collection['features']:
        if feature['properties']['kind'] in TRANSPORT_KINDS | {'parking'}:
            retained.append(feature)
        else:
            omitted.append({'id': feature['id'], 'kind': feature['properties']['kind']})
    (output / 'osm-map.xml').write_bytes(xml)
    write(output / 'osm-elements.json', raw)
    write(output / 'mapped-surfaces.geojson', {'type': 'FeatureCollection', 'features': retained,
                                              'planning_geometry_records': []})
    receipt = {'version': 'retained-buffer-context-v1', 'bbox': bbox, 'local_origin_wgs84': origin,
               'core_config_sha256': sha(ROOT / 'examples/wicker-component-review-config.json'),
               'rasters': receipts, 'osm_xml_sha256': raw['source_xml_sha256'],
               'osm_elements_sha256': sha(output / 'osm-elements.json'),
               'mapped_surfaces_sha256': sha(output / 'mapped-surfaces.geojson'),
               'mapped_surfaces': len(retained), 'omitted_generic_features': omitted, 'skipped': skipped}
    write(output / 'retention-receipt.json', receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dtm_archive', 'dsm_archive', 'osm_map', 'output'):
        parser.add_argument('--' + name.replace('_', '-'), required=True, type=Path)
    args = parser.parse_args()
    result = retain(args.dtm_archive, args.dsm_archive, args.osm_map, args.output)
    print(json.dumps({'output': str(args.output), 'mapped_surfaces': result['mapped_surfaces'],
                      'bounds': result['bbox']}))
