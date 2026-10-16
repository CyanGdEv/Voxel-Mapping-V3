"""Cold-check a retained baseline, a slab-join export and its fresh replay.

Run from the repository with PYTHONPATH=. and the planning dependencies. This
checks native blocks and route instructions; it never records a gameplay pass.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
import zipfile

import amulet
from amulet.api.block import Block
import numpy as np
from shapely.geometry import Point, box, shape

from voxel_mapper.bedrock import material_block
from voxel_mapper.pilot_access import collision, PATH_STEP_FEATURE

DIMENSION = 'minecraft:overworld'
REPLAY_FILES = ('inputs.json', 'voxels.jsonl', 'features-local.geojson', 'review-component.json',
                'access-review.json', 'navigation-review.json', 'navigation-review.svg',
                'path-steps-review.json', 'context-review.json', 'placement-comparison.json')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(path.read_text())


def _clear(level, x, z, feet):
    for y in range(math.floor(feet) - 2, math.ceil(feet + 2)):
        form = collision(level.get_block(x, y, z, DIMENSION))
        if form and y + form[0] / 2 < feet + 2 and y + form[1] / 2 > feet:
            return False
    return True


def _route(level, route, offset):
    points = route['route_native_xyz']
    local = route['route_local_x_z_half_y']
    assert len(points) == len(local) and points
    for (x, feet, z), (lx, lz, lh) in zip(points, local):
        assert [x, feet, z] == [lx + .5, lh / 2 + offset, -lz + .5]
        bx, bz, by = math.floor(x), math.floor(z), math.floor(feet - 1e-7)
        form = collision(level.get_block(bx, by, bz, DIMENSION))
        assert form and form[2] is not None and by + form[2] / 2 == feet
        assert _clear(level, bx, bz, feet)
    for (x, y, z), (nx, ny, nz) in zip(points, points[1:]):
        assert abs(nx - x) + abs(nz - z) == 1 and abs(ny - y) <= .5
        assert _clear(level, math.floor(x), math.floor(z), max(y, ny))
        assert _clear(level, math.floor(nx), math.floor(nz), max(y, ny))
    return len(points)


def _standing_heights(level, x, z):
    heights = []
    for y in range(-64, 320):
        form = collision(level.get_block(x, y, z, DIMENSION))
        if form and form[2] is not None and _clear(level, x, z, y + form[2] / 2):
            heights.append(y + form[2] / 2)
    return heights


def validate(before, after, replay):
    old, new = load(before / 'pilot-report.json'), load(after / 'pilot-report.json')
    assert old['inputs']['assets'] == new['inputs']['assets']
    assert old['world']['spawn'] == new['world']['spawn']
    offset = new['world']['vertical_offset_blocks']
    assert old['world']['vertical_offset_blocks'] == offset
    old_feed = (before / 'voxels.jsonl').read_bytes().splitlines(keepends=True)
    new_feed = (after / 'voxels.jsonl').read_bytes().splitlines(keepends=True)
    retained, additions = [], []
    for line in new_feed:
        row = json.loads(line)
        if row.get('feature') == PATH_STEP_FEATURE:
            additions.append(row)
        else:
            retained.append(line)
    assert retained == old_feed
    assert 0 < len(additions) == new['path_steps_review']['verified_joins'] <= 512
    assert all(row['material'] == 'stone_slab' and row['accepted_physical_geometry'] is False for row in additions)
    assert (before / 'review-component.json').read_bytes() == (after / 'review-component.json').read_bytes()
    assert new['readiness']['planning_components_voxelized'] == 0
    for name, sha in new['output_sha256'].items():
        assert digest(after / name) == sha, name
    assert digest(after / 'park.mcworld') == new['world']['sha256']
    for name in REPLAY_FILES:
        assert (after / name).read_bytes() == (replay / name).read_bytes(), name
    forms = load(after / 'playtest-results.json')
    assert forms['world']['sha256'] == new['world']['sha256']
    assert all(check['outcome'] == 'not_run' for check in forms['checks'])
    assert new['path_steps_review']['training_labels_generated'] == 0
    assert new['path_steps_review']['accepted_physical_geometry'] is False
    withheld = old['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert withheld == new['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert len(withheld) == 9
    assert all(row['emitted_voxel_records'] == 0 for row in new['geographic_features'] if row['id'] in withheld)
    expected = {(row['x'], row['y'] + offset, -row['z']) for row in additions}
    assert len(expected) == len(additions)
    cells, changed, route_points, route_count, height_gaps = 0, set(), 0, 0, 0
    with tempfile.TemporaryDirectory(prefix='path-step-cold-check-') as temporary:
        root = Path(temporary)
        for name, directory in [('before', before), ('after', after)]:
            with zipfile.ZipFile(directory / 'park.mcworld') as archive:
                archive.extractall(root / name)
        embedded = load(root / 'after/voxel-quality-report.json')
        assert embedded['path_steps_review'] == new['path_steps_review']
        levels = []
        try:
            for name in ('before', 'after'):
                levels.append(amulet.load_level(str(root / name)))
            a, b = levels
            coordinates = set(a.all_chunk_coords(DIMENSION))
            assert coordinates == set(b.all_chunk_coords(DIMENSION))
            assert len(coordinates) == new['world']['chunks']
            palette = {Block('universal_minecraft', 'air'): 0}
            def canonical(block):
                return palette.setdefault(block, len(palette))
            for cx, cz in sorted(coordinates):
                ca, cb = a.get_chunk(cx, cz, DIMENSION), b.get_chunk(cx, cz, DIMENSION)
                lookup_a = np.array([canonical(block) for block in ca.block_palette])
                lookup_b = np.array([canonical(block) for block in cb.block_palette])
                for section in range(-4, 20):  # Full native -64..319 build height.
                    aa = (lookup_a[ca.blocks.get_sub_chunk(section)] if section in ca.blocks.sub_chunks
                          else np.zeros((16, 16, 16), dtype=int))
                    bb = (lookup_b[cb.blocks.get_sub_chunk(section)] if section in cb.blocks.sub_chunks
                          else np.zeros((16, 16, 16), dtype=int))
                    cells += aa.size
                    for x, y, z in np.argwhere(aa != bb):
                        point = cx * 16 + int(x), section * 16 + int(y), cz * 16 + int(z)
                        assert point in expected and aa[x, y, z] == 0, point
                        block = cb.block_palette[int(cb.blocks[x, section * 16 + y, z])]
                        slab = material_block('stone_slab')
                        assert block.namespaced_name == slab.namespaced_name
                        assert all(block.properties.get(k) == v for k, v in slab.properties.items())
                        changed.add(point)
                a.unload()
                b.unload()
            assert changed == expected
            cached_heights = {}
            for x, y, z in sorted(changed):
                for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
                    if not a.has_chunk(nx // 16, nz // 16, DIMENSION):
                        continue
                    if (nx, nz) not in cached_heights:
                        cached_heights[nx, nz] = _standing_heights(a, nx, nz)
                    for old_feet in cached_heights[nx, nz]:
                        if old_feet == y:
                            continue  # Flat edges may become half steps.
                        assert abs(y + .5 - old_feet) <= abs(y - old_feet)
                        assert _clear(b, nx, nz, old_feet)
                        height_gaps += 1
            stored = b.level_wrapper.root_tag.compound
            assert [int(stored['Spawn' + axis]) for axis in 'XYZ'] == new['world']['spawn']
            component = new['review_component']
            features = load(after / 'features-local.geojson')['features']
            footprint = shape(next(row['geometry'] for row in features if row['id'] == component['feature_id']))
            openings = {row['id']: row for row in component['access_openings']}
            for opening in new['access_review']['native_readback']['openings']:
                route = opening['walkthrough']
                assert route['status'] == 'native_route_ready'
                route_points += _route(b, route, offset)
                route_count += 1
                columns = {tuple(p) for p in openings[opening['id']]['columns_local_xz']}
                crossing = route['doorway_index']
                for x, z, _ in route['route_local_x_z_half_y'][:crossing + 1]:
                    assert (x, z) in columns or not footprint.intersects(box(x, z, x + 1, z + 1))
                x, z, height = route['route_local_x_z_half_y'][-1]
                assert footprint.buffer(-1).contains(Point(x + .5, z + .5))
                assert height == 2 * round(component['floor_elevation_m'])
            for route in new['access_review']['whole_area_navigation']['walkthroughs']:
                route_points += _route(b, route, offset)
                route_count += 1
        finally:
            for level in levels:
                level.close()
    return {'version': 'wicker-path-step-cold-check-v1', 'status': 'passed',
            'baseline_world_sha256': old['world']['sha256'], 'world_sha256': new['world']['sha256'],
            'world_spawn_native_xyz': new['world']['spawn'], 'source_input_assets_identical': True,
            'original_voxel_records_byte_identical': True, 'source_component_byte_identical': True,
            'native_cells_compared': cells, 'native_height_range_inclusive': [-64, 319],
            'native_changed_cells': len(changed), 'native_changes': 'Only previously empty cells became bottom stone slabs.',
            'native_original_blocks_modified_or_removed': 0, 'route_count': route_count,
            'native_nonzero_adjacent_height_gaps_checked': height_gaps,
            'preexisting_nonzero_adjacent_height_gaps_enlarged': 0,
            'native_route_points_checked': route_points, 'all_entrance_prefixes_remain_exterior': True,
            'replay_identical_files': list(REPLAY_FILES), 'artifact_hashes_checked': len(new['output_sha256']),
            'withheld_feature_ids_remain_without_geometry': withheld,
            'slab_review': {key: new['path_steps_review'][key] for key in ('before', 'native_after', 'verified_joins')},
            'minecraft_playtest': 'not_performed', 'accepted_physical_geometry': False, 'training_labels_generated': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'replay', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.before, args.after, args.replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: result[key] for key in ('status', 'native_cells_compared', 'native_changed_cells', 'native_route_points_checked')}))


if __name__ == '__main__':
    main()
