"""Portable aligned source layers for visual verification, without geometry edits."""
import argparse
import base64
from concurrent.futures import CancelledError
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from .generation_cycles import atomic_json, file_hash
from . import mapping_layer_sources as sources

VERSION = 'mapping-source-layers-v1'
FAMILIES = {
    'draft_labels': ('Current draft labels', '#559ee9', 'https://github.com/CyanGdEv/Voxel-Mapping-V3',
        'Source-assisted training drafts, not independent verification. Ground beneath canopy remains separate from observed labels.'),
    'os_zoomstack': ('GB topographic context', '#62c6a2', 'https://www.arcgis.com/home/item.html?id=2d5a797a822b462e9aa5a6bdbf34bf2f',
        'OS Open Zoomstack vector-tile context. Generalisation and tile fragments limit precise boundary checks; related OS layers are not independent votes.'),
    'lidar_context': ('LiDAR raster context', '#adc6e0', 'https://environment.data.gov.uk/',
        'Dated native one-metre DTM/DSM context sampled onto the image grid. Missing cells remain transparent.'),
    'os_openmap': ('OS OpenMap Local buildings', '#e066f4', 'https://www.ordnancesurvey.co.uk/products/os-open-map-local',
        'Generalised outlines via Esri UK; not surveyed narrow-path edges. Service update dates are not survey dates.'),
    'os_detailed': ('Detailed OS / NGD', '#bd79e8', 'https://www.ordnancesurvey.co.uk/products/os-mastermap-topography-layer',
        'Requires an appropriately licensed local vector import. Public basemap viewing does not provide reusable vectors.'),
    'wayback': ('Historical aerial imagery', '#8eb8f4', 'https://livingatlas.arcgis.com/wayback/',
        'Publication dates differ from image capture dates. Different releases may reuse the same photograph.'),
    'planning': ('Planning surveys and drawings', '#f6ac45', 'https://www.staffsmoorlands.gov.uk/article/1442/Interactive-planning-map',
        'Import registered geometry with document, page and existing/proposed status. Proposed plans are not proof of construction.'),
    'mapillary': ('Mapillary ground photographs', '#facc50', 'https://www.mapillary.com/app/',
        'Coverage is unverified here. Import geotagged photo locations or authorised exports; photo positions are not measured boundaries.'),
    'overture': ('Overture buildings', '#f48676', 'https://docs.overturemaps.org/guides/buildings/',
        'May reuse OSM or imagery-derived roofprints. Agreement with its upstream source is not independent corroboration.'),
    'historic': ('Historic England photo locations', '#4bd2cc', 'https://historicengland.org.uk/images-books/archive/collections/aerial-photos/',
        'Catalogue camera locations, not photo footprints or aligned historical imagery. Photograph rights vary by record.'),
    'raw_lidar': ('Raw LiDAR returns', '#f5db71', 'https://environment.data.gov.uk/dataset/094d4ec8-4c21-4aa6-817f-b7e45843c5e0',
        'Observed returns and recorded classes only. Gaps, sparse returns and source classifications do not prove semantic boundaries.'),
}


def _read(path, limit=16_000_000):
    path = Path(path)
    if not path.is_file() or path.stat().st_size>limit:
        raise ValueError('Bounded existing layer input required')
    def invalid(value):
        raise ValueError('Finite layer JSON required')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=invalid)


def _asset(base, entry, field):
    path = (Path(base)/entry[field]).resolve()
    if not path.is_file() or file_hash(path)!=entry[field+'_sha256']:
        raise ValueError('Pinned layer input changed: '+field)
    return path


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', value):
        raise ValueError('Simple bounded layer identity required')
    return value


def validate(config):
    if not isinstance(config, dict) or config.get('version')!=VERSION or set(config)-{
        'version', 'site', 'areas', 'imports', 'providers', 'wayback_releases', 'offline',
        'datum_grid_file', 'datum_grid_file_sha256'}:
        raise ValueError('Versioned mapping layer request required')
    if not isinstance(config.get('site'), str) or not 1<=len(config['site'])<=200:
        raise ValueError('Named comparison site required')
    areas = config.get('areas')
    if not isinstance(areas, list) or not 1<=len(areas)<=8:
        raise ValueError('One to eight comparison areas required')
    ids = [_id(a['id']) for a in areas]
    if len(set(ids))!=len(ids):
        raise ValueError('Distinct comparison areas required')
    providers = config.get('providers', [])
    if not isinstance(providers, list) or set(providers)-{'os_openmap', 'historic', 'wayback', 'overture'} or len(set(providers))!=len(providers):
        raise ValueError('Known distinct public layer providers required')
    releases = config.get('wayback_releases', [])
    if not isinstance(releases, list) or len(releases)>2 or len(set(releases))!=len(releases) or any(not isinstance(v, str) or not v.isdigit() for v in releases):
        raise ValueError('At most two pinned Wayback releases required')
    if type(config.get('offline', False)) is not bool:
        raise ValueError('Explicit offline mode required')
    imports = config.get('imports', [])
    if not isinstance(imports, list) or len(imports)>24 or len({_id(v['id']) for v in imports})!=len(imports):
        raise ValueError('Bounded distinct local layers required')
    for item in imports:
        if item.get('family') not in FAMILIES or item.get('format') not in ('geojson', 'las'):
            raise ValueError('Known imported layer family and format required')
        if not isinstance(item.get('metadata'), dict) or not item['metadata'].get('source_url') or not item['metadata'].get('license'):
            raise ValueError('Import source and licence metadata required')
        sources.web.url(item['metadata']['source_url'])


def image_uri(image):
    stream = BytesIO()
    image.save(stream, format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')


def project_features(collection, crs, extent, size):
    """Clip in map coordinates and preserve holes; never estimate path widths."""
    if crs not in ('EPSG:4326', 'EPSG:3857', 'EPSG:27700'):
        raise ValueError('Explicit supported source CRS required')
    if collection.get('type')!='FeatureCollection' or not isinstance(collection.get('features'), list) or len(collection['features'])>5000:
        raise ValueError('Bounded feature collection required')
    declared = collection.get('crs', {}).get('properties', {}).get('name')
    if declared and declared not in (crs, 'urn:ogc:def:crs:OGC:1.3:CRS84' if crs=='EPSG:4326' else crs):
        raise ValueError('Declared vector CRS conflicts with import')
    if crs=='EPSG:27700':
        from pyproj.transformer import TransformerGroup
        group = TransformerGroup(27700, 3857, always_xy=True, allow_ballpark=False)
        if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
            raise ValueError('Best metre-scale datum transform required for BNG vectors')
        projector = group.transformers[0]
    else:
        projector = Transformer.from_crs(crs, 3857, always_xy=True)
    boundary = box(*extent)
    result = []
    coordinates = 0
    def xy(x, y):
        return [(x-extent[0])/(extent[2]-extent[0])*size[0], (extent[3]-y)/(extent[3]-extent[1])*size[1]]
    def part(g):
        nonlocal coordinates
        if g.is_empty:
            return []
        if hasattr(g, 'geoms'):
            return [p for sub in g.geoms for p in part(sub)]
        rings = [g.exterior, *g.interiors] if g.geom_type=='Polygon' else [g]
        paths = []
        for ring in rings:
            ps = [xy(x, y) for x, y, *_ in ring.coords]
            coordinates += len(ps)
            if coordinates>250_000 or not all(math.isfinite(v) for p in ps for v in p):
                raise ValueError('Finite bounded projected coordinates required')
            if g.geom_type=='Point':
                paths.append({'point': ps[0]})
            else:
                d = 'M'+' L'.join(f'{x:.3f},{y:.3f}' for x, y in ps)
                paths.append({'path': d+(' Z' if g.geom_type=='Polygon' else '')})
        if g.geom_type=='Polygon':
            return [{'path': ' '.join(p['path'] for p in paths), 'polygon': True}]
        return paths
    for ordinal, feature in enumerate(collection['features']):
        g = shape(feature['geometry'])
        if g.is_empty:
            continue
        if not g.is_valid or not all(math.isfinite(v) for v in g.bounds):
            raise ValueError('Valid finite source geometry required')
        if crs=='EPSG:4326' and not (-180<=g.bounds[0]<=g.bounds[2]<=180 and -85<=g.bounds[1]<=g.bounds[3]<=85):
            raise ValueError('WGS84 coordinates out of range')
        mapped = transform(projector.transform, g)
        if not mapped.is_valid:
            raise ValueError('Invalid projected layer geometry')
        clipped = mapped.intersection(boundary)
        if not clipped.is_empty:
            result.append({'id': str(feature.get('id', ordinal)), 'parts': part(clipped),
                           'properties': feature.get('properties', {})})
    return result


def cloud_features(path, extent, size):
    """Bounded displayed sample of observed native BNG returns, without meshing."""
    import laspy
    from .point_cloud import is_bng
    from pyproj.transformer import TransformerGroup
    group = TransformerGroup(27700, 3857, always_xy=True, allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
        raise ValueError('Best metre-scale datum transform required for raw returns')
    points = []
    eligible_count = 0
    total = 0
    with laspy.open(path) as reader:
        if not is_bng(reader.header.parse_crs()) or reader.header.point_count>15_000_000:
            raise ValueError('Bounded native BNG point crop required')
        stride = max(1, math.ceil(reader.header.point_count/20_000))
        for chunk in reader.chunk_iterator(250_000):
            x, y = group.transformers[0].transform(np.asarray(chunk.x), np.asarray(chunk.y))
            z = np.asarray(chunk.z)
            eligible = (~np.asarray(chunk.withheld, dtype=bool))&(~np.asarray(chunk.synthetic, dtype=bool))
            mask = eligible&np.isfinite(x)&np.isfinite(y)&np.isfinite(z)&(x>=extent[0])&(x<=extent[2])&(y>=extent[1])&(y<=extent[3])
            eligible_count += int(mask.sum())
            mask &= (np.arange(len(chunk))+total)%stride==0
            total += len(chunk)
            for px, py, pz, label in zip(x[mask], y[mask], z[mask], np.asarray(chunk.classification)[mask]):
                points.append([float(px), float(py), float(pz), int(label)])
        if total!=reader.header.point_count:
            raise ValueError('Truncated raw point crop')
    selected = points
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': i, 'geometry': {'type': 'Point', 'coordinates': p[:2]},
         'properties': {'z_odn_m': p[2], 'source_classification': p[3]}} for i, p in enumerate(selected)]}
    # Point layer has its own bounded display budget, separately from vector polygons.
    displayed = []
    for f in fc['features']:
        x, y = f['geometry']['coordinates']
        displayed.append({'id': str(f['id']), 'parts': [{'point': [(x-extent[0])/(extent[2]-extent[0])*size[0],
            (extent[3]-y)/(extent[3]-extent[1])*size[1]]}], 'properties': f['properties']})
    return displayed, {'scanned_points': total, 'eligible_points_in_view': eligible_count,
                       'displayed_points': len(selected), 'decimation': 'deterministic source-wide stride, at most 20000 points',
                       'transform_accuracy_m': group.transformers[0].accuracy}


def _row(identity, family, title=None, **extra):
    name, color, url, limitation = FAMILIES[family]
    return {'id': identity, 'family': family, 'title': title or name, 'color': color,
            'source_url': url, 'limitation': limitation, 'status': 'not_loaded', 'features': [],
            'registration_verified': False, 'training_eligible': False, **extra}


def build(config, output, cache, *, base='.', cancelled=lambda: False, progress=lambda value: None):
    validate(config)
    out = Path(output)
    if out.exists():
        raise ValueError('Fresh mapping comparison output required')
    out.mkdir(parents=True)
    if config.get('datum_grid_file'):
        from pyproj import datadir
        grid = _asset(base, config, 'datum_grid_file')
        datadir.append_data_dir(str(grid.parent))
    reader = sources.Reader(cache, config.get('offline', False), cancelled)
    layers_imported = []
    for item in config.get('imports', []):
        path = _asset(base, item, 'path')
        if path.stat().st_size>512_000_000:
            raise ValueError('Local mapping layer byte budget exceeded')
        retained = out/'imports'/(_id(item['id'])+'.'+item['format'])
        retained.parent.mkdir(exist_ok=True)
        shutil.copy2(path, retained)
        layers_imported.append((item, path, _read(path) if item['format']=='geojson' else None))
    areas = []
    for index, area in enumerate(config['areas']):
        if cancelled():
            raise CancelledError('Mapping comparison cancelled')
        image_path = _asset(base, area, 'image_file')
        if image_path.stat().st_size>16_000_000:
            raise ValueError('Bounded reference image bytes required')
        receipt_path = _asset(base, area, 'receipt_file')
        receipt = _read(receipt_path)
        extent = receipt['extent_epsg3857']
        if len(extent)!=4 or not all(math.isfinite(v) for v in extent) or extent[0]>=extent[2] or extent[1]>=extent[3]:
            raise ValueError('Finite aerial extent required')
        with Image.open(image_path) as image:
            if image.width*image.height>1_048_576 or image.size!=(receipt['width'], receipt['height']) or receipt['image_sha256']!=file_hash(image_path):
                raise ValueError('Reference image receipt dimensions or hash differ')
            size = image.size
            reference = image_uri(image.convert('RGB'))
        bounds = list(Transformer.from_crs(3857, 4326, always_xy=True).transform_bounds(*extent))
        if bounds[2]-bounds[0]>.02 or bounds[3]-bounds[1]>.02:
            raise ValueError('Small mapping comparison extent required')
        folder = out/area['id']
        folder.mkdir()
        shutil.copy2(image_path, folder/'reference.bin')
        shutil.copy2(receipt_path, folder/'reference-receipt.json')
        rows = []
        for key, title in [('ground_mask_file', 'Current draft ground labels'), ('canopy_mask_file', 'Current draft canopy labels')]:
            if not area.get(key):
                continue
            if area.get('label_source_image_sha256')!=receipt['image_sha256']:
                raise ValueError('Draft label image differs from comparison reference')
            label_path = _asset(base, area, key)
            with Image.open(label_path) as label_image:
                labels = np.array(label_image)
            allowed = [0, 1, 2, 3, 255] if key=='ground_mask_file' else [0, 1, 255]
            if labels.shape!=(size[1], size[0]) or not np.isin(labels, allowed).all():
                raise ValueError('Draft labels must use the pinned reference grid and class legend')
            rgba = np.zeros((*labels.shape, 4), np.uint8)
            colors = [(35, 160, 255), (235, 65, 85), (65, 200, 80), (35, 65, 240)] if key=='ground_mask_file' else [(40, 170, 160), (245, 180, 45)]
            for value, color in enumerate(colors):
                rgba[labels==value] = [*color, 180]
            rows.append(_row(key, 'draft_labels', title, status='ready', image=image_uri(Image.fromarray(rgba)),
                source_file_sha256=file_hash(label_path), metadata={'source_image_sha256': receipt['image_sha256'],
                'legend': ['paving', 'structure', 'grass', 'water', '255 unknown'] if key=='ground_mask_file' else ['non-canopy', 'canopy', '255 unknown'],
                'independently_reviewed': False}))
        if area.get('lidar_features_file'):
            field_path = _asset(base, area, 'lidar_features_file')
            field_receipt = _read(_asset(base, area, 'lidar_receipt_file'))
            if field_path.stat().st_size>32_000_000 or field_receipt['image_sha256']!=receipt['image_sha256'] or field_receipt['features_sha256']!=file_hash(field_path):
                raise ValueError('LiDAR context source differs from reference image')
            with np.load(field_path, allow_pickle=False) as archive:
                fields = archive['features']
            if fields.shape!=(size[1], size[0], 4) or not np.isfinite(fields).all() or fields.min()<0 or fields.max()>1:
                raise ValueError('Bounded aligned four-channel LiDAR context required')
            for channel, title in enumerate(('Height above terrain / 30 m', 'Terrain slope / 90 degrees', 'Surface roughness / 5 m', 'Valid LiDAR neighborhoods')):
                value = fields[:, :, channel]
                rgba = np.zeros((*value.shape, 4), np.uint8)
                rgba[:, :, 0] = (value*255).astype(np.uint8)
                rgba[:, :, 1] = (np.maximum(0, 1-abs(value-.5)*2)*230).astype(np.uint8)
                rgba[:, :, 2] = ((1-value)*255).astype(np.uint8)
                rgba[:, :, 3] = np.where(fields[:, :, 3]>0, 210, 0).astype(np.uint8)
                if channel==3:
                    rgba[:, :, :3] = np.where(value[:, :, None]>0, [55, 180, 105], [150, 150, 150])
                    rgba[:, :, 3] = 180
                rows.append(_row('lidar-context-'+str(channel), 'lidar_context', title, status='ready',
                    image=image_uri(Image.fromarray(rgba)), metadata=field_receipt, source_file_sha256=file_hash(field_path)))
        for family, endpoint in [('os_openmap', sources.OPENMAP), *[('historic', url) for url in sources.HISTORIC_LAYERS.values()]]:
            if family not in config.get('providers', []):
                continue
            identity = family+('-vertical' if 'Verticals' in endpoint else '-oblique') if family=='historic' else family
            row = _row(identity, family, title=('Historic England vertical photo locations' if 'Verticals' in endpoint else 'Historic England oblique photo locations') if family=='historic' else None)
            try:
                fc, metadata = sources.feature_layer(reader, endpoint, bounds)
                atomic_json(folder/(identity+'.geojson'), fc)
                row.update(features=project_features(fc, 'EPSG:4326', extent, size), metadata=metadata,
                           source_url=endpoint, status='ready' if fc['features'] else 'empty_selection',
                           source_file=identity+'.geojson', source_file_sha256=file_hash(folder/(identity+'.geojson')))
                if not row['features'] and fc['features']:
                    row['status'] = 'no_features_in_view'
            except ValueError as error:
                row.update(status='unavailable', reason=str(error))
            rows.append(row)
        for release in config.get('wayback_releases', []) if 'wayback' in config.get('providers', []) else []:
            row = _row('wayback-'+release, 'wayback')
            try:
                im, metadata = sources.wayback(reader, release, extent, size)
                im.save(folder/(row['id']+'.png'))
                row.update(title=metadata['itemTitle'], image=image_uri(im), metadata=metadata, status='ready',
                           source_file=row['id']+'.png', source_file_sha256=file_hash(folder/(row['id']+'.png')))
            except ValueError as error:
                row.update(status='unavailable', reason=str(error))
            rows.append(row)
        if 'overture' in config.get('providers', []):
            row = _row('overture', 'overture')
            try:
                fc, metadata = sources.overture(reader, bounds, folder/'overture')
                row.update(metadata=metadata, status=metadata['status'], features=project_features(fc, 'EPSG:4326', extent, size))
                if row['features']:
                    row['status'] = 'ready'
                else:
                    row['reason'] = 'No complete features returned; see retained discovery failures.'
            except ValueError as error:
                row.update(status='unavailable', reason=str(error))
            rows.append(row)
        for item, path, fc in layers_imported:
            if item.get('areas') and area['id'] not in item['areas']:
                continue
            row = _row('import-'+item['id'], item['family'], item.get('title'), metadata=item['metadata'],
                       source_url=item['metadata']['source_url'], source_file_sha256=item['path_sha256'],
                       source_file='imports/'+item['id']+'.'+item['format'])
            if item['format']=='las':
                row['features'], stats = cloud_features(path, extent, size)
                row['metadata'] = {**row['metadata'], **stats}
            else:
                row['features'] = project_features(fc, item.get('crs'), extent, size)
            row['status'] = 'ready' if row['features'] else 'no_features_in_view'
            rows.append(row)
        for family in FAMILIES:
            if not any(r['family']==family for r in rows):
                rows.append(_row(family+'-gap', family, status='local_import_required',
                    reason='No aligned local data supplied. Open the source or add a pinned import.'))
        areas.append({'id': area['id'], 'title': area.get('title', area['id']), 'size': size,
                      'extent_epsg3857': extent, 'reference': reference, 'reference_receipt': receipt, 'layers': rows})
        progress((index+1)/len(config['areas']))
    data = {'version': VERSION, 'site': config['site'], 'created_utc': datetime.now(timezone.utc).isoformat(),
            'areas': areas, 'sources': reader.sources, 'network_bytes': reader.budget.spent,
            'network_byte_scope': 'Public feature/tile reader only; Overture SDK requests have separate bounds and are not counted here.',
            'world_blocks_generated': 0, 'training_labels_added': 0, 'models_retrained': False,
            'registration_policy': 'CRS alignment only; no source is automatically warped to agree with another.'}
    atomic_json(out/'layers.json', data)
    atomic_json(out/'config.json', config)
    page = Path(__file__).with_name('mapping_layers.html').read_text()
    (out/'index.html').write_text(page.replace('__DATA__', json.dumps(data, allow_nan=False).replace('<', '\\u003c')), encoding='utf-8')
    summary = {k: v for k, v in data.items() if k!='areas'}
    summary['areas'] = [{'id': a['id'], 'layers': [{k: v for k, v in row.items() if k not in ('features', 'image')}
        | {'visible_features': len(row['features'])} for row in a['layers']]} for a in areas]
    atomic_json(out/'report.json', summary)
    return summary


def run(config, output, cache, *, base='.', cancelled=lambda: False, progress=lambda value: None):
    return build(config, output, cache, base=base, cancelled=cancelled, progress=progress)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'output', 'cache'):
        p.add_argument('--'+name, required=True)
    args = p.parse_args(argv)
    path = Path(args.config).resolve()
    report = run(_read(path), args.output, args.cache, base=path.parent)
    print(json.dumps({'areas': len(report['areas']), 'network_bytes': report['network_bytes'], 'output': args.output}))


if __name__=='__main__':
    main()
