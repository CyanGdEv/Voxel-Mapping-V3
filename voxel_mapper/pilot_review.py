"""Opt-in provisional study meshes on terrain; never accepted planning geometry."""
import json
import math

from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import transform

from .horizontal_grid import OSTN15Transform
from .reconstruction.local_buildings import rotate_model
from .shop_foundations import level_pad
from .shop_slabs import assemble
from .shop_wall_details import decorate
from .terrain import Terrain

VERSION = 'provisional-study-component-v1'


def prepare(settings, asset, load_json, directory, pins):
    if not isinstance(settings, dict) or settings.get('policy') != 'estimated_review_only':
        raise ValueError('Explicit estimated_review_only component policy required')
    model_path = asset(settings.get('model'), directory, 'review_model')
    placement_path = asset(settings.get('placement'), directory, 'review_placement')
    model, placement = load_json(model_path), load_json(placement_path)
    if model.get('world_placement_eligible') is not False:
        raise ValueError('Review model must retain its explicitly unaccepted placement status')
    evidence = settings.get('evidence', [])
    originals = settings.get('original_pdfs', [])
    if (not isinstance(evidence, list) or not 1 <= len(evidence) <= 32
            or not isinstance(originals, list) or not 1 <= len(originals) <= 16):
        raise ValueError('Bounded pinned original PDFs and study evidence required')
    parents = []
    for index, descriptor in enumerate(evidence):
        path = asset(descriptor, directory, 'review_evidence:' + str(index))
        parents.append(load_json(path))
    pdf_hashes = set()
    for index, descriptor in enumerate(originals):
        path = asset(descriptor, directory, 'review_original:' + str(index))
        if path.stat().st_size > 64_000_000:
            raise ValueError('Review original PDF byte budget exceeded')
        with path.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('Original PDF header required')
        pdf_hashes.add(descriptor['sha256'])
    expected = set(model.get('input_sha256', {}).values()) | set(model.get('vertical_input_sha256', {}).values())
    if model.get('projection_input_wall_sha256'):
        expected.add(model['projection_input_wall_sha256'])
    if not expected or not expected.issubset({digest for _, digest in pins}):
        raise ValueError('Study model parent evidence is missing or changed')
    references = {parent[key] for parent in parents for key in ('floor_sha256', 'roof_plan_sha256', 'source_sha256')
                  if isinstance(parent.get(key), str)}
    if not references or not references.issubset(pdf_hashes):
        raise ValueError('Study source PDF references are not retained originals')
    if (placement.get('estimated') is not True or placement.get('production_placement_eligible') is not False
            or not isinstance(placement.get('id'), str) or not placement['id']
            or not isinstance(placement.get('basis'), str) or not placement['basis'].strip()):
        raise ValueError('Explicitly estimated placement identity and basis required')
    anchor = placement.get('anchor_bng_m')
    angle, floor = placement.get('rotation_bng_degrees'), placement.get('floor_elevation_m')
    alternatives = placement.get('orientation_alternatives_bng_degrees')
    if (not isinstance(anchor, list) or len(anchor) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in anchor)
            or type(angle) not in (int, float) or not math.isfinite(angle) or abs(angle) > 360
            or type(floor) not in (int, float) or not math.isfinite(floor) or abs(floor) > 10000
            or not isinstance(alternatives, list) or not 1 <= len(alternatives) <= 16
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 360 for v in alternatives)
            or angle not in alternatives):
        raise ValueError('Bounded finite placement and retained orientation alternatives required')
    for key in ('wall_mesh', 'roof_mesh', 'projection_mesh'):
        if key not in model:
            continue
        vertices = model[key].get('vertices')
        if (not isinstance(vertices, list) or not 1 <= len(vertices) <= 10000
                or any(not isinstance(v, list) or len(v) != 3 or
                       any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in vertices)):
            raise ValueError('Bounded finite review mesh required')
        extents = [max(v[i] for v in vertices) - min(v[i] for v in vertices) for i in range(3)]
        if math.prod(math.ceil(2 * extent) + 3 for extent in extents) > 2_000_000:
            raise ValueError('Review mesh sampling extent exceeds budget')
    return {'model': model, 'placement': placement, 'original_pdf_sha256': sorted(pdf_hashes),
            'model_sha256': settings['model']['sha256'], 'placement_sha256': settings['placement']['sha256']}


def append_component(component, config, quality, output):
    placement, model = component['placement'], component['model']
    if placement.get('vertical_datum') != config['terrain']['vertical_datum']:
        raise ValueError('Explicit review floor must use the terrain vertical datum')
    operation = config['terrain'].get('horizontal_operation')
    if not operation:
        raise ValueError('Review placement requires the pinned OSTN15 operation')
    local_crs = CRS.from_wkt(quality['crs'])
    coordinate = OSTN15Transform(local_crs, 27700, operation)
    anchor_bng = placement['anchor_bng_m']
    anchor = coordinate.inverse(*anchor_bng)
    angle = math.radians(placement['rotation_bng_degrees'])
    direction = coordinate.inverse(anchor_bng[0] + math.cos(angle), anchor_bng[1] + math.sin(angle))
    vector = [direction[i] - anchor[i] for i in (0, 1)]
    tangent_scale = math.hypot(*vector)
    if abs(tangent_scale - 1) > .002:
        raise ValueError('Review local tangent scale differs excessively from one metre')
    local_angle = math.degrees(math.atan2(vector[1], vector[0]))
    rotated = rotate_model(model, local_angle)
    cells, native = assemble(rotated)
    cells, decorations = decorate(rotated, cells)
    for position, material in list(cells.items()):
        if material.endswith('_trapdoor_north'):
            cells[position] = material.removesuffix('_north') + '_south'
        elif material.endswith('_trapdoor_south'):
            cells[position] = material.removesuffix('_south') + '_north'
    terrain = Terrain(config['terrain'], local_crs, {s['id']: s for s in config['sources']})
    base = placement['floor_elevation_m']
    try:
        for x, y, z in cells:
            ground = terrain.sample(x + round(anchor[0]) + .5, z + round(anchor[1]) + .5)
            if ground is None or y + round(base) <= math.floor(ground):
                raise ValueError('Provisional component intersects terrain or lacks coverage; no excavation inferred')
        foundations, grounding = level_pad(rotated, cells, anchor, base, terrain.sample)
    finally:
        terrain.close()
    combined = {**foundations, **cells}
    if quality['voxel_records'] + len(combined) > config['max_voxels']:
        raise ValueError('Review component exceeds pilot voxel budget')
    west, south, east, north = config['bbox']
    projector = Transformer.from_crs(4326, local_crs, always_xy=True)
    domain = transform(projector.transform, box(west, south, east, north))
    if config.get('boundary_geojson') and config.get('clip_to_boundary', True):
        domain = domain.intersection(transform(projector.transform, shape(config['boundary_geojson'])))
    if any(not domain.covers(Point(x + round(anchor[0]) + .5, z + round(anchor[1]) + .5)) for x, _, z in combined):
        raise ValueError('Review component extends beyond pilot bounds')
    identifier = 'review/' + placement['id']
    with (output / 'voxels.jsonl').open('a', encoding='utf-8') as stream:
        for (x, y, z), material in sorted(combined.items()):
            stream.write(json.dumps({'x': x + round(anchor[0]), 'y': y + round(base), 'z': z + round(anchor[1]),
                'kind': 'building', 'feature': identifier, 'source': 'provisional-study-model', 'material': material,
                'material_origin': 'estimated_reconstruction_shell', 'accepted_physical_geometry': False}) + '\n')
    footprint = Polygon([(v[0] + round(anchor[0]), v[1] + round(anchor[1])) for v in rotated['outer_wall_base_outline']])
    feature_path = output / 'features-local.geojson'
    features = json.loads(feature_path.read_text())
    features['features'].append({'type': 'Feature', 'id': identifier, 'geometry': mapping(footprint),
        'properties': {'review_only': True, 'accepted_physical_geometry': False,
                       'source': 'Previously reviewed study mesh; not automatic complete PDF reconstruction.'}})
    feature_path.write_text(json.dumps(features, indent=2) + '\n', encoding='utf-8')
    quality['voxel_records'] += len(combined)
    from .cli import file_sha256
    quality['sha256'] = file_sha256(output / 'voxels.jsonl')
    report = {'version': VERSION, 'status': 'estimated_component_review_only', 'feature_id': identifier,
        'model_sha256': component['model_sha256'], 'placement_sha256': component['placement_sha256'],
        'original_pdf_sha256': component['original_pdf_sha256'], 'placement_basis': placement['basis'],
        'rotation_bng_degrees': placement['rotation_bng_degrees'], 'rotation_local_degrees': local_angle,
        'retained_orientation_alternatives_bng_degrees': placement['orientation_alternatives_bng_degrees'],
        'anchor_bng_m': anchor_bng, 'anchor_local_m': list(anchor),
        'anchor_snap_offsets_m': [round(v) - v for v in anchor], 'local_tangent_scale': tangent_scale,
        'floor_elevation_m': base, 'floor_snap_offset_m': round(base) - base,
        'floor_datum_verified': False, 'source_geometry_cells': len(cells), 'foundation_cells': len(foundations),
        'emitted_review_voxel_records': len(combined), 'grounding': grounding, 'native_mesh_audit': native,
        'accepted_controls': 0, 'accepted_checkpoints': 0, 'world_placement_eligible': False,
        'accepted_park_world_blocks_added': 0, 'training_labels_generated': 0,
        'limitations': ['Model reuses an existing manual study; no new trained model or complete drawing interpretation.',
                       'Orientation, assembly identity, base floor, materials and foundations are estimates.',
                       'A local tangent rotates before voxelization; no source dimensions are stretched.',
                       'Terrain is not excavated. This world is for visual review, not accepted park placement.']}
    (output / 'review-component.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    quality['review_component'] = report
    quality['spawn_local_xyz_m'] = [round(anchor[0]) - 18, round(base) + 3, round(anchor[1]) - 18]
    return report
