"""Review retained placement hypotheses without generating or accepting park geometry."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.reconstruction.local_buildings import rotate_model
from voxel_mapper.shop_slabs import assemble
from voxel_mapper.shop_wall_details import decorate
from voxel_mapper.terrain import Terrain

PINS = {
    'model': '4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1',
    'lidar': 'b4d282fd2e9a14b27417f4db04951327fbac48224fa63281dd6e8260b02ace6f',
    'context': '58639eb20b641669aa9404e80b4dd00232b16b2caac242b18af7c484693013fd',
}


def terrain_clearance(cells, anchor, floor, ground):
    """Use the production adapter's snapped grid and terrain intersection rule."""
    columns = {}
    for x, y, z in cells:
        columns[x, z] = min(y, columns.get((x, z), y))
    missing = collisions = 0
    elevations = []
    for (x, z), lowest in sorted(columns.items()):
        value = ground(x + round(anchor[0]) + .5, z + round(anchor[1]) + .5)
        if value is None or not math.isfinite(value):
            missing += 1
            continue
        elevations.append(value)
        collisions += lowest + round(floor) <= math.floor(value)
    return {'sampled_columns': len(columns), 'missing_columns': missing,
            'intersecting_columns': collisions,
            'terrain_range_m': [min(elevations), max(elevations)] if elevations else None,
            'terrain_clearance_passed': missing == 0 and collisions == 0}


def review(model_path, lidar_path, context_path, terrain=None):
    inputs = {}
    for name, path in [('model', model_path), ('lidar', lidar_path), ('context', context_path)]:
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != PINS[name]:
            raise ValueError('Pinned ' + name + ' input changed')
        inputs[name] = json.loads(raw)
    model, lidar, context = (inputs[k] for k in ('model', 'lidar', 'context'))
    stable = next(e for e in lidar['envelopes'] if e['point_count'] == 505)
    ranks = next(e for e in context['envelopes'] if e['point_count'] == 505)['hypotheses_ranked_by_context']
    rows = []
    for h in sorted(stable['hypotheses'], key=lambda h: next(r['rear_to_mapped_station_centroid_angle_degrees'] for r in ranks if r['rotation_degrees'] == h['rotation_degrees'])):
        rank = next(r for r in ranks if r['rotation_degrees'] == h['rotation_degrees'])
        rotated = rotate_model(model, h['rotation_degrees'])
        cells, _ = assemble(rotated)
        cells, _ = decorate(rotated, cells)
        anchor = h['translation_bng_m']
        floor = h['implied_floor_offset_odn_m']['median']
        rows.append({'rotation_degrees': h['rotation_degrees'], 'context_preferred': rank['station_context_facing'],
                     'rear_to_station_angle_degrees': rank['rear_to_mapped_station_centroid_angle_degrees'],
                     'anchor_bng_m': anchor, 'mapped_centroid_to_fitted_origin_m': math.dist(anchor, context['shop_mapped_centroid_bng']),
                     'anchor_snap_offset_m': [round(v)-v for v in anchor],
                     'floor_self_fit_odn_m': floor, 'floor_snap_offset_m': round(floor)-floor,
                     'proposed_floor_label_m': 182.5, 'floor_label_datum_verified': False,
                     'voxel_cells': len(cells), 'materials': dict(sorted(Counter(cells.values()).items())),
                     'hypothetical_native_chunks': len({((x+round(anchor[0]))//16, (-(z+round(anchor[1])))//16) for x,y,z in cells}),
                     'terrain_clearance': terrain_clearance(cells, anchor, floor, terrain.sample) if terrain else None,
                     'boundary_review_flags': stable['boundary_review_flags'], 'placement_eligible': False})
    return {'status': 'placement_preflight_only', 'input_sha256': PINS,
            'terrain': terrain.report() if terrain else None, 'hypotheses': rows,
            'accepted_controls': 0, 'accepted_checkpoints': 0, 'world_geometry_additions': 0,
            'unresolved': ['Independent horizontal controls/checkpoints', 'Assembly identity and source handedness',
                           'Independent ODN floor datum', 'Shop-area terrain coverage and floor/grading review'],
            'limitations': ['Self-fitted roof heights are diagnostic candidates, not independent floor measurements.',
                            'Context ranking does not remove the opposite orientation.',
                            'Terrain checks inspect emitted block columns; entrance access, foundations and existing-world collisions need separate review.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['model', 'lidar', 'context', 'output']:
        p.add_argument('--'+name, required=True)
    p.add_argument('--terrain-config', help='JSON with terrain config and registered sources')
    a = p.parse_args()
    terrain = None
    try:
        if a.terrain_config:
            config_path = Path(a.terrain_config)
            config = json.loads(config_path.read_text())
            settings = dict(config['terrain'])
            settings['path'] = str((config_path.parent / settings['path']).resolve())
            terrain = Terrain(settings, 'EPSG:27700', {s['id']: s for s in config['sources']})
            if settings['vertical_datum'] != 'ODN':
                raise ValueError('Preflight floor comparison requires ODN terrain')
        result = review(a.model, a.lidar, a.context, terrain)
        Path(a.output).write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({'status': result['status'], 'hypotheses': len(result['hypotheses']), 'world_geometry_additions': 0}))
    finally:
        if terrain:
            terrain.close()


if __name__ == '__main__':
    main()
