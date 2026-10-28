"""Bounded, cached public comparison sources; observations never become labels."""
from io import BytesIO
from concurrent.futures import CancelledError
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
from urllib.parse import urlencode, urljoin

from PIL import Image
import requests

from . import web_evidence as web
from .generation_cycles import atomic_json, file_hash

OPENMAP = 'https://services.arcgis.com/qHLhLQrcvEnxjtPr/arcgis/rest/services/OS_OpenMap_Local_Buildings/FeatureServer/1'
HISTORIC = 'https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/'
HISTORIC_LAYERS = {
    'historic_vertical': HISTORIC+'New_Verticals_20250304_view/FeatureServer/0',
    'historic_oblique': HISTORIC+'Obliques_update_20250304_view/FeatureServer/0',
}
WAYBACK = 'https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json'
HOSTS = ['services.arcgis.com', 'services-eu1.arcgis.com', 's3-us-west-2.amazonaws.com',
         'wayback.maptiles.arcgis.com', 'metadata.maptiles.arcgis.com', 'environment.data.gov.uk']


class Reader:
    def __init__(self, cache, offline=False, cancelled=lambda: False):
        self.cache = Path(cache)
        self.offline = offline
        self.cancelled = cancelled
        self.deadline = time.monotonic()+600
        self.budget = web.Budget(64_000_000)
        self.sources = []

    def get(self, endpoint, params=None, binary=False):
        if params:
            endpoint += '?'+urlencode(params)
        endpoint = web.url(endpoint, HOSTS)
        key = hashlib.sha256(endpoint.encode()).hexdigest()
        folder = self.cache/'mapping-layers'
        body = folder/(key+'.bin')
        receipt = folder/(key+'.json')
        if self.cancelled():
            raise CancelledError('Mapping source retrieval cancelled')
        if receipt.exists():
            record = json.loads(receipt.read_text())
            if record.get('url')!=endpoint or record.get('body_bytes', 0)>16_000_000 or not body.is_file() or file_hash(body)!=record.get('body_sha256'):
                raise ValueError('Mapping source cache changed')
            raw = body.read_bytes()
        else:
            if self.offline:
                raise ValueError('Original mapping source is absent from the offline cache')
            raw = self._download(endpoint)
            # Validate generic finite JSON without routing it through a semantic
            # evidence extractor: ID selections and Wayback catalogues are not
            # feature/label records and have different schemas.
            self._decode(raw, binary)
            record = {'url': endpoint, 'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                      'body_sha256': hashlib.sha256(raw).hexdigest(), 'body_bytes': len(raw),
                      'source_evidence_verified': False, 'training_labels_generated': 0}
            folder.mkdir(parents=True, exist_ok=True)
            body.write_bytes(raw)
            atomic_json(receipt, record)
        self.sources.append(record)
        return self._decode(raw, binary)

    @staticmethod
    def _decode(raw, binary):
        if binary:
            with Image.open(BytesIO(raw)) as image:
                if image.size!=(256, 256) or image.format not in ('PNG', 'JPEG'):
                    raise ValueError('Bounded public map tile required')
                image.verify()
            return raw
        from .research_sources import bounded_json
        data = bounded_json(raw)
        if isinstance(data, dict) and 'error' in data:
            raise ValueError('Public mapping service returned an error')
        return data

    def _download(self, endpoint):
        current = endpoint
        with requests.Session() as client:
            try:
                for _ in range(4):
                    if self.cancelled():
                        raise CancelledError('Mapping source retrieval cancelled')
                    if time.monotonic()>=self.deadline:
                        raise ValueError('Mapping source deadline exceeded')
                    web._public_dns(current, web.socket.getaddrinfo)
                    client.cookies.clear()
                    with client.get(current, stream=True, allow_redirects=False, auth=web._NoOriginAuth(),
                                    headers={'User-Agent': 'VoxelMapperV3 mapping comparison'}, timeout=(5, 15)) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            current = web.url(urljoin(current, response.headers.get('Location', '')), HOSTS)
                            continue
                        if response.status_code!=200:
                            raise ValueError('Mapping source HTTP '+str(response.status_code))
                        raw = bytearray()
                        for chunk in response.iter_content(65536):
                            if self.cancelled():
                                raise CancelledError('Mapping source retrieval cancelled')
                            if time.monotonic()>=self.deadline:
                                raise ValueError('Mapping source deadline exceeded')
                            self.budget.take(len(chunk))
                            raw.extend(chunk)
                            if len(raw)>16_000_000:
                                raise ValueError('Mapping source byte budget exceeded')
                        return bytes(raw)
            except requests.RequestException:
                raise ValueError('Mapping source transport unavailable') from None
        raise ValueError('Mapping source redirect budget exceeded')


def feature_layer(reader, endpoint, bounds, max_features=1500):
    """Fetch a complete bounded selection; never render a silently truncated page."""
    metadata = reader.get(endpoint, {'f': 'json'})
    query = {'geometry': ','.join(map(str, bounds)), 'geometryType': 'esriGeometryEnvelope',
             'inSR': 4326, 'spatialRel': 'esriSpatialRelIntersects', 'where': '1=1'}
    selection = reader.get(endpoint+'/query', {**query, 'returnIdsOnly': 'true', 'f': 'json'})
    ids = selection.get('objectIds')
    if not isinstance(ids, list) or len(ids)>max_features or len(set(ids))!=len(ids):
        raise ValueError('Complete bounded unique feature selection required')
    features = []
    limit = metadata.get('maxRecordCount', 100)
    if type(limit) is not int or limit<=0:
        raise ValueError('Positive mapping service page limit required')
    page_size = min(100, limit)
    for offset in range(0, len(ids), page_size):
        batch = ids[offset:offset+page_size]
        data = reader.get(endpoint+'/query', {'objectIds': ','.join(map(str, batch)),
            'outFields': '*', 'returnGeometry': 'true', 'outSR': 4326, 'f': 'geojson'})
        rows = data.get('features')
        if (data.get('exceededTransferLimit') or data.get('properties', {}).get('exceededTransferLimit') or not isinstance(rows, list) or len(rows)!=len(batch)
                or data.get('type')!='FeatureCollection'):
            raise ValueError('Incomplete mapping feature page')
        field = metadata.get('objectIdField', selection.get('objectIdFieldName'))
        actual = [r.get('properties', {}).get(field, r.get('id')) for r in rows]
        if set(actual)!=set(batch) or len(set(actual))!=len(batch):
            raise ValueError('Mapping page identities differ from selection')
        features.extend(rows)
    return {'type': 'FeatureCollection', 'features': features}, {
        'service': endpoint, 'service_name': metadata.get('name'), 'selected_count': len(ids),
        'editing_info': metadata.get('editingInfo'), 'copyright': metadata.get('copyrightText'),
        'capture_date': None, 'date_scope': 'service editing dates are not survey/capture dates'}


def wayback(reader, release_id, extent, size):
    """Mosaic exact published tiles on the reference grid, with point metadata."""
    catalog = reader.get(WAYBACK)
    entry = catalog.get(release_id)
    if not isinstance(entry, dict):
        raise ValueError('Pinned Wayback release is absent from catalogue')
    template = entry['itemURL']
    # Only the documented public tile endpoint may supply image bytes.
    if not template.startswith('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/'):
        raise ValueError('Unsupported Wayback tile endpoint')
    origin = 20037508.342789244
    for zoom in range(18, 9, -1):
        span = 2*origin/(2**zoom)
        left = math.floor((extent[0]+origin)/span)
        right = math.ceil((extent[2]+origin)/span)-1
        top = math.floor((origin-extent[3])/span)
        bottom = math.ceil((origin-extent[1])/span)-1
        if (right-left+1)*(bottom-top+1)<=36:
            break
    mosaic = Image.new('RGB', ((right-left+1)*256, (bottom-top+1)*256))
    for row in range(top, bottom+1):
        for col in range(left, right+1):
            raw = reader.get(template.replace('{level}', str(zoom)).replace('{row}', str(row)).replace('{col}', str(col)), binary=True)
            with Image.open(BytesIO(raw)) as tile:
                if tile.size!=(256, 256):
                    raise ValueError('Native 256-pixel Wayback tile required')
                mosaic.paste(tile.convert('RGB'), ((col-left)*256, (row-top)*256))
    step = span/256
    x0 = -origin+left*span
    y0 = origin-top*span
    affine = ((extent[2]-extent[0])/size[0]/step, 0, (extent[0]-x0)/step,
              0, (extent[3]-extent[1])/size[1]/step, (y0-extent[3])/step)
    image = mosaic.transform(size, Image.Transform.AFFINE, affine, resample=Image.Resampling.BILINEAR)
    metadata = {'release_id': release_id, **entry, 'tile_zoom': zoom,
                'projected_tile_pixel_spacing_m': step, 'capture_date': None,
                'date_scope': 'itemTitle gives publication date, not local image capture date',
                'point_metadata_applies_to_whole_image': False}
    try:
        endpoint = web.url(entry['metadataLayerUrl'], HOSTS)
        metadata['point_metadata'] = reader.get(endpoint+'/identify', {
            'f': 'json', 'geometry': f'{(extent[0]+extent[2])/2},{(extent[1]+extent[3])/2}',
            'geometryType': 'esriGeometryPoint', 'sr': 3857, 'layers': 'all', 'tolerance': 1,
            'mapExtent': ','.join(map(str, extent)), 'imageDisplay': f'{size[0]},{size[1]},96',
            'returnGeometry': 'false'})
    except (web.WebError, ValueError) as error:
        metadata['point_metadata_error'] = str(error)
    return image, metadata


def overture(reader, bounds, output):
    """Retain complete selections or explicit failures for honest offline replay."""
    key = hashlib.sha256(json.dumps(bounds).encode()).hexdigest()
    folder = reader.cache/'mapping-overture'/key
    receipt = folder/'receipt.json'
    features = folder/'features.geojson'
    if receipt.exists():
        record = json.loads(receipt.read_text())
        if record['bounds']!=bounds or file_hash(features)!=record['features_sha256']:
            raise ValueError('Retained Overture comparison source changed')
        collection = json.loads(features.read_text())
        metadata = record['discovery']
    elif reader.offline:
        raise ValueError('No retained Overture selection or failure for offline replay')
    else:
        if reader.cancelled():
            raise CancelledError('Mapping comparison cancelled')
        from .overture import acquire_buildings
        collection, metadata = acquire_buildings(bounds, folder/'original', timeout=45,
                                                max_features=1500, max_bytes=5_000_000)
        atomic_json(features, collection)
        atomic_json(receipt, {'bounds': bounds, 'features_sha256': file_hash(features), 'discovery': metadata})
    shutil.copytree(folder, output)
    return collection, metadata
