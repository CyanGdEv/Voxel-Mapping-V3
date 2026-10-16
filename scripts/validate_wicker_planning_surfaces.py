"""Cold-check planning paving against the retained slab-join world and a fresh replay.

Read both packaged Bedrock databases, including air through the full build height.
Permit only same-height paving finishes and changes to estimated buffer vegetation.
This records native checks, never a Minecraft gameplay pass or surveyed acceptance.
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

from voxel_mapper.bedrock import material_block, record_priority
from voxel_mapper.pilot_access import (SURFACE_POLICY, WALKING_KINDS, _mapped_nodes,
                                       _read_inputs, _scene, collision)
from validate_wicker_path_steps import digest, load, _route, _clear

DIMENSION = 'minecraft:overworld'
REPLAY_FILES = ('inputs.json', 'voxels.jsonl', 'features-local.geojson', 'review-component.json',
                'access-review.json', 'navigation-review.json', 'navigation-review.svg',
                'path-steps-review.json', 'context-review.json', 'placement-comparison.json',
                'planning-surfaces-review.json', 'planning-surfaces-source.geojson',
                'planning-surfaces-local.geojson')


def _feed(directory):
    retained, context, paving = hashlib.sha256(), {}, {}
    count = 0
    with (directory / 'voxels.jsonl').open('rb') as stream:
        for line in stream:
            row = json.loads(line)
            key = row['x'], row['y'], row['z']
            if row.get('review_surface_policy') == SURFACE_POLICY:
                assert row['accepted_physical_geometry'] is False
                assert row['finished_level_verified'] is False
                assert key not in paving
                paving[key] = row
            elif row.get('shape_status') == 'estimated_fence_and_noise_foliage':
                assert row['accepted_physical_geometry'] is False
                if key not in context or record_priority(row) > record_priority(context[key]):
                    context[key] = row
            else:
                retained.update(line)
                count += 1
    return retained.hexdigest(), count, context, paving


def _material(level, key, offset, row):
    x, y, z = key
    actual = level.get_block(x, y + offset, -z, DIMENSION)
    expected = material_block(row['material'])
    assert actual.namespaced_name == expected.namespaced_name, key
    assert all(actual.properties.get(k) == v for k, v in expected.properties.items()), key
    return actual


def validate(before, after, replay):
    old, new = load(before / 'pilot-report.json'), load(after / 'pilot-report.json')
    old_assets = {row['role']: row for row in old['inputs']['assets']}
    new_assets = {row['role']: row for row in new['inputs']['assets']}
    assert all(new_assets[key] == value for key, value in old_assets.items())
    assert old['world']['spawn'] == new['world']['spawn']
    offset = new['world']['vertical_offset_blocks']
    assert old['world']['vertical_offset_blocks'] == offset
    a_feed, a_count, a_context, a_paving = _feed(before)
    b_feed, b_count, b_context, paving = _feed(after)
    assert (a_feed, a_count) == (b_feed, b_count) and not a_paving
    assert (before / 'review-component.json').read_bytes() == (after / 'review-component.json').read_bytes()
    assert new['readiness']['planning_components_voxelized'] == 0
    report = new['planning_surfaces_review']
    assert report['accepted_physical_geometry'] is False and report['training_labels_generated'] == 0
    assert report['extraction']['source_plaza_labels'] == report['labelled_plaza_features'] == 3
    assert report['extraction']['unmatched_plaza_labels'] == []
    assert report['placement']['scale_adjusted_to_fit_map'] is False
    assert report['placement']['registration_verified'] is False
    assert len(paving) == report['added_paving_records']
    for name, sha in new['output_sha256'].items():
        assert digest(after / name) == sha, name
    assert digest(after / 'park.mcworld') == new['world']['sha256']
    for name in REPLAY_FILES:
        assert (after / name).read_bytes() == (replay / name).read_bytes(), name
    forms = load(after / 'playtest-results.json')
    assert forms['world']['sha256'] == new['world']['sha256']
    assert all(check['outcome'] == 'not_run' for check in forms['checks'])
    assert sum(check['id'].startswith('plaza/') for check in forms['checks']) == 3
    withheld = old['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert withheld == new['access_review']['whole_area_navigation']['withheld_feature_ids_not_audited_as_geometry']
    assert len(withheld) == 9
    assert all(row['emitted_voxel_records'] == 0 for row in new['geographic_features'] if row['id'] in withheld)
    old_records, terrain, paths, bounds = _read_inputs(before, old['review_component'], whole_area=True)
    old_mapped = _mapped_nodes(_scene(old_records, bounds), paths, old_records)
    assert len(old_mapped) == new['access_review']['whole_area_navigation']['mapped_supported_cells']
    local_features = load(after / 'planning-surfaces-local.geojson')['features']
    polygons = {row['id']: shape(row['geometry']) for row in local_features}
    for key, row in paving.items():
        assert old_records[key]['kind'] in WALKING_KINDS | {'terrain'}, key
        assert terrain[key[0], key[2]] == key[1]
        assert polygons[row['feature']].covers(Point(key[0]+.5,key[2]+.5)), key
    expected = {(x, y + offset, -z) for x, y, z in paving}
    vegetation = {(x, y + offset, -z) for x, y, z in a_context.keys() | b_context.keys()}
    for key in a_context.keys() | b_context.keys():
        assert old_records.get(key, {}).get('shape_status') == 'estimated_fence_and_noise_foliage' or key not in old_records
    cells, changed_paving, changed_context, route_points, route_count = 0, set(), set(), 0, 0
    with tempfile.TemporaryDirectory(prefix='planning-paving-cold-check-') as temporary:
        root = Path(temporary)
        for name, directory in [('before', before), ('after', after)]:
            with zipfile.ZipFile(directory / 'park.mcworld') as archive:
                archive.extractall(root / name)
        embedded = load(root / 'after/voxel-quality-report.json')
        assert embedded['planning_surfaces_review'] == report
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
                for section in range(-4, 20):
                    aa = (lookup_a[ca.blocks.get_sub_chunk(section)] if section in ca.blocks.sub_chunks
                          else np.zeros((16, 16, 16), dtype=int))
                    bb = (lookup_b[cb.blocks.get_sub_chunk(section)] if section in cb.blocks.sub_chunks
                          else np.zeros((16, 16, 16), dtype=int))
                    cells += aa.size
                    for x, y, z in np.argwhere(aa != bb):
                        point = cx * 16 + int(x), section * 16 + int(y), cz * 16 + int(z)
                        if point in expected:
                            assert collision(ca.block_palette[int(ca.blocks[x, section * 16 + y, z])]) == (0,2,2)
                            assert collision(cb.block_palette[int(cb.blocks[x, section * 16 + y, z])]) == (0,2,2)
                            changed_paving.add(point)
                        else:
                            assert point in vegetation, point
                            changed_context.add(point)
                a.unload(); b.unload()
            for key, row in paving.items():
                _material(b, key, offset, row)
            for x, z, height in old_mapped:
                feet = height / 2 + offset
                by = math.floor(feet - 1e-7)
                form = collision(b.get_block(x, by, -z, DIMENSION))
                assert form and form[2] is not None and by + form[2] / 2 == feet
                assert _clear(b, x, -z, feet)
            stored = b.level_wrapper.root_tag.compound
            assert [int(stored['Spawn' + axis]) for axis in 'XYZ'] == new['world']['spawn']
            component = new['review_component']
            features = load(after / 'features-local.geojson')['features']
            footprint = shape(next(row['geometry'] for row in features if row['id'] == component['feature_id']))
            openings = {row['id']: row for row in component['access_openings']}
            for opening in new['access_review']['native_readback']['openings']:
                route = opening['walkthrough']
                assert route['status'] == 'native_route_ready'
                route_points += _route(b, route, offset); route_count += 1
                columns = {tuple(p) for p in openings[opening['id']]['columns_local_xz']}
                for x, z, _ in route['route_local_x_z_half_y'][:route['doorway_index'] + 1]:
                    assert (x,z) in columns or not footprint.intersects(box(x,z,x+1,z+1))
                x, z, height = route['route_local_x_z_half_y'][-1]
                assert footprint.buffer(-1).contains(Point(x+.5,z+.5))
                assert height == 2 * round(component['floor_elevation_m'])
            for route in new['access_review']['whole_area_navigation']['walkthroughs']:
                route_points += _route(b, route, offset); route_count += 1
            for feature in report['features']:
                if feature['surface_role'] != 'labelled_plaza':
                    continue
                route = feature['walkthrough']
                assert route['status'] == 'native_route_ready'
                route_points += _route(b, route, offset); route_count += 1
        finally:
            for level in levels:
                level.close()
    return {'version': 'wicker-planning-paving-cold-check-v1', 'status': 'passed',
            'baseline_world_sha256': old['world']['sha256'], 'world_sha256': new['world']['sha256'],
            'world_spawn_native_xyz': new['world']['spawn'], 'original_input_assets_unchanged': True,
            'source_and_slab_records_byte_identical': True, 'retained_source_row_count': a_count,
            'source_component_byte_identical': True, 'native_cells_compared': cells,
            'native_height_range_inclusive': [-64,319], 'native_changed_paving_cells': len(changed_paving),
            'native_changed_estimated_vegetation_cells': len(changed_context),
            'native_changes_outside_paving_and_estimated_vegetation': 0,
            'native_paving_materials_checked': len(paving), 'original_mapped_supports_checked': len(old_mapped),
            'native_route_count': route_count, 'native_route_points_checked': route_points,
            'all_entrance_prefixes_remain_exterior': True, 'replay_identical_files': list(REPLAY_FILES),
            'artifact_hashes_checked': len(new['output_sha256']),
            'withheld_feature_ids_remain_without_geometry': withheld,
            'planning_paving': {key: report[key] for key in ('recovered_features','labelled_plaza_features',
                'added_paving_records','mapped_paving_finish_cells','terrain_heights_modified','native_readback')},
            'plazas': [row for row in report['features'] if row['surface_role']=='labelled_plaza'],
            'minecraft_playtest': 'not_performed', 'accepted_physical_geometry': False, 'training_labels_generated': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','replay','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    result = validate(args.before,args.after,args.replay)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({key:result[key] for key in ('status','native_cells_compared','native_paving_materials_checked','native_route_points_checked')}))


if __name__=='__main__': main()
