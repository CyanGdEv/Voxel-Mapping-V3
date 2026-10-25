"""Source-local plan previews in Bedrock; footprint markers never imply heights.

This export deliberately carries the planning layout's unresolved interpretation
into an explorable, flat map. It does not promote a proposal into park geometry.
"""
from collections import deque
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

from shapely.geometry import Point, shape

from .generation_cycles import atomic_json
from . import paving_palette

VERSION = 'planning-area-world-preview-v1'
MAX_LAYOUT_BYTES = 16_000_000
MAX_CANDIDATES = 128
MAX_SPAN_M = 128
MAX_PLATFORM_CELLS = 16_384
MAX_WORLD_BLOCKS = 100_000
MAX_GRID_CHECKS = 262_144
MAX_POINTS = 200_000
DIMENSION = 'minecraft:overworld'
BUILDING_MARKER_MATERIAL = 'yellow_concrete'
SURFACE_ROLES = {'path', 'plaza', 'surface'}


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate(config):
    if (not isinstance(config, dict)
            or set(config) != {'version', 'layout_path', 'layout_sha256'}
            or config.get('version') != VERSION
            or not isinstance(config.get('layout_path'), str) or not config['layout_path']
            or len(config['layout_path']) > 4096
            or not re.fullmatch('[0-9a-f]{64}', str(config.get('layout_sha256')))):
        raise ValueError('Versioned pinned source-local area layout required')
    return config


def _read_layout(config):
    from . import planning_area_layout
    path = Path(config['layout_path'])
    if not path.is_file() or path.stat().st_size > MAX_LAYOUT_BYTES:
        raise ValueError('Bounded existing source-local area layout required')
    data = path.read_bytes()
    if len(data) > MAX_LAYOUT_BYTES or hashlib.sha256(data).hexdigest() != config['layout_sha256']:
        raise ValueError('Source-local area layout changed')
    def invalid(value):
        raise ValueError('Nonfinite layout value: '+value)
    layout = json.loads(data.decode('utf-8'), parse_constant=invalid)
    planning_area_layout.validate_layout(layout)
    if (layout.get('analysis_complete') is not True or not layout.get('shared_frame')
            or not isinstance(layout.get('candidates'), list)
            or not 1 <= len(layout['candidates']) <= MAX_CANDIDATES
            or layout.get('world_placement_eligible') is not False):
        raise ValueError('Complete nonempty source-local layout required')
    return layout


def _grid_connectivity(cells, features):
    """Four-neighbour membership only, explicitly not physical route validation."""
    remaining = set(cells)
    groups = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        pending = deque([start])
        count = 0
        low = list(start)
        high = list(start)
        owners = set()
        while pending:
            x, z = pending.popleft()
            count += 1
            owners.update(features.get((x, z), ()))
            low = [min(low[0], x), min(low[1], z)]
            high = [max(high[0], x), max(high[1], z)]
            for neighbour in ((x-1, z), (x+1, z), (x, z-1), (x, z+1)):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    pending.append(neighbour)
        groups.append({'cells': count, 'bounds_xz': [low, high],
            'candidate_ids': sorted(owners)})
    groups.sort(key=lambda row: tuple(row['bounds_xz'][0]))
    return {'status': 'flat_display_paving_grid_assessed', 'adjacency': 'four_neighbour',
        'components': groups, 'component_count': len(groups), 'paving_cells': len(cells),
        'all_display_paving_connected': len(groups) == 1 if cells else None,
        'physical_traversability_verified': False, 'entrances_verified': False,
        'finished_levels_verified': False, 'player_movement_verified': False}


def _rasterize(layout, cancelled):
    """Centre sample unchanged polygons; no buffering, snapping or gap filling."""
    def check():
        if cancelled():
            raise CancelledError('Area plan preview cancelled')
    candidates = layout['candidates']
    shapes = []
    points = checks = 0
    for row in candidates:
        check()
        if row.get('role') not in SURFACE_ROLES | {'building'} or row.get('height_m') is not None:
            raise ValueError('Supported footprint roles with unresolved heights required')
        geometry = shape(row['geometry_nominal_local'])
        if (geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty
                or not geometry.is_valid or geometry.has_z
                or not all(math.isfinite(value) and abs(value) <= 10000 for value in geometry.bounds)):
            raise ValueError('Finite bounded valid area polygons required')
        polygons = [geometry] if geometry.geom_type == 'Polygon' else geometry.geoms
        points += sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
            for p in polygons)
        lowx, lowz, highx, highz = geometry.bounds
        checks += (math.ceil(highx)-math.floor(lowx))*(math.ceil(highz)-math.floor(lowz))
        if points > MAX_POINTS or checks > MAX_GRID_CHECKS:
            raise ValueError('Area preview source point or sampling work budget exceeded')
        surface = (None if row['role'] == 'building' else
            paving_palette.material_label(row.get('surface') or 'stone'))
        if row['role'] != 'building' and surface is None:
            raise ValueError('Supported explicit paving palette required')
        shapes.append((row, geometry, surface))
    minx = math.floor(min(geometry.bounds[0] for _, geometry, _ in shapes))-4
    minz = math.floor(min(geometry.bounds[1] for _, geometry, _ in shapes))-4
    maxx = math.ceil(max(geometry.bounds[2] for _, geometry, _ in shapes))+4
    maxz = math.ceil(max(geometry.bounds[3] for _, geometry, _ in shapes))+4
    if maxx-minx > MAX_SPAN_M or maxz-minz > MAX_SPAN_M or (maxx-minx)*(maxz-minz) > MAX_PLATFORM_CELLS:
        raise ValueError('Flat area display platform exceeds 128 by 128 metre budget')
    # Avoid using composition order to choose a building, a paving role, or one
    # of two inconsistent surface finishes. Matching paving may share a tile.
    for i, (first, geometry, surface) in enumerate(shapes):
        check()
        for second, other, other_surface in shapes[i+1:]:
            if (geometry.intersection(other).area > 1e-9
                    and ('building' in (first['role'], second['role']) or surface != other_surface)):
                raise ValueError('Conflicting area footprint overlap requires interpretation')
    materials = {}
    paving = set()
    owners = {}
    counts = []
    for row, geometry, surface in shapes:
        check()
        a, b, c, d = geometry.bounds
        count = 0
        for x in range(math.floor(a), math.ceil(c)):
            check()
            for z in range(math.floor(b), math.ceil(d)):
                if not geometry.covers(Point(x+.5, z+.5)):
                    continue
                key = (x, z)
                material = (BUILDING_MARKER_MATERIAL if row['role'] == 'building'
                    else paving_palette.palette_block(surface, x, z))
                if key in materials and materials[key] != material:
                    raise ValueError('Conflicting source proposals occupy the same preview cell')
                materials[key] = material
                owners.setdefault(key, set()).add(row['id'])
                if row['role'] in SURFACE_ROLES:
                    paving.add(key)
                count += 1
        counts.append({'candidate_id': row['id'], 'role': row['role'], 'display_cells': count,
            'source_nominal_area_m2': geometry.area,
            'submetre_geometry_lost': count == 0,
            'surface': surface, 'display_material': BUILDING_MARKER_MATERIAL if surface is None else None,
            'height_reconstructed': False})
    if not materials:
        raise ValueError('Source polygons contain no one-metre preview cell centres')
    platform_cells = (maxx-minx)*(maxz-minz)
    if 4*platform_cells+len(materials) > MAX_WORLD_BLOCKS:
        raise ValueError('Area preview native write budget exceeded')
    return {'materials': materials, 'paving': paving, 'owners': owners,
        'candidate_counts': counts, 'platform_bounds': [minx, minz, maxx, maxz],
        'sampling_checks': checks, 'source_points': points,
        'grid_connectivity': _grid_connectivity(paving, owners)}


def _saved_grid_check(path, offset, sampled, cancelled):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from .bedrock import material_block
    wrapper = LevelDBFormat(str(path))
    wrapper.open()
    paving = set()
    chunks = {}
    try:
        for (x, depth), material in sorted(sampled['materials'].items()):
            if cancelled():
                raise CancelledError('Area plan preview cancelled')
            # Reflect the whole source cell [depth, depth+1], rather than just
            # its lower index: the Minecraft cell then spans [-depth-1,-depth].
            z = -depth-1
            key = (x//16, z//16)
            if key not in chunks:
                chunks[key] = wrapper.load_chunk(*key, DIMENSION)
            chunk = chunks[key]
            actual = chunk.block_palette[int(chunk.blocks[x%16, offset, z%16])]
            expected = material_block(material)
            if (actual.namespaced_name != expected.namespaced_name
                    or any(actual.properties.get(k) != v for k, v in expected.properties.items())):
                raise ValueError('Saved area display cells differ from source rasterization')
            for y in (offset+1, offset+2):
                if chunk.block_palette[int(chunk.blocks[x%16, y, z%16])].base_name != 'air':
                    raise ValueError('Saved flat area display headroom is occupied')
            if (x, depth) in sampled['paving']:
                paving.add((x, depth))
    finally:
        wrapper.close()
    result = _grid_connectivity(paving, sampled['owners'])
    if result != sampled['grid_connectivity']:
        raise ValueError('Saved paving membership or grid connectivity changed')
    result.update(saved_display_cells_verified=True, saved_display_headroom_verified=True,
        saved_paving_membership_verified=True)
    return result


def run(config, output, *, cancelled=lambda: False, progress=lambda value: None):
    validate(config)
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh area plan preview output required')
    def check():
        if cancelled():
            raise CancelledError('Area plan preview cancelled')
    check()
    layout = _read_layout(config)
    sampled = _rasterize(layout, cancelled)
    check()
    from . import bedrock
    from .planning_world_preview import _spawn_check, _verify_archive
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='planning-area-world-', dir=output.parent) as temporary:
        root = Path(temporary)/'output'
        root.mkdir()
        atomic_json(root/'source-area-layout.json', layout)
        voxel = root/'voxels.jsonl'
        minx, minz, maxx, maxz = sampled['platform_bounds']
        with voxel.open('w', encoding='utf-8', newline='\n') as stream:
            for x in range(minx, maxx):
                check()
                for depth in range(minz, maxz):
                    stream.write(json.dumps({'x': x, 'y': 0, 'z': depth+1,
                        'kind': 'terrain', 'material': 'grass_block'}, sort_keys=True)+'\n')
            for (x, depth), material in sorted(sampled['materials'].items()):
                stream.write(json.dumps({'x': x, 'y': 0, 'z': depth+1,
                    'kind': 'path' if (x, depth) in sampled['paving'] else 'building',
                    'material': material}, sort_keys=True)+'\n')
        progress({'progress': .25, 'message': 'Exporting the flat source-local plan preview'})
        report = {'version': VERSION, 'status': 'source_local_area_plan_preview_exported',
            'voxel_size_m': 1, 'model_blocks_per_source_metre': 1, 'crs': None,
            'vertical_datum': 'STUDY_ZERO', 'geographic_registration': None,
            'source_layout_sha256': config['layout_sha256'], 'source_layout_id': layout['id'],
            'source_document_sha256': layout['document_sha256'], 'source_page': layout['page'],
            'shared_frame': layout['shared_frame'],
            'horizontal_transform': {'minecraft_x': 'source-local nominal plan X',
                'minecraft_z': 'negative source-local nominal plan Y; not surveyed north'},
            'spawn_local_xyz_m': [minx+1, 1, minz+2],
            'platform_bounds_source_local_xy': sampled['platform_bounds'],
            'candidate_display_counts': sampled['candidate_counts'],
            'building_marker_material': BUILDING_MARKER_MATERIAL,
            'source_cell_to_minecraft': {'x': 'floor(source X)',
                'z': '-floor(source Y)-1; reflected source cell interval'},
            'building_marker_height_blocks': 1, 'building_heights_reconstructed': 0,
            'reconstructed_buildings': 0, 'physical_height_verified': False,
            'ground_datum_verified': False, 'finished_levels_verified': False,
            'world_placement_eligible': False, 'park_world_blocks_added': 0,
            'training_labels_generated': 0, 'model_weights_updated': False,
            'limitations': [
                'This is a source-local plan map on artificial flat ground, not a reconstructed area.',
                'Yellow one-cell building footprint markers supply no building height, roof or openings.',
                'Every label and boundary remains an unverified source hypothesis; physical roles may be wrong.',
                'Printed-scale metres are nominal; no surveyed park position or finished ground level is established.',
                'One-metre cell-centre sampling can erase narrow paths, round boundaries or change apparent connections.',
                'Paving without a supported source finish uses the recorded display-stone rule.',
                'Four-neighbour paving membership checks do not establish entrances, physical routes or player movement.',
                'Minecraft import and gameplay have not been tested.'],
            'limits': {'max_candidates': MAX_CANDIDATES, 'max_platform_span_m': MAX_SPAN_M,
                'max_platform_cells': MAX_PLATFORM_CELLS, 'max_world_blocks': MAX_WORLD_BLOCKS,
                'max_sampling_checks': MAX_GRID_CHECKS, 'max_source_points': MAX_POINTS}}
        def saved_check(path, offset, spawn):
            check()
            report['spawn_validation'] = _spawn_check(path, spawn)
            report['saved_grid_paving_connectivity'] = _saved_grid_check(path, offset, sampled, cancelled)
            atomic_json(path/'preview-source-area-layout.json', layout)
            (path/'PREVIEW-README.txt').write_text(
                'Source-local flat plan preview; yellow cells mark building footprints, not heights.\n'
                'Paths and plazas remain unverified boundary hypotheses. One block per nominal source metre.\n'
                'No park alignment, finished levels, building roofs, openings or complete area reconstruction.\n', encoding='utf-8')
        world = bedrock.export_world(voxel, root, report,
            name='Source-local area plan (footprint markers)', max_blocks=MAX_WORLD_BLOCKS,
            ground_depth=3, post_export_check=saved_check)
        check()
        archive = _verify_archive(root/world['file'], root/'bedrock-world', world, cancelled)
        filename = 'area-plan.mcworld'
        shutil.move(root/world['file'], root/filename)
        world = {**world, 'file': filename}
        report.update(world=world, file=filename, archive_validation=archive,
            preview_worlds_exported=1, worlds=[{'file': filename, 'world': world,
                'audit_file': 'quality-report.json', 'reconstructed_buildings': 0}])
        shutil.rmtree(root/'bedrock-world')
        _write_index(root, report)
        # Source changes while the potentially expensive native export runs do
        # not silently authorize a stale or different review at publication.
        if _sha(config['layout_path']) != config['layout_sha256']:
            raise ValueError('Source-local area layout changed during world export')
        report['output_sha256'] = {p.relative_to(root).as_posix(): _sha(p)
            for p in sorted(root.rglob('*')) if p.is_file()}
        atomic_json(root/'quality-report.json', report)
        check()
        if output.exists():
            raise ValueError('Fresh area plan preview output required')
        root.rename(output)
    progress({'progress': 1., 'message': 'Source-local plan preview download ready'})
    return report


def _write_index(root, report):
    counts = report['candidate_display_counts']
    buildings = sum(row['role'] == 'building' for row in counts)
    surfaces = sum(row['role'] in SURFACE_ROLES for row in counts)
    empty = sum(row['display_cells'] == 0 for row in counts)
    components = report['saved_grid_paving_connectivity']['component_count']
    body = ['<!doctype html><html lang="en"><meta charset="utf-8">',
        '<title>Source-local plan preview</title><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<style>body{font:17px system-ui;max-width:950px;margin:2rem auto;padding:0 1rem;line-height:1.5}a{color:#17549b}</style>',
        '<h1>Download the source-local plan preview</h1>',
        '<p>This flat map shows the relative positions of planning-boundary hypotheses. Yellow building footprint markers '
        'have no reconstructed height, roof or openings. It has no surveyed park placement or recovered ground levels.</p>',
        '<p><a download href="area-plan.mcworld">Download area-plan.mcworld</a> and open it with Minecraft Bedrock. '
        'The target format is Bedrock 1.21.130. Import and gameplay have not been tested.</p>',
        '<p>'+str(buildings)+' building footprint proposals; '+str(surfaces)+' path/plaza/surface proposals. '
        +str(empty)+' proposals contain no one-metre sample centres. The saved paving grid has '
        +str(components)+' four-neighbour components; this does not certify physical access.</p>',
        '<p>All candidates share one nominal source scale and frame. Shapes are sampled without snapping, widening or joining. '
        'This map is an intermediate inspection output, not a completed area reconstruction.</p>',
        '<p><a href="source-area-layout.json">Source layout and evidence</a> · '
        '<a href="quality-report.json">Saved-world checks</a> · <a href="voxels.jsonl">Cell intents</a></p></html>']
    (root/'index.html').write_text(''.join(body), encoding='utf-8')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Export a source-local flat planning map as a Bedrock world')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args(argv)
    path = Path(arguments.config).resolve()
    if path.stat().st_size > 16384:
        raise ValueError('Area preview request byte budget exceeded')
    config = json.loads(path.read_text(encoding='utf-8'))
    validate(config)
    config = {**config, 'layout_path': str((path.parent/config['layout_path']).resolve())}
    report = run(config, arguments.output)
    print(json.dumps({'status': report['status'], 'file': report['file']}, sort_keys=True))


if __name__ == '__main__':
    main()
