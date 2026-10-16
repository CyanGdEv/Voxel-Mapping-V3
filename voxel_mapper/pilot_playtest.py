"""Write a pending human walkthrough for the exact exported pilot world."""
import hashlib
import json
from pathlib import Path

VERSION = 'pilot-playtest-v1'
ARTIFACTS = ['playtest-guide.md', 'playtest-routes.json', 'playtest-results.json']


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def _coordinates(point):
    return ' '.join(f'{value:g}' for value in point)


def write(output, report):
    """Native routes are test instructions, never completed gameplay reviews."""
    output = Path(output)
    world = report['world']
    with (output / 'park.mcworld').open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != world['sha256']:
            raise ValueError('Play-test world checksum mismatch')
    binding = {key: world[key] for key in ('file', 'sha256', 'target_version', 'spawn')}
    access = (report.get('access_review') or {}).get('native_readback', {})
    navigation = (report.get('access_review') or {}).get('whole_area_navigation')
    paving = report.get('planning_surfaces_review')
    plaza_entrances = (report.get('planning_paving_joins_review') or {}).get('plaza_entrance_connections',[])
    plazas = [{**feature['walkthrough'], 'feature_id': feature['feature_id'],
               'supported_cells': feature['native_supported_footprint_cells'],
               'reachable_cells_on_walking_surfaces': feature['reachable_cells_on_walking_surfaces']}
              for feature in paving['features'] if feature['surface_role'] == 'labelled_plaza'] if paving else []
    routes = []
    checks = [
        {'id': 'world-import', 'title': 'World imports and loads in Minecraft Bedrock'},
        {'id': 'spawn-standing', 'title': 'Player stands at spawn with clear headroom'},
        {'id': 'mapped-surfaces', 'title': 'Mapped paths and estimated steps are usable on foot'},
        {'id': 'building-exterior', 'title': 'Inspect building walls, roof and visible gaps'},
    ]
    if not report.get('review_component'):
        checks = [check for check in checks if check['id'] != 'building-exterior']
    if report.get('context_review'):
        checks += [
            {'id': 'context-terrain', 'title': 'Inspect the transition from the original area into buffered terrain'},
            {'id': 'context-vegetation', 'title': 'Check that woodland proxies leave mapped paths clear'},
        ]
    if report.get('path_steps_review'):
        checks.append({'id': 'path-step-joins',
                       'title': 'Walk the estimated slab joins in both directions without jumping'})
    if report.get('planning_paving_joins_review'):
        checks.append({'id':'planning-paving-joins',
                       'title':'Walk the planning paving joins uphill and downhill without jumping'})
    for opening in access.get('openings', []):
        witness = opening['walkthrough']
        ready = (witness['status'] == 'native_route_ready'
                 and opening['id'] not in access['unresolved_opening_ids'])
        routes.append({'opening_id': opening['id'], 'status': 'ready_to_test' if ready else 'unresolved',
                       **{key: witness[key] for key in ('doorway_index', 'horizontal_length_m',
                           'route_local_x_z_half_y', 'route_native_xyz')}})
        checks.append({'id': 'entrance/' + opening['id'],
                       'title': 'Walk from spawn through ' + opening['id'] + ' and back without flying',
                       'native_route_status': 'ready_to_test' if ready else 'unresolved'})
    checks.append({'id': 'terrain-edge', 'title': 'Inspect terrain edges and omitted elevated paths'})
    if navigation:
        checks.append({'id': 'whole-area-obstacles', 'title': 'Inspect disconnected walking components and steps across the full area'})
        checks += [{'id': 'site/' + route['id'], 'title': 'Walk the site route: ' + route['id']}
                   for route in navigation['walkthroughs']]
    checks += [{'id': 'plaza/' + route['feature_id'],
                'title': 'Walk from spawn to planning plaza ' + route['feature_id'].rsplit('/', 1)[1] + ' and back',
                'surface_scope': route['surface_scope']} for route in plazas]
    checks += [{'id':'plaza-entrance/'+r['plaza_feature_id']+'/'+r['opening_id'],
                'title':'Walk from plaza '+r['plaza_feature_id'].rsplit('/',1)[1]+' through '+r['opening_id'],
                'native_route_status':'ready_to_test' if r['status']=='native_route_ready' else 'unresolved'}
               for r in plaza_entrances]
    results = {'version': VERSION, 'world': binding, 'status': 'awaiting_minecraft_playtest',
               'observer': {'name': None, 'platform': None, 'minecraft_version': None, 'tested_at_utc': None},
               'checks': [{**check, 'outcome': 'not_run', 'notes': '', 'evidence_reference': None}
                          for check in checks],
               'review_scope': 'Human gameplay observations of this export; not physical placement or training labels.',
               'training_labels_generated': 0, 'accepted_physical_geometry': False}
    _write(output / 'playtest-results.json', results)
    _write(output / 'playtest-routes.json', {'version': VERSION, 'world': binding,
        'coordinate_frame': 'Native block-centred Minecraft X/Y/Z; Y is feet height including half slabs.',
        'basis': 'Bounded conservative routes traced from reopened native blocks; not in-game physics.',
        'routes': routes, 'site_routes': navigation['walkthroughs'] if navigation else [], 'planning_plaza_routes': plazas,
        'plaza_entrance_routes':plaza_entrances})
    spawn = world['spawn']
    spawn_command = '/tp @s ' + _coordinates([spawn[0] + .5, spawn[1], spawn[2] + .5])
    version = '.'.join(map(str, world['target_version']))
    guide = [
        '# Minecraft walkthrough', '',
        'Import `park.mcworld` into Minecraft Bedrock. This export targets ' + version +
        '; record the version you actually test. Java Edition does not open this format.', '',
        '**World SHA256:** `' + world['sha256'] + '`', '',
        'Keep an untouched copy of this package. Importing or saving in Minecraft can change its bytes. '
        'Edit a copy of `playtest-results.json` to record observations for the original export.', '',
        '## Spawn and movement', '',
        'Load the world, enable coordinates in Settings, and check that the player stands above the path. '
        'The world opens in Creative. To test walking without flight, run these chat commands separately:', '',
        '```text', spawn_command, '/gamemode adventure', '```', '',
        'Walk the routes below without jumping or flying. Follow each point in order and return the same way. '
        'The route check allows half-block steps and two metres of headroom. '
        'If movement fails, record the position and a screenshot reference. '
        'Use `/gamemode creative` after the walking checks to inspect the exterior and roof.', '',
        '## Entrances', '',
    ]
    if not routes:
        guide += ['No declared entrance walkthroughs are available for this export.', '']
    if report.get('context_review'):
        context = report['context_review']
        guide += ['Woodland context outside the original area contains ' + str(context['tree_count']) +
                  ' estimated trees and ' + str(context['shrub_clusters']) +
                  ' shrub clusters. Inspect the terrain transition and path clearance separately. '
                  'Tree positions within woodland, shapes and species are visual estimates.', '']
    for route in routes:
        guide += ['### ' + route['opening_id'], '']
        if route['status'] != 'ready_to_test':
            guide += ['Unresolved by native checks. No complete walking route is claimed; record any observations.', '']
            continue
        points = route['route_native_xyz']
        guide += [f"Route length: {route['horizontal_length_m']} m. Point 0 is spawn; "
                  f"point {route['doorway_index']} is the entrance crossing; the final point is inside.", '',
                  'Reset to spawn with `' + spawn_command + '` before each route.', '',
                  '| Point | X | Feet Y | Z | Position |', '| ---: | ---: | ---: | ---: | --- |']
        for index, (x, y, z) in enumerate(points):
            label = ('Spawn' if index == 0 else 'Entrance crossing' if index == route['doorway_index']
                     else 'Inside' if index == len(points) - 1 else '')
            guide.append(f'| {index} | {x:g} | {y:g} | {z:g} | {label} |')
        guide.append('')
    if plazas:
        guide += ['## Planning plazas', '',
                  'These footprints come from a proposed planning sheet. Placement and paving levels remain '
                  'provisional; materials use the recorded drawing labels or display rules. '
                  'The paving follows retained terrain rather than verified finished levels. '
                  'A route that uses other surfaces does not establish a continuous paved connection.', '']
        if report.get('planning_paving_joins_review'):
            guide += [str(report['planning_paving_joins_review']['added_slab_records']) +
                      ' estimated bottom stone slabs join existing planning paving at isolated full-block rises. '
                      'Inspect them uphill and downhill without jumping. Their source-cell links are in '
                      '`planning-paving-joins-review.json`. Proposed level claims are retained separately in '
                      '`planning-paving-levels-review.json`; none are applied as verified grading.', '']
        for route in plazas:
            guide += ['### Planning plaza ' + route['feature_id'].rsplit('/', 1)[1], '',
                      'Route scope: `' + route['surface_scope'] + '`. Supported footprint cells reached '
                      'while staying on walking surfaces: ' + str(route['reachable_cells_on_walking_surfaces']) +
                      '/' + str(route['supported_cells']) + '.', '']
            if route['status'] != 'native_route_ready':
                guide += ['No complete native route is available.', '']
                continue
            guide += [f"Length: {route['horizontal_length_m']} m. Reset with `{spawn_command}`.", '',
                      '| Point | X | Feet Y | Z |', '| ---: | ---: | ---: | ---: |']
            for i, (x, y, z) in enumerate(route['route_native_xyz']):
                guide.append(f'| {i} | {x:g} | {y:g} | {z:g} |')
            guide.append('')
    if plaza_entrances:
        guide += ['## Plaza to entrance walking checks','',
                  'First follow the matching spawn-to-plaza route above. From its final point, follow each route below. '
                  'The exterior prefix stays on walking surfaces and enters only the named opening; '
                  'its final points are on the declared interior floor. An unresolved result remains a gap.','']
        for route in plaza_entrances:
            guide += ['### Plaza '+route['plaza_feature_id'].rsplit('/',1)[1]+' to '+route['opening_id'],'']
            if route['status']!='native_route_ready':
                guide += ['Unresolved: no complete route on walking surfaces through this entrance is claimed.','']
                continue
            guide += [f"Length: {route['horizontal_length_m']} m. Entrance crossing at point {route['doorway_index']}.",'',
                      '| Point | X | Feet Y | Z |','| ---: | ---: | ---: | ---: |']
            for i,(x,y,z) in enumerate(route['route_native_xyz']):
                guide.append(f'| {i} | {x:g} | {y:g} | {z:g} |')
            guide.append('')
    if navigation:
        guide += ['## Whole-area walking', '',
                  'Open `navigation-review.svg` to inspect the complete area. Blue marks the spawn walking '
                  'component. Amber components can be reached using other surfaces, including terrain or '
                  'the building interior; red components are unresolved from spawn under this rule.', '',
                  f"Supported mapped cells reachable by any walking route: {navigation['mapped_reachable_cells_any_walking']}"
                  f"/{navigation['mapped_supported_cells']}. Reachable while staying on mapped walking surfaces "
                  f"and estimated approaches: {navigation['mapped_reachable_cells_on_walking_surfaces']}.", '',
                  'Missing/overridden cells and full-block steps remain separate findings in `navigation-review.json`. '
                  'An off-path route does not establish continuous paving. The sampled site routes below '
                  'are native checks; walk them in Adventure mode and record the result.', '']
        if report.get('path_steps_review'):
            steps = report['path_steps_review']
            guide += [str(steps['added_slab_records']) + ' estimated stone slabs raise selected mapped path cells '
                      'by half a metre. Inspect `path-steps-review.json` for each native block position. '
                      'Walk them uphill and downhill without jumping; the source terrain does not establish '
                      'real steps at these positions. Remaining barriers stay listed in the navigation report.', '']
        for route in navigation['walkthroughs']:
            guide += ['### Site route: ' + route['id'], '', route['surface_scope'] + '.', '',
                      f"Length: {route['horizontal_length_m']} m. Reset with `{spawn_command}`.", '',
                      '| Point | X | Feet Y | Z |', '| ---: | ---: | ---: | ---: |']
            for index, (x, y, z) in enumerate(route['route_native_xyz']):
                guide.append(f'| {index} | {x:g} | {y:g} | {z:g} |')
            guide.append('')
    guide += [
        '## Record the result', '',
        'Fill in the observer fields in `playtest-results.json`. For each check, set `outcome` to '
        '`pass`, `fail`, `blocked` or `not_run`, and add notes and an optional screenshot/reference. '
        'Record each entrance separately. A route that only works while flying has failed the walking check. '
        'The form starts with every check `not_run`; native checks do not complete it.', '',
        'Reported generation errors: ' + str(report['generation_errors']) +
        '. See `pilot-report.json` for the affected features and missing evidence.', '',
        'This provisional scene uses estimated placement and materials. The walkthrough checks gameplay; '
        'it does not verify surveyed position, floor datum, as-built identity or source dimensions. '
        'No play-test result is automatically used as an AI training label or physical acceptance.', '',
    ]
    (output / 'playtest-guide.md').write_text('\n'.join(guide), encoding='utf-8')
    return {'version': VERSION, 'status': 'awaiting_minecraft_playtest', 'world_sha256': world['sha256'],
            'ready_entrance_routes': sum(route['status'] == 'ready_to_test' for route in routes),
            'unresolved_entrance_routes': sum(route['status'] != 'ready_to_test' for route in routes),
            'ready_site_routes': len(navigation['walkthroughs']) if navigation else 0,
            'ready_plaza_routes': sum(route['status'] == 'native_route_ready' for route in plazas),
            'artifacts': list(ARTIFACTS), 'training_labels_generated': 0}
