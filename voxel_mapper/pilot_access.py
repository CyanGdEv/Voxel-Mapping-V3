"""Conservative, bounded access checks for explicitly provisional review worlds.

This is a centred single-player route with two metres of headroom and at most
half-metre steps. Unknown collision shapes obstruct the route. It is not a
Minecraft physics simulator, accessible-design assessment or real-site survey.
"""
from collections import deque
from html import escape
import heapq
import json
import math

import amulet
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

from .bedrock import MATERIALS, material_block, record_priority
from .doorway_raster import PLAYER_WIDTH_M

VERSION = 'provisional-world-access-v4'
RADIUS = 32
MAX_ROUTE_COLUMNS = 32
MAX_SEARCH_STATES = 60_000
MAX_APPROACH_SEARCH_STATES = 60_000
MAX_FILL = 16
MAX_READ_CELLS = 1_000_000
WALKING_KINDS = {'path', 'sidewalk', 'queue', 'plaza'}
FULL_BLOCKS = {'stone', 'dirt', 'grass_block', 'concrete', 'planks', 'stone_bricks',
               'granite', 'sandstone', 'brick_block', 'terracotta', 'stained_terracotta',
               'mud_bricks', 'iron_block', 'log'}


def collision(block):
    """Half-block vertical interval and bearing height, or conservative obstruction."""
    name = block.base_name
    if name == 'air':
        return None
    if name in FULL_BLOCKS:
        return 0, 2, 2
    if name == 'slab':
        kind = str(block.properties.get('type', ''))
        if kind == 'bottom':
            return 0, 1, 1
        if kind == 'top':
            return 1, 2, 2
        if kind == 'double':
            return 0, 2, 2
    # Fences/walls can extend above the nominal block. Stairs, trapdoors, liquids,
    # plants and unrecognised blocks never become assumed walkable supports.
    return 0, 3 if name in ('fence', 'wall', 'fence_gate') else 2, None


class Scene:
    def __init__(self, columns, bounds):
        self.columns, self.bounds = columns, bounds
        self._nodes = {}

    def covers(self, x, z):
        x0, z0, x1, z1 = self.bounds
        return x0 <= x <= x1 and z0 <= z <= z1

    def clear(self, x, z, feet, head=None):
        head = feet + 4 if head is None else head
        return self.covers(x, z) and all(
            high <= feet or low >= head for low, high, _ in self.columns.get((x, z), ()))

    def nodes(self, x, z):
        key = x, z
        if key not in self._nodes:
            self._nodes[key] = tuple(sorted({top for _, _, top in self.columns.get(key, ())
                                            if top is not None and self.clear(x, z, top)}))
        return self._nodes[key]

    def standing(self, node):
        x, z, height = node
        return height in self.nodes(x, z)

    def transition(self, a, b):
        return (abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 and abs(a[2] - b[2]) <= 1
                and self.clear(a[0], a[1], max(a[2], b[2]))
                and self.clear(b[0], b[1], max(a[2], b[2])))

    def neighbours(self, node):
        x, z, height = node
        for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
            for nh in self.nodes(nx, nz):
                candidate = nx, nz, nh
                if self.transition(node, candidate):
                    yield candidate


def _scene(records, bounds):
    columns = {}
    for (x, y, z), row in records.items():
        form = collision(material_block(row.get('material', MATERIALS.get(row['kind'], 'stone'))))
        if form:
            low, high, top = form
            columns.setdefault((x, z), []).append((2 * y + low, 2 * y + high,
                                                  None if top is None else 2 * y + top))
    return Scene(columns, bounds)


def _read_inputs(output, component, whole_area=False):
    ax, az = [round(v) for v in component['anchor_local_m']]
    bounds = ax - RADIUS, az - RADIUS, ax + RADIUS, az + RADIUS
    records, terrain, paths = {}, {}, {}
    with (output / 'voxels.jsonl').open(encoding='utf-8') as stream:
        for index, line in enumerate(stream):
            if index >= 1_000_000:
                raise ValueError('Access input voxel budget exceeded')
            row = json.loads(line)
            x, y, z = row['x'], row['y'], row['z']
            if not whole_area and (not bounds[0] <= x <= bounds[2] or not bounds[1] <= z <= bounds[3]):
                continue
            key = x, y, z
            if key not in records or record_priority(row) > record_priority(records[key]):
                records[key] = row
            if row['kind'] == 'terrain':
                terrain[x, z] = y
            if row['kind'] in WALKING_KINDS and not row.get('feature', '').startswith(('review/', 'planning/')):
                # Composition retains the first equal-priority record. A later
                # alias must not hide that surviving mapped junction.
                if key not in paths or record_priority(row) > record_priority(paths[key]):
                    paths[key] = row
    if whole_area:
        if not records:
            raise ValueError('Whole-area access requires emitted geometry')
        bounds = (min(p[0] for p in records), min(p[2] for p in records),
                  max(p[0] for p in records), max(p[2] for p in records))
        if (bounds[2] - bounds[0] + 1) * (bounds[3] - bounds[1] + 1) > 40_000:
            raise ValueError('Whole-area access column budget exceeded')
    return records, terrain, paths, bounds


def _mapped_nodes(scene, paths, records):
    return {(x, z, 2 * y + 2): row['feature'] for (x, y, z), row in paths.items()
            if records.get((x, y, z)) == row and scene.standing((x, z, 2 * y + 2))}


def _flood(scene, starts, allowed=None):
    seen = {node for node in starts if scene.standing(node)}
    queue = deque(sorted(seen))
    while queue:
        node = queue.popleft()
        for neighbour in scene.neighbours(node):
            if neighbour not in seen and (allowed is None or allowed(neighbour)):
                seen.add(neighbour)
                queue.append(neighbour)
        if len(seen) > MAX_SEARCH_STATES:
            raise ValueError('Access graph budget exceeded')
    return seen


def _shortest_path(scene, starts, goal, allowed=None):
    """Retain a bounded, deterministic witness rather than just reachability."""
    parents = {node: None for node in sorted(set(starts))
               if scene.standing(node) and (allowed is None or allowed(node))}
    queue = deque(parents)
    while queue:
        if len(parents) > MAX_SEARCH_STATES:
            raise ValueError('Access witness search budget exceeded')
        node = queue.popleft()
        if goal(node):
            route = []
            while node is not None:
                route.append(node)
                node = parents[node]
            return list(reversed(route))
        for neighbour in scene.neighbours(node):
            if neighbour not in parents and (allowed is None or allowed(neighbour)):
                parents[neighbour] = node
                queue.append(neighbour)
    return []


def _walkthrough(scene, spawn, crossing, columns, footprint, floor, offset):
    """Reach this entrance from outside, then continue into its declared floor."""
    exterior = _exterior_predicate(footprint)
    approach = (_shortest_path(scene, [spawn], lambda p: p in crossing,
                               lambda p: exterior(p) or (p[0], p[1]) in columns)
                if crossing and exterior(spawn) else [])
    interior = footprint.buffer(-1)
    passage = _shortest_path(scene, approach[-1:],
        lambda p: p[2] == floor and interior.contains(Point(p[0] + .5, p[1] + .5)),
        lambda p: p[2] == floor and ((p[0], p[1]) in columns or
                  footprint.contains(Point(p[0] + .5, p[1] + .5))))
    route = approach + passage[1:] if approach and passage else []
    return {'status': 'native_route_ready' if route else 'unresolved',
            'doorway_index': len(approach) - 1 if route else None,
            'horizontal_length_m': len(route) - 1 if route else None,
            'route_local_x_z_half_y': [list(p) for p in route],
            # Convert block indices to block centres, then negate the Z index.
            # Negating the local centre itself would shift native Z by one block.
            'route_native_xyz': [[x + .5, h / 2 + offset, -z + .5] for x, z, h in route],
            'minecraft_playtest': 'not_performed'}


def _exterior_predicate(footprint):
    cache = {}
    def exterior(node):
        key = node[0], node[1]
        if key not in cache:
            cache[key] = footprint.intersection(box(key[0], key[1], key[0] + 1, key[1] + 1)).area <= 1e-8
        return cache[key]
    return exterior


def _openings(scene, component, footprint):
    """A doorway must connect into this building, rather than around its exterior."""
    floor = 2 * round(component['floor_elevation_m'])
    interior = footprint.buffer(-1)
    results, usable = [], set()
    exterior = _exterior_predicate(footprint)
    exterior_starts = [(x, z, height) for x, z in scene.columns if exterior((x, z))
                       for height in scene.nodes(x, z)]
    for opening in component['access_openings']:
        columns = {tuple(p) for p in opening['columns_local_xz']}
        nodes = {(x, z, floor) for x, z in columns if scene.standing((x, z, floor))}
        connected = set()
        for node in sorted(nodes):
            reached = _flood(scene, [node], lambda p: p[2] == floor and
                             ((p[0], p[1]) in columns or footprint.contains(Point(p[0] + .5, p[1] + .5))))
            if any(interior.contains(Point(p[0] + .5, p[1] + .5)) for p in reached):
                connected.add(node)
        source_passable = (opening['declared_height_m'] >= 2 and
                           opening.get('declared_width_m', PLAYER_WIDTH_M) >= PLAYER_WIDTH_M and
                           opening.get('native_representation') not in
                           ('source_too_narrow_for_player', 'unrepresented_on_native_grid'))
        if not source_passable:
            connected.clear()
        from_exterior = _flood(scene, exterior_starts, lambda p: exterior(p) or (p[0], p[1]) in columns)
        crossing = connected & from_exterior
        usable.update(connected)
        results.append({'id': opening['id'], 'declared_height_m': opening['declared_height_m'],
                        'declared_width_m': opening.get('declared_width_m'), 'source_player_clearance': source_passable,
                        'declared_native_columns': len(columns), 'standing_floor_columns': len(nodes),
                        'interior_connected_columns': len(connected),
                        'exterior_connected_columns': len(crossing),
                        'crossing_nodes_x_z_half_y': [list(p) for p in sorted(crossing)],
                        'usable_nodes_x_z_half_y': [list(p) for p in sorted(connected)],
                        'status': 'interior_connected' if connected else 'blocked_or_unresolved'})
    return results, usable


def _fill(scene, records, terrain, node, footprint, door_columns, path_columns):
    x, z, height = node
    if not scene.covers(x, z) or (x, z) not in terrain:
        return None
    if (x, z) in door_columns:
        return {} if scene.standing(node) else None
    # No path covering, source-building alteration or terrain cutting. New work
    # lies outside the entire footprint cell, not just outside its centre.
    if footprint.intersection(box(x, z, x + 1, z + 1)).area > 1e-8:
        return None
    if scene.standing(node):
        return {}
    if (x, z) in path_columns or not scene.clear(x, z, height):
        return None
    ground = terrain[x, z]
    if height <= 2 * (ground + 1) or height - 2 * (ground + 1) > 2 * MAX_FILL:
        return None
    cells = {(x, y, z): 'stone' for y in range(ground + 1, height // 2)}
    if height % 2:
        cells[x, height // 2, z] = 'stone_slab'
    if not cells:
        return None
    if any(key in records and records[key].get('material') != 'air' for key in cells):
        return None
    return cells


def _route(scene, records, terrain, targets, starts, footprint, state_budget=MAX_APPROACH_SEARCH_STATES, path_columns=None):
    """Bounded level/descending half-step search; failure stays explicit."""
    doors = {(x, z) for x, z, _ in starts}
    if path_columns is None:
        path_columns = {(x, z) for (x, _, z), row in records.items() if row['kind'] in WALKING_KINDS}
    queue, best, fill_cache = [], {}, {}
    for node in sorted(starts):
        best[node] = 0
        heapq.heappush(queue, (0, (node,)))
    explored = 0
    while queue and explored < state_budget:
        cost, path = heapq.heappop(queue)
        node = path[-1]
        if cost != best.get(node):
            continue
        explored += 1
        if node in targets:
            return path, explored
        if len(path) >= MAX_ROUTE_COLUMNS:
            continue
        visited_columns = {(p[0], p[1]) for p in path}
        x, z, height = node
        for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
            if (nx, nz) in visited_columns:
                continue
            for nh in (height, height - 1):
                neighbour = nx, nz, nh
                if not scene.transition(node, neighbour):
                    continue
                if neighbour not in fill_cache:
                    fill_cache[neighbour] = _fill(scene, records, terrain, neighbour, footprint, doors, path_columns)
                fill = fill_cache[neighbour]
                if fill is None:
                    continue
                new_cost = cost + 10 + len(fill) * 2 + (height - nh)
                if new_cost < best.get(neighbour, math.inf):
                    best[neighbour] = new_cost
                    heapq.heappush(queue, (new_cost, path + (neighbour,)))
    return None, explored


def prepare(output, quality, component, settings, max_voxels=1_000_000):
    records, terrain, paths, bounds = _read_inputs(output, component)
    collection = json.loads((output / 'features-local.geojson').read_text())
    footprint = shape(next(f['geometry'] for f in collection['features'] if f['id'] == component['feature_id']))
    scene = _scene(records, bounds)
    openings, starts = _openings(scene, component, footprint)
    targets = _mapped_nodes(scene, paths, records)
    before = _flood(scene, targets)
    report = {'version': VERSION, 'status': 'audit_only', 'estimated': True,
              'accepted_physical_geometry': False, 'bounds_local_xz': list(bounds),
              'minimum_headroom_m': 2, 'maximum_step_m': .5, 'route_width_blocks': 1,
              'minimum_source_player_width_m': PLAYER_WIDTH_M,
              'before': {'basis': 'composed input voxels before estimated access work',
                         'openings': openings, 'mapped_path_reachable_opening_columns': len(starts & before)},
              'approach': {'status': 'not_requested', 'added_voxel_records': 0},
              'terrain_excavation_cells': 0, 'source_geometry_cells_modified': 0,
              'accepted_park_world_blocks_added': 0, 'training_labels_generated': 0,
              'limitations': ['Centred one-player route; no in-game physics or accessible-design certification.',
                              'Only known full blocks and slabs bear weight; other shapes conservatively obstruct.',
                              'Estimated one-block-wide approach; no source-supported site access design.',
                              'Exterior reachability excludes routes through other building openings.',
                              'Placement and floor remain unverified; no independent geographic accuracy established.',
                              'Route search is bounded, level or descending, and does not prove absence of other routes.']}
    routes, fill, decisions = [], {}, []
    per_opening = isinstance(settings, dict) and settings.get('policy') == 'estimated_each_opening_approach_v2'
    if settings:
        groups = [(opening['id'], {tuple(p) for p in opening['usable_nodes_x_z_half_y']})
                  for opening in openings] if per_opening else [('any_opening', starts)]
        def distance(group):
            return min((abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in group[1] for b in targets), default=math.inf), group[0]
        groups.sort(key=distance)
        remaining = MAX_APPROACH_SEARCH_STATES
        path_columns = {(x, z) for x, _, z in paths}
        for identifier, group in groups:
            route, explored = _route(scene, records, terrain, targets, group, footprint, remaining, path_columns)
            remaining -= explored
            decision = {'opening_id': identifier, 'status': 'withheld_no_bounded_route',
                        'search_states': explored, 'added_voxel_records': 0}
            decisions.append(decision)
            if not route:
                continue
            doors = {(x, z) for x, z, _ in group}
            additions = {}
            for node in route:
                proposed = _fill(scene, records, terrain, node, footprint, doors, path_columns)
                if proposed is None:
                    raise ValueError('Estimated access route lost its construction clearance')
                additions.update(proposed)
            fill.update(additions)
            for (x, y, z), material in additions.items():
                records[x, y, z] = _approach_row(component['feature_id'] + '/approach', x, y, z, material)
            scene = _scene(records, bounds)
            routes.append(route)
            decision.update(status='estimated_approach_added' if additions else 'existing_route',
                added_voxel_records=len(additions), route_local_x_z_half_y=[list(p) for p in route],
                mapped_path_feature=targets[route[-1]], horizontal_length_m=len(route) - 1,
                maximum_step_m=max((abs(a[2] - b[2]) / 2 for a, b in zip(route, route[1:])), default=0))
        report['approach'] = {'status': 'estimated_approach_added' if fill else 'existing_route' if routes else 'withheld_no_bounded_route',
                              'added_voxel_records': len(fill), 'search_states': MAX_APPROACH_SEARCH_STATES - remaining,
                              'per_opening_requested': per_opening, 'decisions': decisions}
        if routes:
            primary = next(d for d in decisions if 'route_local_x_z_half_y' in d)
            for key in ('route_local_x_z_half_y', 'mapped_path_feature', 'horizontal_length_m', 'maximum_step_m'):
                report['approach'][key] = primary[key]
        if per_opening and any(d['status'] == 'withheld_no_bounded_route' for d in decisions):
            report['approach']['unresolved_opening_ids'] = [d['opening_id'] for d in decisions if d['status'] == 'withheld_no_bounded_route']
    route = routes[0] if routes else None
    identifier = component['feature_id'] + '/approach'
    if quality['voxel_records'] + len(fill) > max_voxels:
        raise ValueError('Access approach exceeds pilot voxel budget')
    # The terrain inventory is already clipped. Every proposed column must have
    # an emitted terrain cell; no inferred terrain is added beyond that domain.
    with (output / 'voxels.jsonl').open('a', encoding='utf-8') as stream:
        for (x, y, z), material in sorted(fill.items()):
            row = _approach_row(identifier, x, y, z, material)
            stream.write(json.dumps(row) + '\n')
            records[x, y, z] = row
    if fill:
        geometry = unary_union([box(x, z, x + 1, z + 1) for x, _, z in fill])
        collection['features'].append({'type': 'Feature', 'id': identifier, 'geometry': mapping(geometry),
            'properties': {'review_only': True, 'accepted_physical_geometry': False,
                           'source': 'Estimated access experiment; not a source-supported site design.'}})
        (output / 'features-local.geojson').write_text(json.dumps(collection, indent=2) + '\n', encoding='utf-8')
    updated = _scene(records, bounds)
    # Bedrock spawn metadata has integer Y. Choose a full-height supported point,
    # preferably the mapped-path endpoint of the route, without rounding a slab.
    candidates = [route[-1]] if route else sorted(targets)
    if not candidates:
        candidates = [(x, z, height) for x, z in sorted(terrain)
                      if not footprint.intersects(box(x, z, x + 1, z + 1))
                      for height in updated.nodes(x, z) if height % 2 == 0]
    candidates = [p for p in candidates if p[2] % 2 == 0 and updated.standing(p)]
    if not candidates:
        raise ValueError('Provisional review has no supported integer-height spawn')
    spawn = min(candidates, key=lambda p: (p[0] ** 2 + p[1] ** 2, p))
    quality['spawn_local_xyz_m'] = [spawn[0], spawn[2] // 2, spawn[1]]
    report['spawn_local_xyz_m'] = quality['spawn_local_xyz_m']
    quality['voxel_records'] += len(fill)
    from .cli import file_sha256
    quality['sha256'] = file_sha256(output / 'voxels.jsonl')
    quality['access_review'] = report
    return {'records': records, 'terrain': terrain, 'paths': paths, 'bounds': bounds,
            'footprint': footprint, 'component': component, 'report': report, 'route': route, 'routes': routes,
            'audit_scope': settings.get('audit_scope', 'component_neighbourhood') if isinstance(settings, dict) else 'component_neighbourhood',
            'withheld_feature_ids': sorted({issue['feature'] for issue in quality.get('issues', [])
                                            if issue.get('severity') == 'error' and issue.get('feature')})}


def _approach_row(identifier, x, y, z, material):
    return {'x': x, 'y': y, 'z': z, 'kind': 'steps', 'feature': identifier,
            'source': 'provisional-study-model', 'material': material,
            'material_origin': 'estimated_reconstruction_shell', 'accepted_physical_geometry': False}


def verify_saved(world_path, offset, spawn, prepared):
    """Read collision geometry and spawn metadata from the saved native world."""
    records, terrain, bounds = prepared['records'], prepared['terrain'], prepared['bounds']
    component, footprint, report = prepared['component'], prepared['footprint'], prepared['report']
    paths = prepared['paths']
    whole_area = prepared.get('audit_scope') == 'whole_pilot'
    if whole_area:
        records, terrain, paths, bounds = _read_inputs(world_path.parent, component, whole_area=True)
    columns, read_cells = {}, 0
    by_column = {}
    for x, y, z in records:
        by_column.setdefault((x, z), []).append(y)
    level = amulet.load_level(str(world_path))
    try:
        root = level.level_wrapper.root_tag.compound
        stored_spawn = [int(root['Spawn' + axis]) for axis in 'XYZ']
        if stored_spawn != spawn:
            raise ValueError('Saved review spawn differs from the requested spawn')
        active_chunk = None
        for (x, z), ys in sorted(by_column.items(), key=lambda item: (item[0][0] // 16, (-item[0][1]) // 16, item[0])):
            native_z = -z
            if not level.has_chunk(x // 16, native_z // 16, 'minecraft:overworld'):
                continue
            key = x // 16, native_z // 16
            if key != active_chunk:
                level.unload()
                active_chunk = key
            chunk = level.get_chunk(x // 16, native_z // 16, 'minecraft:overworld')
            low = min(ys) - 1
            high = max(max(ys) + 2, round(component['floor_elevation_m']) + 3)
            for y in range(low, high + 1):
                read_cells += 1
                if read_cells > MAX_READ_CELLS:
                    raise ValueError('Native access readback budget exceeded')
                block = chunk.block_palette[int(chunk.blocks[x % 16, y + offset, native_z % 16])]
                form = collision(block)
                if form:
                    bottom, top, bearing = form
                    columns.setdefault((x, z), []).append((2 * y + bottom, 2 * y + top,
                                                           None if bearing is None else 2 * y + bearing))
    finally:
        level.close()
    scene = Scene(columns, bounds)
    local_spawn = spawn[0], -spawn[2], 2 * (spawn[1] - offset)
    supported = scene.standing(local_spawn)
    if not supported:
        raise ValueError('Saved review spawn lacks bearing support or two metres of headroom')
    mapped = _mapped_nodes(scene, paths, records)
    from_path, from_spawn = _flood(scene, mapped), _flood(scene, [local_spawn])
    openings, usable = _openings(scene, component, footprint)
    source = {opening['id']: opening for opening in component['access_openings']}
    exterior = _exterior_predicate(footprint)
    for opening in openings:
        nodes = {tuple(p) for p in opening['usable_nodes_x_z_half_y']}
        columns = {tuple(p) for p in source[opening['id']]['columns_local_xz']}
        exterior_path = _flood(scene, [p for p in mapped if exterior(p)],
                               lambda p: exterior(p) or (p[0], p[1]) in columns)
        opening['reachable_from_mapped_path'] = bool(nodes & from_path)
        opening['reachable_from_spawn'] = bool(nodes & from_spawn)
        crossing = {tuple(p) for p in opening['crossing_nodes_x_z_half_y']}
        opening['exterior_route_from_mapped_path'] = bool(crossing & exterior_path)
        opening['walkthrough'] = _walkthrough(scene, local_spawn, crossing, columns, footprint,
                                               2 * round(component['floor_elevation_m']), offset)
    routes = prepared['routes']
    verified_routes = 0
    for route in routes:
        if not (all(scene.standing(p) for p in route)
                and all(scene.transition(a, b) for a, b in zip(route, route[1:]))
                and route[0] in usable and route[-1] in mapped and route[0] in from_spawn):
            raise ValueError('Saved estimated access route is blocked, unsupported or disconnected')
        verified_routes += 1
    route_verified = bool(routes and verified_routes == len(routes))
    unresolved = [opening['id'] for opening in openings
                  if not opening['exterior_route_from_mapped_path'] or not opening['reachable_from_spawn']
                  or opening['walkthrough']['status'] != 'native_route_ready']
    connected = any(opening['id'] not in unresolved for opening in openings)
    report['status'] = ('route_verified' if route_verified else 'existing_access_verified') if connected else 'access_unresolved'
    if connected and unresolved:
        report['status'] += '_with_unresolved_openings'
    report['native_readback'] = {'status': 'completed', 'sampled_blocks': read_cells,
        'coordinate_frame': 'Routes use local x, north-positive z, and half-unit local Y; native z is negated and native Y includes the export offset.',
        'spawn_native_xyz': spawn, 'spawn_supported': supported, 'spawn_headroom_m': 2,
        'spawn_on_mapped_path': local_spawn in mapped, 'route_verified': route_verified,
        'verified_approach_routes': verified_routes,
        'interior_connected_to_path_and_spawn': connected,
        'openings': openings, 'unresolved_opening_ids': unresolved,
        'minecraft_visual_inspection': 'not_performed'}
    report['native_readback']['audit_scope'] = prepared.get('audit_scope', 'component_neighbourhood')
    report['native_readback']['bounds_local_xz'] = list(bounds)
    if whole_area:
        from .pilot_navigation import inspect, write
        report['whole_area_navigation'] = inspect(scene, local_spawn, mapped, paths, records, offset,
                                                 prepared.get('withheld_feature_ids', []))
        write(world_path.parent, report['whole_area_navigation'], footprint)
    (world_path.parent / 'access-review.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    _write_svg(world_path.parent / 'access-review.svg', prepared)
    return report


def _write_svg(path, prepared):
    """A standalone plan/profile diagram of the audited route, not a game render."""
    footprint, report = prepared['footprint'], prepared['report']
    route = prepared['route'] or []
    openings = report['native_readback']['openings']
    xmin, zmin, xmax, zmax = footprint.bounds
    points = [(p[0] + .5, p[1] + .5) for candidate in prepared['routes'] for p in candidate]
    if points:
        xmin, xmax = min(xmin, *(p[0] for p in points)), max(xmax, *(p[0] for p in points))
        zmin, zmax = min(zmin, *(p[1] for p in points)), max(zmax, *(p[1] for p in points))
    xmin, zmin, xmax, zmax = xmin - 3, zmin - 3, xmax + 3, zmax + 3
    scale = min(430 / (xmax - xmin), 420 / (zmax - zmin))
    def point(x, z):
        return 35 + (x - xmin) * scale, 100 + (zmax - z) * scale
    def cell(x, z, colour):
        px, pz = point(x, z + 1)
        return f'<rect x="{px:.2f}" y="{pz:.2f}" width="{scale:.2f}" height="{scale:.2f}" fill="{colour}"/>'
    def label(x, y, text, size=14, colour='#263238'):
        return f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="{colour}">{escape(str(text))}</text>'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="700" viewBox="0 0 1100 700">',
           '<rect width="1100" height="700" fill="white"/>',
           label(35, 32, 'Provisional building doorway access review', 23),
           label(35, 59, 'Saved-world collision checks. Estimated placement, floor and approach; no in-game inspection.'),
           label(35, 88, 'Plan: local north up', 16)]
    for x, _, z in sorted(prepared['paths']):
        if xmin <= x <= xmax and zmin <= z <= zmax:
            svg.append(cell(x, z, '#c5cbd0'))
    coords = ' '.join(f'{x:.2f},{z:.2f}' for x, z in [point(x, z) for x, z in footprint.exterior.coords])
    svg.append(f'<polygon points="{coords}" fill="#f2dfc1" stroke="#6d4c41" stroke-width="2"/>')
    source = {o['id']: o for o in prepared['component']['access_openings']}
    for opening in openings:
        colour = '#207d49' if opening['id'] not in report['native_readback']['unresolved_opening_ids'] else '#c62828'
        for x, z in source[opening['id']]['columns_local_xz']:
            svg.append(cell(x, z, colour))
    if route:
        for candidate in prepared['routes']:
            coords = ' '.join(f'{x:.2f},{z:.2f}' for x, z in [point(x + .5, z + .5) for x, z, _ in candidate])
            colour = '#087da3' if candidate == route else '#5baab5'
            svg.append(f'<polyline points="{coords}" fill="none" stroke="{colour}" stroke-width="3"/>')
        for index, node in enumerate(route):
            px, pz = point(node[0] + .5, node[1] + .5)
            svg.append(f'<circle cx="{px:.2f}" cy="{pz:.2f}" r="3" fill="#087da3"/>')
            if index == len(route) - 1:
                svg.append(label(round(px + 7, 2), round(pz + 5, 2), 'spawn / mapped path', 12))
        svg.append(label(535, 105, 'Route profile: threshold to mapped path', 17))
        heights = [p[2] / 2 for p in route]
        ground = [prepared['terrain'][p[0], p[1]] + 1 for p in route]
        low, high = min(ground + heights) - .5, max(ground + heights) + 1
        sx = 480 / len(route)
        sy = 290 / (high - low)
        def profile_y(value):
            return 425 - (value - low) * sy
        for height in range(math.ceil(low), math.floor(high) + 1):
            py = profile_y(height)
            svg.append(f'<path d="M555 {py:.2f} H1035" stroke="#e4e7ea"/>')
            svg.append(label(515, round(py + 4, 2), height, 12))
        for index, (height, terrain_height) in enumerate(zip(heights, ground)):
            px = 555 + index * sx
            py = profile_y(terrain_height)
            svg.append(f'<rect x="{px:.2f}" y="{py:.2f}" width="{sx:.2f}" height="{425 - py:.2f}" fill="#d4dfca"/>')
            ry = profile_y(height)
            if height > terrain_height:
                svg.append(f'<rect x="{px:.2f}" y="{ry:.2f}" width="{sx:.2f}" height="{py - ry:.2f}" fill="#e6a449"/>')
            svg.append(f'<path d="M{px:.2f} {ry:.2f} h{sx:.2f}" stroke="#087da3" stroke-width="3"/>')
            if index:
                previous = profile_y(heights[index - 1])
                svg.append(f'<path d="M{px:.2f} {previous:.2f} V{ry:.2f}" stroke="#087da3" stroke-width="3"/>')
        svg += [label(555, 453, 'Green: existing terrain | Amber: support above terrain', 12),
                label(555, 476, 'Blue: verified standing surface; maximum step 0.5 m', 12),
                label(535, 505, f"Primary route {len(route) - 1} m; {report['approach']['added_voxel_records']} total added access blocks; no excavation.", 13),
                label(535, 532, f"Verified external approach routes: {report['native_readback']['verified_approach_routes']}", 14)]
        raster = prepared['component'].get('native_mesh_audit', {}).get('doorway_rasterization', {})
        narrow = [o for o in raster.get('openings', []) if o['source_width_m'] < 1 and o['native_cell_envelope_width_m']]
        if narrow:
            opening = narrow[0]
            svg.append(label(535, 555, f"Narrow study span {opening['source_width_m']:.3f} m; cell envelope {opening['native_cell_envelope_width_m']:.3f} m (approx.).", 12))
    else:
        svg.append(label(535, 140, 'No constructed route requested or found. See JSON audit.', 15))
    unresolved = ', '.join(report['native_readback']['unresolved_opening_ids']) or 'none under this rule'
    svg += [label(35, 575, 'Grey: mapped paving | Brown: study footprint | Green: exterior-connected opening | Red: unresolved', 13),
            label(35, 606, 'Audit: ' + report['status'], 15),
            label(35, 634, 'Unresolved: ' + unresolved, 14, '#a52222'),
            label(35, 669, 'Schematic only. One-player route; no site access design, survey accuracy or accessible-design certification.', 13),
            '</svg>']
    path.write_text('\n'.join(svg) + '\n', encoding='utf-8')
