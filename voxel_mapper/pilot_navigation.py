"""Conservative saved-world walking connectivity across one bounded pilot area."""
from collections import deque
from html import escape
import json

from .bedrock import material_block, MATERIALS
from .pilot_access import collision, _mapped_node, _review_surface_nodes, MAX_SEARCH_STATES

VERSION = 'whole-pilot-navigation-v3'
ARTIFACTS = ['navigation-review.json', 'navigation-review.svg']
MAX_WITNESS_POINTS = 512


def _tree(scene, start, allowed=None):
    parents, depths = {}, {}
    if not scene.standing(start) or (allowed is not None and start not in allowed):
        return parents, depths
    parents[start], depths[start] = None, 0
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in scene.neighbours(node):
            if neighbour not in parents and (allowed is None or neighbour in allowed):
                if len(parents) >= MAX_SEARCH_STATES:
                    raise ValueError('Whole-area navigation graph budget exceeded')
                parents[neighbour], depths[neighbour] = node, depths[node] + 1
                queue.append(neighbour)
    return parents, depths


def _native(node, offset):
    x, z, height = node
    return [x + .5, height / 2 + offset, -z + .5]


def _witness(identifier, candidates, parents, depths, offset, scope):
    candidates = [node for node in candidates if depths[node] < MAX_WITNESS_POINTS]
    if not candidates:
        return None
    node = max(candidates, key=lambda p: (depths[p], p))
    route = []
    while node is not None:
        route.append(node)
        node = parents[node]
    route.reverse()
    return {'id': identifier, 'surface_scope': scope, 'status': 'native_route_ready',
            'horizontal_length_m': len(route) - 1, 'route_local_x_z_half_y': [list(p) for p in route],
            'route_native_xyz': [_native(p, offset) for p in route], 'minecraft_playtest': 'not_performed'}


def _walking_nodes(scene, mapped, records):
    walking = set(mapped) | _review_surface_nodes(scene, records).keys()
    for (x, y, z), row in records.items():
        if row['kind'] != 'steps' or not row.get('feature', '').startswith('review/'):
            continue
        form = collision(material_block(row.get('material', MATERIALS['steps'])))
        node = (x, z, 2 * y + form[2]) if form and form[2] is not None else None
        if node is not None and scene.standing(node):
            walking.add(node)
    return walking


def inspect(scene, spawn, mapped, paths, records, offset, withheld):
    all_parents, all_depths = _tree(scene, spawn)
    review = _review_surface_nodes(scene, records)
    surfaces = {**mapped, **review}
    walking = _walking_nodes(scene, mapped, records)
    path_parents, path_depths = _tree(scene, spawn, walking)
    remaining, components, membership = set(walking), [], {}
    while remaining:
        group, _ = _tree(scene, min(remaining), walking)
        nodes = set(group)
        remaining.difference_update(nodes)
        identifier = f'walking-component-{len(components) + 1:04d}'
        for node in nodes:
            membership[node] = identifier
        components.append({'id': identifier, 'supported_nodes': len(nodes),
            'contains_spawn': spawn in nodes, 'reachable_from_spawn_by_any_walking': bool(nodes & all_parents.keys()),
            'feature_ids': sorted({surfaces[node] for node in nodes if node in surfaces}),
            'representative_native_xyz': _native(min(nodes), offset),
            'cells_local_x_z_half_y': [list(node) for node in sorted(nodes)]})
    features = {}
    for key, row in paths.items():
        x, y, z = key
        node = _mapped_node(scene, key, row, records)
        group = features.setdefault(row['feature'], {'emitted_cells': 0, 'supported_cells': 0,
            'reachable_cells_any_walking': 0, 'reachable_cells_on_walking_surfaces': 0,
            'overridden_cells': 0, 'blocked_or_unsupported_cells': 0, 'component_ids': set(),
            'unreachable_examples_native_xyz': []})
        group['emitted_cells'] += 1
        if node is None and records.get(key) != row:
            group['overridden_cells'] += 1
        elif node not in mapped:
            group['blocked_or_unsupported_cells'] += 1
        else:
            group['supported_cells'] += 1
            group['reachable_cells_any_walking'] += node in all_parents
            group['reachable_cells_on_walking_surfaces'] += node in path_parents
            group['component_ids'].add(membership[node])
            if node not in all_parents and len(group['unreachable_examples_native_xyz']) < 3:
                group['unreachable_examples_native_xyz'].append(_native(node, offset))
    feature_rows = []
    for identifier, group in sorted(features.items()):
        group['component_ids'] = sorted(group['component_ids'])
        count, reached = group['supported_cells'], group['reachable_cells_any_walking']
        group['status'] = ('no_supported_cells' if not count else 'unreachable' if not reached
                           else 'partly_reachable' if reached < count else 'reachable')
        feature_rows.append({'feature_id': identifier, **group})
    barriers, barrier_count = [], 0
    for node in sorted(walking):
        x, z, height = node
        for nx, nz in ((x + 1, z), (x, z + 1)):
            for nh in scene.nodes(nx, nz):
                other = nx, nz, nh
                if other in walking and not scene.transition(node, other):
                    barrier_count += 1
                    if len(barriers) < 1000:
                        barriers.append({'from_local_x_z_half_y': list(node), 'to_local_x_z_half_y': list(other),
                                         'reason': 'step_exceeds_half_metre' if abs(nh - height) > 1 else 'swept_headroom'})
    witnesses = [
        _witness('mapped-walk', set(mapped) & path_parents.keys(), path_parents, path_depths, offset,
                 'mapped walking surfaces, provisional planning paving, estimated slab joins and estimated approaches'),
        _witness('terrain-detour', (set(mapped) & all_parents.keys()) - path_parents.keys(),
                 all_parents, all_depths, offset, 'includes terrain or other surfaces outside the mapped walking network'),
    ]
    reachable = set(mapped) & all_parents.keys()
    return {'version': VERSION, 'status': 'all_emitted_walking_cells_reachable' if len(reachable) == len(paths) and paths else 'partial_or_unresolved',
        'scope': 'All emitted pilot columns; routes may use terrain unless explicitly restricted to walking surfaces.',
        'bounds_local_xz': list(scene.bounds), 'sampled_columns': len(scene.columns),
        'supported_standing_nodes_reachable_from_spawn': len(all_parents),
        'mapped_emitted_cells': len(paths), 'mapped_supported_cells': len(mapped),
        'mapped_cells_with_estimated_display_slabs': sum(
            node[2] != 2 * key[1] + 2
            for key, row in paths.items() if (node := _mapped_node(scene, key, row, records)) is not None),
        'mapped_cells_with_planning_review_finish': sum(
            _mapped_node(scene, key, row, records) is not None and records.get(key) != row
            for key, row in paths.items()),
        'mapped_reachable_cells_any_walking': len(reachable),
        'mapped_reachable_cells_on_walking_surfaces': len(set(mapped) & path_parents.keys()),
        'planning_review_supported_cells': len(review),
        'planning_review_reachable_cells_any_walking': len(set(review) & all_parents.keys()),
        'planning_review_reachable_cells_on_walking_surfaces': len(set(review) & path_parents.keys()),
        'walking_components': components, 'features': feature_rows,
        'adjacent_walking_surface_barriers': barrier_count, 'barrier_examples': barriers,
        'withheld_feature_ids_not_audited_as_geometry': withheld,
        'spawn_local_x_z_half_y': list(spawn), 'spawn_native_xyz_centred': _native(spawn, offset),
        'walkthroughs': [witness for witness in witnesses if witness],
        'sample_route_point_limit': MAX_WITNESS_POINTS,
        'reachable_columns_local_xz': [list(p) for p in sorted({(p[0], p[1]) for p in all_parents})],
        'minecraft_playtest': 'not_performed', 'accepted_physical_geometry': False, 'training_labels_generated': 0}


def write(output, report, footprint):
    (output / 'navigation-review.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    x0, z0, x1, z1 = report['bounds_local_xz']
    scale = min(840 / (x1 - x0 + 1), 700 / (z1 - z0 + 1))
    def point(x, z):
        return 35 + (x - x0) * scale, 105 + (z1 + 1 - z) * scale
    def cell(x, z, colour):
        px, pz = point(x, z + 1)
        return f'<rect x="{px:.2f}" y="{pz:.2f}" width="{scale:.2f}" height="{scale:.2f}" fill="{colour}"/>'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="960" viewBox="0 0 1000 960">',
           '<rect width="1000" height="960" fill="white"/>',
           '<g font-family="sans-serif" fill="#263238">',
           '<text x="35" y="35" font-size="24">Whole-area native walking audit</text>',
           '<text x="35" y="64" font-size="14">Conservative centred-player graph; half-metre steps, two-metre headroom. No in-game test.</text>',
           f'<text x="35" y="88" font-size="14">Mapped cells reachable: {report["mapped_reachable_cells_any_walking"]}/{report["mapped_supported_cells"]}; on walking surfaces: {report["mapped_reachable_cells_on_walking_surfaces"]}</text>']
    px, pz = point(x0, z1 + 1)
    svg.append(f'<rect x="{px}" y="{pz}" width="{(x1-x0+1)*scale}" height="{(z1-z0+1)*scale}" fill="#eeeeee"/>')
    for x, z in report['reachable_columns_local_xz']:
        svg.append(cell(x, z, '#d5e8d6'))
    for group in report['walking_components']:
        colour = '#126d94' if group['contains_spawn'] else '#cd8b29' if group['reachable_from_spawn_by_any_walking'] else '#b84343'
        for x, z, _ in group['cells_local_x_z_half_y']:
            svg.append(cell(x, z, colour))
    points = ' '.join(f'{x:.2f},{z:.2f}' for x, z in (point(x, z) for x, z in footprint.exterior.coords))
    svg.append(f'<polygon points="{points}" fill="none" stroke="#754e2c" stroke-width="2"/>')
    sx, sz = point(report['spawn_local_x_z_half_y'][0] + .5, report['spawn_local_x_z_half_y'][1] + .5)
    svg.append(f'<circle cx="{sx}" cy="{sz}" r="5" fill="#1a2832"/>')
    for y, text in [(845, 'Green: reachable terrain/surfaces. Grey: no reachable standing node in the audited column.'),
                    (871, 'Blue: spawn walking component. Amber: other components reached via terrain/interior. Red: unreachable.'),
                    (897, 'Separate components can still connect off path. Missing/withheld geometry is not made walkable.'),
                    (923, 'Estimated world placement and vegetation; no physical acceptance or AI training labels.')]:
        svg.append(f'<text x="35" y="{y}" font-size="13">{escape(text)}</text>')
    if report.get('planning_review_supported_cells'):
        text = (f'Provisional planning paving: {report["planning_review_supported_cells"]} cells; '
                f'{report["planning_review_reachable_cells_on_walking_surfaces"]} reachable on walking surfaces.')
        svg.append(f'<text x="35" y="823" font-size="13">{escape(text)}</text>')
    svg += ['</g>', '</svg>']
    (output / 'navigation-review.svg').write_text('\n'.join(svg))
