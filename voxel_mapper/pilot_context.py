"""Bounded mapped woodland proxies outside a retained review-world core."""
import copy
import json
from pathlib import Path
import shutil

from pyproj import CRS, Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

VERSION = 'mapped-woodland-buffer-v1'


def prepare(settings, asset, load_json, directory, config):
    if not isinstance(settings, dict) or settings.get('policy') != VERSION:
        raise ValueError('Explicit mapped woodland buffer policy required')
    sources = {source['id']: source for source in config['sources']}
    if sources.get(settings.get('osm_source_id'), {}).get('kind') != 'osm':
        raise ValueError('Registered OSM context source required')
    surface_source = settings.get('surface_source_id')
    if sources.get(surface_source, {}).get('kind') != 'surface':
        raise ValueError('Registered surface context source required')
    core = load_json(asset(settings.get('core_config'), directory, 'context_core_config'))
    from .cli import validate_config
    west, south, east, north, resolution = validate_config(core)
    if resolution != 1:
        raise ValueError('Context core must retain one-metre resolution')
    origin = core.get('local_origin_wgs84', [(west + east) / 2, (south + north) / 2])
    if config.get('local_origin_wgs84') != origin:
        raise ValueError('Context must pin the original core coordinate origin')
    if not box(*config['bbox']).covers(box(*core['bbox'])):
        raise ValueError('Context bounds must cover the retained core')
    if core.get('terrain', {}).get('vertical_datum') != config['terrain']['vertical_datum']:
        raise ValueError('Context must retain the core vertical datum')
    maximum_trees, maximum_cells = settings.get('max_trees', 64), settings.get('max_cells', 100_000)
    if (type(maximum_trees) is not int or not 1 <= maximum_trees <= 128
            or type(maximum_cells) is not int or not 1 <= maximum_cells <= 100_000):
        raise ValueError('Bounded context tree/cell budgets required')
    raw_path = asset(settings.get('raw_osm'), directory, 'context_raw_osm')
    raw = load_json(raw_path)
    if (not isinstance(raw.get('elements'), list) or len(raw['elements']) > 100_000
            or raw.get('remark')):
        raise ValueError('Complete bounded raw OSM context required')
    surface_path = asset(settings.get('surface'), directory, 'context_surface')
    return {'core_bbox': core['bbox'], 'raw_osm': raw_path, 'surface_path': surface_path,
            'surface_source_id': surface_source, 'osm_source_id': settings['osm_source_id'],
            'max_trees': maximum_trees, 'max_cells': maximum_cells}


def append(output, quality, config, prepared, walking_mask=None):
    """Reuse the foliage generator against a temporary native occupancy snapshot."""
    from .bedrock import export_world
    from .park_foliage import reconstruct
    from .cli import file_sha256

    output = Path(output)
    scratch = output / '.context-snapshot'
    scratch.mkdir()
    try:
        crs = CRS.from_wkt(quality['crs'])
        project = Transformer.from_crs(4326, crs, always_xy=True).transform
        domain = transform(project, box(*config['bbox']))
        if config.get('boundary_geojson') and config.get('clip_to_boundary', True):
            domain = domain.intersection(transform(project, shape(config['boundary_geojson'])))
        core = transform(project, box(*prepared['core_bbox']))
        # Protect whole metre cells touching the original core. No part of any
        # trunk, branch or leaf may occupy a core column.
        boundary = domain.difference(core.buffer(2))
        (scratch / 'boundary.json').write_text(json.dumps(mapping(boundary)))
        raw = json.loads(prepared['raw_osm'].read_text())
        nodes = [{**node, 'id': str(node['id'])} for node in raw['elements']
                 if node.get('type') == 'node' and node.get('tags', {}).get('natural') == 'tree']
        (scratch / 'nodes.json').write_text(json.dumps(nodes))
        snapshot = copy.deepcopy(quality)
        snapshot['world'] = export_world(output / 'voxels.jsonl', scratch, snapshot,
                                         'Temporary vegetation occupancy', max_blocks=4_000_000)
        (scratch / 'quality-report.json').write_text(json.dumps(snapshot))
        (scratch / 'resolved-config.json').write_text(json.dumps(config))
        surface = {'path': str(prepared['surface_path']), 'source_id': prepared['surface_source_id'],
                   'units': 'm', 'vertical_datum': config['terrain']['vertical_datum']}
        rows, report = reconstruct(scratch, prepared['raw_osm'], scratch / 'nodes.json',
            prepared['surface_path'], scratch / 'boundary.json', scratch / 'unused',
            max_trees=prepared['max_trees'], max_cells=prepared['max_cells'],
            collect_only=True, surface_config=surface, additional_path_mask=walking_mask)
        if quality['voxel_records'] + len(rows) > config['max_voxels']:
            raise ValueError('Context exceeds pilot voxel budget')
        for row in rows:
            x, z = row['x'], row['z']
            if not boundary.covers(box(x, z, x + 1, z + 1)):
                raise ValueError('Context geometry extends outside its buffer or into the protected core')
            row.update(source=prepared['osm_source_id'], elevation_source=prepared['surface_source_id'],
                       material_origin='estimated_reconstruction_shell', accepted_physical_geometry=False)
        with (output / 'voxels.jsonl').open('a', encoding='utf-8') as stream:
            for row in sorted(rows, key=lambda r: (r['feature'], r['x'], r['y'], r['z'])):
                stream.write(json.dumps(row) + '\n')
        report.update(version=VERSION, status='estimated_buffer_context', core_bbox=prepared['core_bbox'],
                      core_geometry_modified=False, accepted_physical_geometry=False, training_labels_generated=0,
                      horizontal_operation='Same pinned operation as terrain for both DTM and DSM.',
                      world_name='Mapped woodland buffer context')
        report['sources']['original_osm_xml_sha256'] = raw.get('source_xml_sha256')
        (output / 'context-review.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        quality['voxel_records'] += len(rows)
        quality['sha256'] = file_sha256(output / 'voxels.jsonl')
        quality['context_review'] = report
        return report
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
