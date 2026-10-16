"""Add bounded, explicitly estimated half-slab joins to grounded mapped paths.

Only empty cells above surviving paving receive blocks. Original terrain,
source rows, building cells, spawn and approach columns are retained. This is
a display experiment, not a reconstruction of surveyed steps or site grading.
"""
import json

from shapely.geometry import box, mapping
from shapely.ops import unary_union

from .bedrock import MATERIALS, material_block
from .pilot_access import (PATH_STEP_FEATURE, PATH_STEP_POLICY, collision, _read_inputs,
                           _scene, _mapped_nodes)
from .pilot_navigation import _tree, _walking_nodes, inspect

VERSION = 'provisional-path-step-joins-v1'
MAX_SLABS = 512
MAX_CANDIDATES = 4096  # At most 512 * 4096 deterministic candidate evaluations.


def validate_settings(settings):
    if (not isinstance(settings, dict) or set(settings) != {'policy', 'max_slabs'}
            or settings.get('policy') != PATH_STEP_POLICY
            or type(settings.get('max_slabs')) is not int
            or not 1 <= settings['max_slabs'] <= MAX_SLABS):
        raise ValueError('Bounded estimated half-slab path steps policy required')


def _summary(navigation):
    keys = ('mapped_emitted_cells', 'mapped_supported_cells', 'mapped_reachable_cells_any_walking',
            'mapped_reachable_cells_on_walking_surfaces', 'mapped_cells_with_estimated_display_slabs',
            'adjacent_walking_surface_barriers')
    return {**{key: navigation[key] for key in keys},
            'walking_surface_components': len(navigation['walking_components'])}


def _row(node, source):
    x, z, height = node
    return {'x': x, 'y': height // 2, 'z': z, 'kind': 'steps', 'feature': PATH_STEP_FEATURE,
            'source': 'provisional-study-model', 'material': 'stone_slab',
            'material_origin': 'estimated_reconstruction_shell', 'display_policy': PATH_STEP_POLICY,
            'accepted_physical_geometry': False,
            'mapped_source_cell': {key: source[key] for key in ('feature', 'x', 'y', 'z')}}


def append(output, quality, access, settings, max_voxels=1_000_000):
    validate_settings(settings)
    if access.get('audit_scope') != 'whole_pilot':
        raise ValueError('Estimated path steps require a whole_pilot native audit')
    records, terrain, paths, bounds = _read_inputs(output, access['component'], whole_area=True)
    if any(row.get('feature') == PATH_STEP_FEATURE for row in records.values()):
        raise ValueError('Estimated path steps must be applied once to a fresh scene')
    scene = _scene(records, bounds)
    mapped = _mapped_nodes(scene, paths, records)
    walking = _walking_nodes(scene, mapped, records)
    sx, sy, sz = quality['spawn_local_xyz_m']
    spawn = sx, sz, 2 * sy
    protected = {(x, z) for route in access['routes'] for x, z, _ in route} | {(sx, sz)}
    guard = access['footprint'].buffer(1)

    def grounded(node):
        x, z, height = node
        key = x, height // 2 - 1, z
        return (height % 2 == 0 and key in paths and records.get(key) == paths[key]
                and terrain.get((x, z)) == key[1]
                and collision(material_block(paths[key].get('material', MATERIALS['path']))) == (0, 2, 2))

    candidates = {}
    for node in sorted(mapped):
        x, z, height = node
        raised = x, z, height + 1
        if (not grounded(node) or (x, z) in protected
                or guard.intersects(box(x, z, x + 1, z + 1))
                or (x, height // 2, z) in records
                or not scene.clear(x, z, height, height + 6)):
            continue
        adjacent = [(nx, nz, nh) for nx, nz in
                    ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1))
                    for nh in scene.nodes(nx, nz)]
        # Even an existing full-metre gap may be useful when jumping in-game.
        # Do not make any nonzero adjacent standing-height gap larger, including
        # off-path terrain. Flat neighbours may become intended half steps.
        if any(other[2] < height for other in adjacent):
            continue
        # Retain every existing incident edge, including grass, roads and
        # half-slab approaches. Raising a lower neighbour can otherwise cut it.
        if any(not scene.transition(raised, other) for other in scene.neighbours(node)):
            continue
        upper = [(nx, nz, height + 2) for nx, nz in
                 ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1))]
        upper = sorted(other for other in upper if other in mapped and grounded(other))
        if upper:
            candidates[node] = upper
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError('Estimated path step candidate budget exceeded')

    # Build the existing walking components. A join locks its upper endpoints
    # at their original heights, so a later slab cannot undo an earlier join.
    parents, sizes = {node: node for node in walking}, {node: 1 for node in walking}
    def find(node):
        while node != parents[node]:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            if sizes[a] < sizes[b]:
                a, b = b, a
            parents[b] = a
            sizes[a] += sizes[b]
    for node in sorted(walking):
        for other in scene.neighbours(node):
            if other in walking:
                union(node, other)

    selected, locked = {}, set()
    for _ in range(settings['max_slabs']):
        best = None
        for node, upper in candidates.items():
            if node in selected or node in locked:
                continue
            links = [other for other in upper if other not in selected and find(other) != find(node)]
            groups = {find(node)} | {find(other) for other in links}
            score = (find(spawn) in groups if spawn in parents else False,
                     len(groups) - 1, sum(sizes[group] for group in groups))
            if len(groups) > 1 and (best is None or score > best[0]):
                best = score, node, links
        if best is None:
            break
        _, node, links = best
        selected[node] = links
        for other in links:
            locked.add(other)
            union(node, other)

    adjustments = {node: (node[0], node[1], node[2] + 1) for node in selected}
    preserved_edges = [(node, other) for node in selected for other in scene.neighbours(node)]
    preserved_gaps = [(node, (nx, nz, nh)) for node in selected
                      for nx, nz in ((node[0] - 1, node[1]), (node[0] + 1, node[1]),
                                     (node[0], node[1] - 1), (node[0], node[1] + 1))
                      for nh in scene.nodes(nx, nz) if nh != node[2]]
    additions, joins = [], []
    for node, upper in sorted(selected.items()):
        x, z, height = node
        source = paths[x, height // 2 - 1, z]
        row = _row(node, source)
        additions.append(row)
        joins.append({'block_local_xyz': [row['x'], row['y'], row['z']],
                      'mapped_source_cell': row['mapped_source_cell'],
                      'before_local_x_z_half_y': list(node),
                      'after_local_x_z_half_y': list(adjustments[node]),
                      'upper_endpoints_local_x_z_half_y': [list(other) for other in upper]})
    if quality['voxel_records'] + len(additions) > max_voxels:
        raise ValueError('Estimated path steps exceed pilot voxel budget')
    updated_records = {**records, **{(row['x'], row['y'], row['z']): row for row in additions}}
    updated = _scene(updated_records, bounds)
    updated_mapped = _mapped_nodes(updated, paths, updated_records)
    for a, b in preserved_edges:
        a, b = adjustments.get(a, a), adjustments.get(b, b)
        if not (updated.standing(a) and updated.standing(b) and updated.transition(a, b)):
            raise ValueError('Estimated path step would break an existing walking edge')
    _check_gaps(updated, adjustments, preserved_gaps)
    before = inspect(scene, spawn, mapped, paths, records, 0, [])
    after = inspect(updated, spawn, updated_mapped, paths, updated_records, 0, [])
    before_reached, _ = _tree(scene, spawn)
    after_reached, _ = _tree(updated, spawn)
    preserved_reachable = {adjustments.get(node, node) for node in mapped if node in before_reached}
    if len(updated_mapped) != len(mapped) or not preserved_reachable.issubset(after_reached):
        raise ValueError('Estimated path steps would lose supported or reachable mapped cells')
    report = {'version': VERSION, 'policy': settings['policy'],
              'status': 'awaiting_native_readback', 'estimated': True,
              'candidate_columns': len(candidates), 'max_slabs': settings['max_slabs'],
              'added_slab_records': len(additions), 'surface_height_adjustment_m': .5,
              'selection': 'Grow the spawn walking component first, then merge count and total component size; coordinate order breaks ties.',
              'stop_reason': 'slab_limit' if len(selected) == settings['max_slabs'] else 'no_further_compatible_component_join',
              'before': _summary(before), 'planned_after': _summary(after),
              'comparison_basis': 'Composed scene after entrance approaches, before optional vegetation context.',
              'preserved_existing_incident_edges': len(preserved_edges),
              'preserved_nonzero_adjacent_height_gaps': len(preserved_gaps),
              'preexisting_nonzero_adjacent_height_gaps_enlarged': 0,
              'protected_spawn_and_approach_columns': len(protected), 'building_guard_m': 1,
              'terrain_excavation_cells': 0, 'source_records_rewritten': 0,
              'original_native_blocks_replaced': 0, 'accepted_physical_geometry': False,
              'training_labels_generated': 0, 'minecraft_playtest': 'not_performed', 'joins': joins,
              'limitations': ['Only grounded mapped paving is eligible; no missing bridge or tunnel is inferred.',
                              'Stone slabs and raised walking heights are display estimates, not measured steps.',
                              'One-block-wide centred routes; no jumping or Minecraft physics simulation.',
                              'Greedy bounded selection does not prove an optimal or complete ramp network.']}
    # All geometry and budget checks precede writes. Source voxel records remain
    # byte-for-byte prefixes; additions occupy previously absent cells only.
    with (output / 'voxels.jsonl').open('a', encoding='utf-8') as stream:
        for row in additions:
            stream.write(json.dumps(row) + '\n')
    if additions:
        collection = json.loads((output / 'features-local.geojson').read_text())
        geometry = unary_union([box(row['x'], row['z'], row['x'] + 1, row['z'] + 1) for row in additions])
        collection['features'].append({'type': 'Feature', 'id': PATH_STEP_FEATURE, 'geometry': mapping(geometry),
            'properties': {'review_only': True, 'accepted_physical_geometry': False,
                           'source': 'Estimated display slab joins; not source-supported site steps.'}})
        (output / 'features-local.geojson').write_text(json.dumps(collection, indent=2) + '\n', encoding='utf-8')
    quality['voxel_records'] += len(additions)
    from .cli import file_sha256
    quality['sha256'] = file_sha256(output / 'voxels.jsonl')
    quality['path_steps_review'] = report
    _write(output, report)
    return {'report': report, 'adjustments': adjustments, 'preserved_edges': preserved_edges,
            'preserved_gaps': preserved_gaps,
            'expected_mapped': set(updated_mapped), 'preserved_reachable': preserved_reachable,
            'additions': additions}


def verify(output, scene, mapped, records, offset, navigation, prepared):
    """Reject lost joins/old edges using collision shapes read from the saved DB."""
    report, adjustments = prepared['report'], prepared['adjustments']
    for row in prepared['additions']:
        if records.get((row['x'], row['y'], row['z'])) != row:
            raise ValueError('Saved path step lost its source lineage')
    for join in report['joins']:
        a = tuple(join['after_local_x_z_half_y'])
        if a not in mapped or not scene.standing(a):
            raise ValueError('Saved path step lacks mapped bearing support or headroom')
        for upper in join['upper_endpoints_local_x_z_half_y']:
            b = tuple(upper)
            if b not in mapped or not scene.standing(b) or not scene.transition(a, b):
                raise ValueError('Saved path step join is blocked or disconnected')
    for a, b in prepared['preserved_edges']:
        a, b = adjustments.get(a, a), adjustments.get(b, b)
        if not (scene.standing(a) and scene.standing(b) and scene.transition(a, b)):
            raise ValueError('Saved path step lost an existing walking edge')
    _check_gaps(scene, adjustments, prepared['preserved_gaps'])
    spawn = tuple(navigation['spawn_local_x_z_half_y'])
    reached, _ = _tree(scene, spawn)
    if not (prepared['expected_mapped'].issubset(mapped)
            and prepared['preserved_reachable'].issubset(reached)):
        raise ValueError('Saved path steps lost supported or reachable mapped cells')
    for join in report['joins']:
        x, y, z = join['block_local_xyz']
        join['block_native_xyz'] = [x, y + offset, -z]
    report.update(status='native_joins_verified' if report['joins'] else 'no_qualifying_joins',
                  native_after=_summary(navigation), verified_joins=len(report['joins']),
                  native_readback={'status': 'completed', 'all_existing_incident_edges_preserved': True,
                                   'no_preexisting_nonzero_adjacent_height_gap_enlarged': True,
                                   'all_previously_reachable_mapped_cells_preserved': True,
                                   'minecraft_playtest': 'not_performed'})
    _write(output, report)


def _check_gaps(scene, adjustments, gaps):
    for a, b in gaps:
        na, nb = adjustments.get(a, a), adjustments.get(b, b)
        if not (scene.standing(na) and scene.standing(nb) and abs(na[2] - nb[2]) <= abs(a[2] - b[2])):
            raise ValueError('Path step enlarged or obstructed a pre-existing adjacent height gap')


def _write(output, report):
    (output / 'path-steps-review.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
