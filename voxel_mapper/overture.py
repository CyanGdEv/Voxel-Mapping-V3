"""Automatic supplemental building footprints with conservative source conflict checks."""
import copy
import datetime
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import requests
from pyproj import CRS, Geod, Transformer
from shapely.geometry import box, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from .acquisition import USER_AGENT

CATALOG = 'https://stac.overturemaps.org/catalog.json'
SOURCE = {'id':'overture-buildings','url':'https://docs.overturemaps.org/guides/buildings/',
          'license':'ODbL-1.0','attribution_url':'https://docs.overturemaps.org/attribution/#buildings',
          'attribution':'© OpenStreetMap contributors, Overture Maps Foundation; '
          'Esri Community Maps contributors (CC BY 4.0); Microsoft Global ML Building Footprints (ODbL); '
          'Google Open Buildings (CC BY 4.0); USGS 3DEP; Qian Shi et al. '
          '(doi:10.5281/zenodo.8174931, CC BY 4.0); derived from BTN 2024, ign.es (CC BY 4.0). '
          'Per-feature upstream records retained; footprints may be imagery-derived roofprints.'}


def acquire_buildings(bounds, output, timeout=180, max_features=20_000, max_bytes=64_000_000):
    """Pin the current official release; never ingest a partial worker download."""
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    result = {'provider':SOURCE['id'],'status':'unavailable','feature_count':0,
              'queried_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'catalog_url':CATALOG,'bbox':list(bounds),'failures':[]}
    collection = {'type':'FeatureCollection','features':[]}
    pending = output/'overture-buildings.partial.jsonl'
    destination = output/'overture-buildings.geojsonl'
    try:
        west,south,east,north = map(float,bounds)
        if not (-180<=west<east<=180 and -90<south<north<90):
            raise ValueError('Invalid bounded WGS84 area')
        geod = Geod(ellps='WGS84')
        area = abs(geod.polygon_area_perimeter([west,east,east,west],[south,south,north,north])[0])
        if area>4_000_000 or min(timeout,max_features,max_bytes)<=0:
            raise ValueError('Overture area/resource budget exceeded')
        with requests.get(CATALOG,headers={'User-Agent':USER_AGENT},timeout=(10,30),stream=True) as response:
            response.raise_for_status()
            chunks, size = [],0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size>1_000_000:
                    raise ValueError('Catalog byte budget exceeded')
                chunks.append(chunk)
        catalog_bytes = b''.join(chunks)
        catalog = json.loads(catalog_bytes)
        release = catalog.get('latest')
        if not isinstance(release,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.\d+',release):
            raise ValueError('Missing/invalid current Overture release')
        result.update(release=release,catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest())
        (output/'overture-catalog.json').write_bytes(catalog_bytes)
        worker = subprocess.run([sys.executable,'-m','voxel_mapper.overture_worker',release,
            json.dumps(list(bounds)),str(pending),str(max_features),str(max_bytes)],
            timeout=timeout,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if worker.returncode:
            raise ValueError('Overture reader failed: '+worker.stderr.decode(errors='replace')[-2000:])
        if not pending.exists() or pending.stat().st_size>max_bytes:
            raise ValueError('Missing/oversized Overture download')
        with pending.open() as stream:
            for line in stream:
                if len(collection['features']) >= max_features:
                    raise ValueError('Overture feature budget exceeded')
                record = json.loads(line)
                if record.get('type')!='Feature' or not isinstance(record.get('properties'),dict):
                    raise ValueError('Invalid Overture feature envelope')
                collection['features'].append(record)
        pending.replace(destination)
        result.update(status='downloaded' if collection['features'] else 'empty_coverage_unknown',
                      feature_count=len(collection['features']),file=destination.name,
                      sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    except (requests.RequestException,ValueError,TypeError,OSError,subprocess.TimeoutExpired) as error:
        collection['features'] = []
        result['failures'].append(str(error))
    finally:
        pending.unlink(missing_ok=True)
        (output/'overture-discovery.json').write_text(json.dumps(result,indent=2))
    return collection,result


def supplement_buildings(collection, supplemental, bounds, release=None, max_checks=100_000):
    """Add only disjoint non-OSM ground polygons; keep original features unchanged."""
    enriched = copy.deepcopy(collection)
    report = {'provider':SOURCE['id'],'release':release,'added_physical_features':0,
              'geometry_replacements':0,'checks':0,'decisions':[],
              'accuracy_status':'draft_unverified','limitations':[
                  'Additional footprint/roofprint evidence, not verified as-built surveys',
                  'OSM-derived geometry is not independent corroboration and is never reintroduced',
                  'Overlapping/nearby candidates are withheld, not clipped into invented buildings',
                  'No attribute replacement, classified meshes, facades or building-part assembly']}
    west,south,east,north = bounds
    target = CRS.from_proj4(f'+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m')
    projector = Transformer.from_crs(4326,target,always_xy=True)
    area = box(*bounds)
    protected, protected_ids = [],[]
    # Every existing feature blocks new footprints; includes mapped paths/ride lines.
    for feature in collection['features']:
        geometry = shape(feature['geometry'])
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError('Cannot resolve conflicts against invalid existing geometry')
        metric = transform(projector.transform,geometry)
        if not all(math.isfinite(v) for v in metric.bounds):
            raise ValueError('Nonfinite existing geometry')
        protected.append(metric.buffer(2)); protected_ids.append(feature.get('id'))
    tree = STRtree(protected)
    seen, accepted_metric = set(),[]
    candidates = supplemental.get('features',[])
    if len(candidates)>20_000:
        raise ValueError('Supplemental feature budget exceeded')
    for feature in sorted(candidates,key=lambda f:str(f.get('id',''))):
        decision = {'feature':feature.get('id'),'status':'rejected'}
        report['decisions'].append(decision)
        try:
            identity = feature.get('id')
            if not isinstance(identity,str) or not identity or identity in seen:
                raise ValueError('Missing/duplicate source identity')
            seen.add(identity)
            properties = feature['properties']
            if properties.get('type')!='building' or properties.get('theme')!='buildings':
                raise ValueError('Not a building footprint record')
            if properties.get('is_underground') not in (None,False) or properties.get('level') not in (None,0) or properties.get('min_height') not in (None,0) or properties.get('min_floor') not in (None,0):
                raise ValueError('Underground/elevated building requires absolute elevation evidence')
            upstream = properties.get('sources') or []
            geometry_sources = [s for s in upstream if s.get('property') in (None,'','/geometry')]
            if not geometry_sources or any(not s.get('dataset') or not (s.get('record_id') or all(s.get(k) for k in ('provider','resource','version'))) for s in geometry_sources):
                raise ValueError('Traceable upstream geometry sources required')
            if any('openstreetmap' in str(s['dataset']).lower() for s in geometry_sources):
                raise ValueError('OSM-derived geometry withheld; existing OSM is authoritative')
            for source in geometry_sources:
                confidence = source.get('confidence')
                if confidence is not None and (not math.isfinite(float(confidence)) or not .9<=float(confidence)<=1):
                    raise ValueError('Upstream geometry confidence below 0.9 or invalid')
            geometry = shape(feature['geometry'])
            if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.has_z or geometry.is_empty or not geometry.is_valid or not area.intersects(geometry):
                raise ValueError('Invalid/nonpolygon/3D/out-of-area geometry')
            if not (-180<=geometry.bounds[0]<=geometry.bounds[2]<=180 and -90<geometry.bounds[1]<=geometry.bounds[3]<90):
                raise ValueError('Invalid geographic coordinates')
            metric = transform(projector.transform,geometry)
            if not math.isfinite(metric.area) or not 2<=metric.area<=100_000:
                raise ValueError('Footprint outside supported 2–100,000 m² range')
            overlaps = tree.query(metric,predicate='intersects')
            report['checks'] += len(overlaps)+1
            if report['checks']>max_checks:
                raise RuntimeError('Supplement conflict budget exceeded')
            if len(overlaps):
                decision['conflicts'] = [protected_ids[int(i)] for i in overlaps]
                raise ValueError('Within 2 m of existing mapped geometry')
            for prior in accepted_metric:
                report['checks'] += 1
                if report['checks']>max_checks:
                    raise RuntimeError('Supplement conflict budget exceeded')
                if prior.buffer(2).intersects(metric):
                    raise ValueError('Within 2 m of another supplemental footprint')
            height = properties.get('height')
            if height is not None and (not math.isfinite(float(height)) or not 0<float(height)<=120):
                raise ValueError('Invalid/unsupported building height')
            additions = {'kind':'building','source_id':SOURCE['id'],'building':'yes',
                         'overture_release':release,'overture_sources':copy.deepcopy(upstream),
                         'evidence_status':'additional_footprint_unverified',
                         'construction_status':'not_independently_verified',
                         'overture_metadata':copy.deepcopy(properties)}
            if height is not None:
                additions['height_m']=float(height)
            name = (properties.get('names') or {}).get('primary')
            if name:
                additions['name']=name
            enriched['features'].append({'type':'Feature','id':'overture/building/'+identity,
                                        'geometry':copy.deepcopy(feature['geometry']),'properties':additions})
            accepted_metric.append(metric)
            report['added_physical_features'] += 1
            decision.update(status='added_unverified',geometry_sources=copy.deepcopy(geometry_sources),
                            upstream_identity_status='record_ids_available' if all(s.get('record_id') for s in geometry_sources) else 'provider_resource_version_only')
        except (ValueError,TypeError,KeyError,AttributeError) as error:
            decision['reason']=str(error)
    return enriched,report
