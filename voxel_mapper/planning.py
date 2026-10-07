"""Automatic England planning evidence discovery; records are not built geometry."""
import copy
import datetime
import hashlib
import json
import time

import requests
from pyproj import CRS, Transformer
from shapely import wkt
from shapely.geometry import box, shape
from shapely.ops import transform
from shapely.strtree import STRtree
from shapely.errors import GEOSException

from .acquisition import USER_AGENT

BASE = 'https://www.planning.data.gov.uk'
SOURCE = {'id': 'planning-data-england', 'url': BASE,
          'license': 'OGL-UK-3.0', 'attribution': '© Crown copyright and database right; Planning Data'}
DATASETS = ('local-planning-authority', 'planning-application', 'listed-building')


def discover_planning(bounds, output, max_pages=5, page_size=100):
    """Bounded spatial queries with raw pages, checksums and explicit gaps."""
    west, south, east, north = bounds
    result = {'provider': SOURCE['id'], 'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'datasets': [], 'records': [], 'documents': {'status': 'unavailable'},
              'limitations': ['National coverage is incomplete; empty results do not prove absence',
                              'Council portal crawling and drawing interpretation are not implemented',
                              'Planning approval/site boundaries do not prove construction or physical geometry']}
    # Provider discovery window, not a claim that all these coordinates are England.
    if east < -7 or west > 2.3 or north < 49.8 or south > 56:
        result['status'] = 'not_supported'
        return result
    directory = output / 'planning-evidence'
    directory.mkdir(parents=True, exist_ok=True)
    area = box(west, south, east, north)
    seen = set()
    for dataset in DATASETS:
        entry = {'dataset': dataset, 'status': 'downloaded', 'pages': [], 'record_count': 0}
        result['datasets'].append(entry)
        try:
            for page in range(max_pages):
                response = requests.get(BASE+'/entity.json', params={
                    'dataset': dataset, 'geometry': area.wkt, 'geometry_relation': 'intersects',
                    'limit': page_size, 'offset': page*page_size},
                    headers={'User-Agent': USER_AGENT}, timeout=(10, 30))
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get('entities'), list):
                    raise ValueError('Malformed planning response')
                raw = json.dumps(data).encode()
                filename = f'{dataset}-{page}.json'
                (directory / filename).write_bytes(raw)
                entry['pages'].append({'file': 'planning-evidence/'+filename,
                                       'sha256': hashlib.sha256(raw).hexdigest()})
                added = 0
                for record in data['entities']:
                    if record.get('dataset') != dataset or record.get('entity') is None:
                        raise ValueError('Unexpected dataset or missing entity ID')
                    identity = (dataset, str(record['entity']))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    result['records'].append(record)
                    added += 1
                    entry['record_count'] += 1
                if not data.get('links', {}).get('next') and len(data['entities']) < page_size:
                    break
                if not added:
                    raise ValueError('Pagination did not advance')
                if page == max_pages-1:
                    entry['status'] = 'truncated'
                else:
                    time.sleep(.25)
            if not entry['record_count']:
                entry['status'] = 'empty_coverage_unknown'
        except (requests.RequestException, ValueError, TypeError, AttributeError) as error:
            entry.update(status='unavailable_or_incomplete', reason=str(error))
    try:
        response = requests.get(BASE+'/dataset/planning-application-document.json',
                                headers={'User-Agent': USER_AGENT}, timeout=(10, 30))
        response.raise_for_status()
        data = response.json()
        if data.get('dataset') != 'planning-application-document':
            raise ValueError('Unexpected document catalogue')
        (directory/'document-catalogue.json').write_text(json.dumps(data, indent=2))
        result['documents'] = {'status': 'catalogue_empty' if data.get('entity-count') == 0 else 'catalogue_present_not_acquired',
                               'entity_count': data.get('entity-count'),
                               'source_url': BASE+'/dataset/planning-application-document'}
    except (requests.RequestException, ValueError, AttributeError) as error:
        result['documents'] = {'status': 'unavailable', 'reason': str(error)}
    result['status'] = 'checked'
    (output/'planning-discovery.json').write_text(json.dumps(result, indent=2))
    return result


def match_planning(collection, discovery, bounds, max_candidates=100_000):
    """Attach auditable context references; preserve all original geometry/tags."""
    enriched = copy.deepcopy(collection)
    west, south, east, north = bounds
    area = box(west, south, east, north)
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m')
    projector = Transformer.from_crs(4326, crs, always_xy=True)
    features, geometries = [], []
    for feature in enriched['features']:
        geometry = shape(feature['geometry'])
        if geometry.is_valid and not geometry.is_empty:
            features.append(feature)
            geometries.append(transform(projector.transform, geometry))
    tree = STRtree(geometries)
    matches, authorities, examined = [], [], 0
    for record in discovery['records']:
        rid = f"planning/{record.get('dataset')}/{record.get('entity')}"
        match = {'record': rid, 'status': 'unmatched', 'candidates': [],
                 'geometry_action': 'unchanged', 'construction_status': 'not_verified'}
        matches.append(match)
        try:
            # A site polygon is context, never silently relabelled as a building.
            geometry = wkt.loads(record.get('geometry') or record.get('point') or '')
            if geometry.is_empty or not geometry.is_valid or not area.intersects(geometry):
                raise ValueError('Invalid or out-of-area evidence geometry')
            if record.get('dataset') == 'local-planning-authority':
                authorities.append({'entity': record['entity'], 'name': record.get('name'),
                                    'reference': record.get('reference'),
                                    'record_url': BASE+f"/entity/{record['entity']}"})
                match['status'] = 'authority_context'
                continue
            projected = transform(projector.transform, geometry)
            indices = tree.query(projected, predicate='intersects')
            examined += len(indices)
            if examined > max_candidates:
                raise ValueError('Planning match candidate budget exceeded')
            for index in indices:
                feature = features[int(index)]
                overlap = projected.intersection(geometries[int(index)])
                match['candidates'].append({'feature': feature.get('id'),
                    'relation': 'point_intersects' if geometry.geom_type == 'Point' else 'site_intersects',
                    'intersection_area_m2': overlap.area})
            if indices.size:
                # These links are evidence associations, not assertions of identity.
                match['status'] = 'candidate_context' if len(indices) == 1 else 'ambiguous_context'
                for index in indices:
                    props = features[int(index)].setdefault('properties', {})
                    props.setdefault('planning_evidence', []).append({'record': rid,
                        'source_id': SOURCE['id'], 'relationship': match['status'],
                        'dataset': record.get('dataset'), 'reference': record.get('reference'),
                        'entry_date': record.get('entry-date'), 'start_date': record.get('start-date'),
                        'record_url': BASE+f"/entity/{record['entity']}",
                        'construction_status': 'not_verified'})
        except (ValueError, TypeError, AttributeError, GEOSException) as error:
            if 'budget exceeded' in str(error):
                raise
            match.update(status='rejected', reason=str(error))
    return enriched, {'method': 'spatial_context_only', 'metric_crs': crs.to_wkt(),
                      'candidate_checks': examined, 'authorities': authorities, 'matches': matches,
                      'geometry_replacements': 0, 'added_physical_features': 0}
