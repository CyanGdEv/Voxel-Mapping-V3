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

VERSION = 'planning-area-world-preview-v2'
LEGACY_VERSION = 'planning-area-world-preview-v1'
MAX_LAYOUT_BYTES = 16_000_000
MAX_CANDIDATES = 128
MAX_SPAN_M = 128
MAX_PLATFORM_CELLS = 16_384
MAX_TILES = 4
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
    if isinstance(config,dict) and config.get('version')=='planning-geometry-world-preview-v1':
        from .planning_geometry_world import validate as validate_geometry
        return validate_geometry(config)
    if (not isinstance(config, dict)
            or set(config) != {'version', 'layout_path', 'layout_sha256'}
            or config.get('version') not in (LEGACY_VERSION, VERSION)
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


def _platform_tiles(bounds, version):
    """Half-open integer sections cover the entire platform, without overlap.

    Per-section bounds are unchanged; the global write ceiling bounds their
    combined area, including three foundation layers. No feature is cropped.
    """
    minx, minz, maxx, maxz = bounds
    cells = (maxx-minx)*(maxz-minz)
    if version == LEGACY_VERSION:
        if maxx-minx > MAX_SPAN_M or maxz-minz > MAX_SPAN_M or cells > MAX_PLATFORM_CELLS:
            raise ValueError('Flat area display platform exceeds 128 by 128 metre budget')
    elif version != VERSION:
        raise ValueError('Supported area preview version required')
    if 4*cells > MAX_WORLD_BLOCKS:
        raise ValueError('Area preview native write budget exceeded')
    nx = math.ceil((maxx-minx)/MAX_SPAN_M)
    nz = math.ceil((maxz-minz)/MAX_SPAN_M)
    if nx*nz > MAX_TILES:
        raise ValueError('Area preview complete platform exceeds section count budget')
    tiles = []
    for x in range(minx, maxx, MAX_SPAN_M):
        for z in range(minz, maxz, MAX_SPAN_M):
            tile_cells = min(MAX_SPAN_M, maxx-x)*min(MAX_SPAN_M, maxz-z)
            if tile_cells > MAX_PLATFORM_CELLS:
                raise ValueError('Area preview section cell budget exceeded')
            tiles.append({'index': len(tiles), 'bounds_source_local_xy': [x, z,
                min(x+MAX_SPAN_M, maxx), min(z+MAX_SPAN_M, maxz)],
                'platform_cells': tile_cells})
    return tiles


def _rasterize(layout, cancelled, *, version=VERSION):
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
    tiles = _platform_tiles([minx, minz, maxx, maxz], version)
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
    counts = {row['id']: 0 for row, _, _ in shapes}
    # Sampling work is charged once for the full source bounding boxes above.
    # Disjoint sections partition that work, including features crossing seams.
    for tile in tiles:
        check()
        tx0, tz0, tx1, tz1 = tile['bounds_source_local_xy']
        tile_materials = set()
        tile_paving = set()
        tile_counts = {}
        for row, geometry, surface in shapes:
            check()
            a, b, c, d = geometry.bounds
            count = 0
            for x in range(max(tx0, math.floor(a)), min(tx1, math.ceil(c))):
                check()
                for z in range(max(tz0, math.floor(b)), min(tz1, math.ceil(d))):
                    if not geometry.covers(Point(x+.5, z+.5)):
                        continue
                    key = (x, z)
                    material = (BUILDING_MARKER_MATERIAL if row['role'] == 'building'
                        else paving_palette.palette_block(surface, x, z))
                    if key in materials and materials[key] != material:
                        raise ValueError('Conflicting source proposals occupy the same preview cell')
                    materials[key] = material
                    tile_materials.add(key)
                    owners.setdefault(key, set()).add(row['id'])
                    if row['role'] in SURFACE_ROLES:
                        paving.add(key)
                        tile_paving.add(key)
                    count += 1
            counts[row['id']] += count
            tile_counts[row['id']] = count
        tile.update(display_cells=len(tile_materials), paving_cells=len(tile_paving),
            candidate_display_cells=tile_counts,
            native_write_attempts=4*tile['platform_cells']+len(tile_materials))
    candidate_counts = []
    for row, geometry, surface in shapes:
        count = counts[row['id']]
        candidate_counts.append({'candidate_id': row['id'], 'role': row['role'], 'display_cells': count,
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
        'candidate_counts': candidate_counts, 'platform_bounds': [minx, minz, maxx, maxz],
        'tiles': tiles, 'platform_cells': platform_cells,
        'native_write_attempts': 4*platform_cells+len(materials),
        'sampling_checks': checks, 'source_points': points,
        'grid_connectivity': _grid_connectivity(paving, owners)}


def _saved_grid_check(path, offset, sampled, cancelled):
    from amulet.level.formats.leveldb_world import LevelDBFormat
    from .bedrock import material_block
    wrapper = LevelDBFormat(str(path))
    wrapper.open()
    paving = set()
    verified_tiles = []
    expected_blocks = {material: material_block(material)
        for material in set(sampled['materials'].values()) | {'grass_block'}}
    try:
        for tile in sampled['tiles']:
            a, b, c, d = tile['bounds_source_local_xy']
            platform_cells = display_cells = paving_cells = 0
            candidate_counts = {identifier: 0 for identifier in tile['candidate_display_cells']}
            # Direct-format reads retain one decoded chunk at a time. Check
            # every platform cell, including grass and both sides of seams.
            for cx in range(a//16, (c-1)//16+1):
                for cd in range(b//16, (d-1)//16+1):
                    if cancelled():
                        raise CancelledError('Area plan preview cancelled')
                    chunk = wrapper.load_chunk(cx, -cd-1, DIMENSION)
                    for x in range(max(a, cx*16), min(c, (cx+1)*16)):
                        for depth in range(max(b, cd*16), min(d, (cd+1)*16)):
                            # Reflect the complete source cell interval.
                            z = -depth-1
                            key = (x, depth)
                            material = sampled['materials'].get(key, 'grass_block')
                            actual = chunk.block_palette[int(chunk.blocks[x%16, offset, z%16])]
                            expected = expected_blocks[material]
                            if (actual.namespaced_name != expected.namespaced_name
                                    or any(actual.properties.get(k) != v for k, v in expected.properties.items())):
                                raise ValueError('Saved area display cells differ from source rasterization')
                            for y in (offset+1, offset+2):
                                if chunk.block_palette[int(chunk.blocks[x%16, y, z%16])].base_name != 'air':
                                    raise ValueError('Saved flat area display headroom is occupied')
                            platform_cells += 1
                            display_cells += key in sampled['materials']
                            for identifier in sampled['owners'].get(key, ()):
                                candidate_counts[identifier] += 1
                            if key in sampled['paving']:
                                paving.add(key)
                                paving_cells += 1
                    del chunk
            if (platform_cells != tile['platform_cells'] or display_cells != tile['display_cells']
                    or paving_cells != tile['paving_cells']
                    or candidate_counts != tile['candidate_display_cells']):
                raise ValueError('Saved section coverage or feature membership changed')
            verified_tiles.append({**tile, 'saved_platform_cells': platform_cells,
                'saved_display_cells': display_cells, 'saved_paving_cells': paving_cells,
                'saved_candidate_display_cells': candidate_counts, 'verified': True})
    finally:
        wrapper.close()
    result = _grid_connectivity(paving, sampled['owners'])
    if result != sampled['grid_connectivity']:
        raise ValueError('Saved paving membership or grid connectivity changed')
    result.update(saved_display_cells_verified=True, saved_display_headroom_verified=True,
        saved_paving_membership_verified=True, saved_complete_platform_verified=True,
        saved_platform_cells=sum(t['saved_platform_cells'] for t in verified_tiles),
        saved_sections=verified_tiles, decoded_chunk_cache_limit=1)
    return result


def run(config, output, *, cancelled=lambda: False, progress=lambda value: None):
    if isinstance(config,dict) and config.get('version')=='planning-geometry-world-preview-v1':
        from .planning_geometry_world import run as run_geometry
        return run_geometry(config,output,cancelled=cancelled,progress=progress)
    validate(config)
    output = Path(output)
    if output.exists():
        raise ValueError('Fresh area plan preview output required')
    def check():
        if cancelled():
            raise CancelledError('Area plan preview cancelled')
    check()
    layout = _read_layout(config)
    sampled = _rasterize(layout, cancelled, version=config['version'])
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
            for tile in sampled['tiles']:
                check()
                a, b, c, d = tile['bounds_source_local_xy']
                for x in range(a, c):
                    check()
                    for depth in range(b, d):
                        stream.write(json.dumps({'x': x, 'y': 0, 'z': depth+1,
                            'kind': 'terrain', 'material': 'grass_block'}, sort_keys=True)+'\n')
                        material = sampled['materials'].get((x, depth))
                        if material is not None:
                            stream.write(json.dumps({'x': x, 'y': 0, 'z': depth+1,
                                'kind': 'path' if (x, depth) in sampled['paving'] else 'building',
                                'material': material}, sort_keys=True)+'\n')
                progress({'progress': .2*(tile['index']+1)/len(sampled['tiles']),
                    'message': 'Prepared complete plan section '+str(tile['index']+1)})
                check()
        progress({'progress': .25, 'message': 'Exporting the flat source-local plan preview'})
        report = {'version': config['version'], 'status': 'source_local_area_plan_preview_exported',
            'voxel_size_m': 1, 'model_blocks_per_source_metre': 1, 'crs': None,
            'vertical_datum': 'STUDY_ZERO', 'geographic_registration': None,
            'source_layout_sha256': config['layout_sha256'], 'source_layout_id': layout['id'],
            'source_document_sha256': layout['document_sha256'], 'source_page': layout['page'],
            'shared_frame': layout['shared_frame'],
            'horizontal_transform': {'minecraft_x': 'source-local nominal plan X',
                'minecraft_z': 'negative source-local nominal plan Y; not surveyed north'},
            'spawn_local_xyz_m': [minx+1, 1, minz+2],
            'platform_bounds_source_local_xy': sampled['platform_bounds'],
            'platform_partition': {'strategy': 'complete_half_open_sections',
                'sections': sampled['tiles'], 'section_count': len(sampled['tiles']),
                'platform_cells': sampled['platform_cells'],
                'native_write_attempts': sampled['native_write_attempts'],
                'sampling_checks': sampled['sampling_checks'], 'source_points': sampled['source_points'],
                'all_candidates_retained': True, 'cropped': False, 'rescaled': False},
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
            'limits': {'max_candidates': MAX_CANDIDATES, 'max_section_span_m': MAX_SPAN_M,
                'max_section_cells': MAX_PLATFORM_CELLS,
                'max_sections': 1 if config['version'] == LEGACY_VERSION else MAX_TILES,
                'max_total_platform_cells_before_features': (MAX_PLATFORM_CELLS
                    if config['version'] == LEGACY_VERSION else MAX_WORLD_BLOCKS//4),
                'max_world_blocks': MAX_WORLD_BLOCKS,
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
    if config['version']=='planning-geometry-world-preview-v1':
        for name in tuple(n for n in ('paving','gaps','buildings','markings','expansion') if n+'_path' in config):config[name+'_path']=str((path.parent/config[name+'_path']).resolve())
    report = run(config, arguments.output)
    print(json.dumps({'status': report['status'], 'file': report['file']}, sort_keys=True))


if __name__ == '__main__':
    main()
