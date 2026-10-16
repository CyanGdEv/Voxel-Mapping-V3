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
    routes = []
    checks = [
        {'id': 'world-import', 'title': 'World imports and loads in Minecraft Bedrock'},
        {'id': 'spawn-standing', 'title': 'Player stands at spawn with clear headroom'},
        {'id': 'mapped-surfaces', 'title': 'Mapped paths and estimated steps are usable on foot'},
        {'id': 'building-exterior', 'title': 'Inspect building walls, roof and visible gaps'},
    ]
    if not report.get('review_component'):
        checks = [check for check in checks if check['id'] != 'building-exterior']
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
        'routes': routes})
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
            'artifacts': list(ARTIFACTS), 'training_labels_generated': 0}
