"""Build an explicitly provisional 1:1 shop/terrain section from pinned survey rasters."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.preflight_wicker_shop_placement import review, terrain_clearance
from voxel_mapper.bedrock import export_world
from voxel_mapper.reconstruction.local_buildings import rotate_model
from voxel_mapper.shop_slabs import assemble
from voxel_mapper.shop_wall_details import decorate
from voxel_mapper.survey import crop_pair
from voxel_mapper.terrain import Terrain

RASTER_PINS = {'dtm': '57becd3683c8492b645472d936ff0d714acd5d037326a6c6f0b6050e04eb2493',
               'dsm': 'caca385431739d291ab92f839e26840eee76650ab5593088a48dbfeac04907af'}
BOUNDS = [407461, 343478, 407603, 343627]


def pinned_archives(paths):
    archives = {}
    for kind in ('dtm', 'dsm'):
        path = Path(paths[kind])
        if path.stat().st_size > 100_000_000:
            raise ValueError('Survey archive exceeds budget')
        raw = path.read_bytes()
        name = f'{kind.upper()}_SK0540_P_10682_20220105_20220105.tif'
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [e for e in archive.infolist() if e.filename.lower().endswith('.tif')]
            if len(entries) != 1 or entries[0].filename != name or entries[0].file_size > 150_000_000:
                raise ValueError('One pinned dated survey raster required')
            if hashlib.sha256(archive.read(entries[0])).hexdigest() != RASTER_PINS[kind]:
                raise ValueError('Original survey raster checksum mismatch')
        archives[kind] = raw
    return archives


def candidate_cells(model, hypothesis):
    rotated = rotate_model(model, hypothesis['rotation_degrees'])
    cells, _ = assemble(rotated)
    cells, _ = decorate(rotated, cells)
    # The native export negates northing, as in the production adapter.
    for p, material in list(cells.items()):
        if material.endswith('_trapdoor_north'):
            cells[p] = material.removesuffix('_north')+'_south'
        elif material.endswith('_trapdoor_south'):
            cells[p] = material.removesuffix('_south')+'_north'
    return cells


def build(dtm, dsm, model_path, lidar_path, context_path, output, provisional_floor):
    if isinstance(provisional_floor, bool) or not math.isfinite(provisional_floor) or abs(provisional_floor)>10000:
        raise ValueError('Explicit finite provisional floor required')
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    if (out/'quality-report.json').exists() or (out/'park.mcworld').exists():
        raise ValueError('Refusing to overwrite a completed section')
    archives = pinned_archives({'dtm': dtm, 'dsm': dsm})
    survey = crop_pair(archives, BOUNDS, out, '2022', 'SK0540')
    settings = {'path': str((out/'ea-national-dtm.tif').resolve()), 'source_id': 'ea-dtm', 'units': 'm', 'vertical_datum': 'ODN'}
    config = {'terrain': {**settings, 'path': 'ea-national-dtm.tif'}, 'sources': [{'id': 'ea-dtm'}]}
    (out/'terrain-config.json').write_text(json.dumps(config, indent=2)+'\n')
    terrain = Terrain(settings, 'EPSG:27700', {'ea-dtm': {}})
    try:
        preflight = review(model_path, lidar_path, context_path, terrain)
        (out/'placement-preflight.json').write_text(json.dumps(preflight, indent=2)+'\n')
        hypothesis = preflight['hypotheses'][0]
        cells = candidate_cells(json.loads(Path(model_path).read_text()), hypothesis)
        anchor = hypothesis['anchor_bng_m']
        clearance = terrain_clearance(cells, anchor, provisional_floor, terrain.sample)
        if not clearance['terrain_clearance_passed']:
            raise ValueError('Provisional floor intersects terrain or lacks coverage; no excavation is inferred')
        rows = out/'voxels.jsonl'
        terrain_count = 0
        with rows.open('w') as stream:
            for z in range(BOUNDS[1], BOUNDS[3]):
                for x in range(BOUNDS[0], BOUNDS[2]):
                    ground = terrain.sample(x+.5, z+.5)
                    if ground is None:
                        raise ValueError('Section has missing ground; cannot invent elevation')
                    stream.write(json.dumps({'x': x, 'y': math.floor(ground), 'z': z, 'kind': 'terrain', 'material': 'grass_block'})+'\n')
                    terrain_count += 1
            for (x,y,z),material in sorted(cells.items()):
                stream.write(json.dumps({'x': x+round(anchor[0]), 'y': y+round(provisional_floor), 'z': z+round(anchor[1]),
                                        'kind': 'building', 'material': material})+'\n')
        sources = [{'id': 'ea-'+k, 'url': f'https://environment.data.gov.uk/tiles/collections/survey/national_lidar_programme_{k}/2022/1/SK0540',
                    'vertical_datum': 'ODN', 'license': 'OGL-UK-3.0', 'survey': survey,
                    'archive_sha256': hashlib.sha256(archives[k]).hexdigest(), 'original_raster_sha256': RASTER_PINS[k]} for k in ('dtm','dsm')]
        report = {'status': 'provisional_terrain_section_review', 'voxel_size_m': 1, 'model_blocks_per_source_metre': 1,
                  'crs': 'EPSG:27700', 'vertical_datum': 'ODN', 'sources': sources,
                  'bounds_bng_m': BOUNDS, 'terrain_columns': terrain_count, 'shop_cells': len(cells),
                  'shop_hypothesis': hypothesis, 'provisional_floor_m': provisional_floor,
                  'floor_shift_from_self_fit_m': provisional_floor-hypothesis['floor_self_fit_odn_m'],
                  'provisional_floor_clearance': clearance, 'accepted_controls': 0, 'accepted_checkpoints': 0,
                  'production_placement_eligible': False,
                  'spawn_local_xyz_m': [round(anchor[0])-18, round(provisional_floor)+3, round(anchor[1])-18],
                  'axis': {'x': 'BNG east', 'z': 'BNG north; native Z negated'},
                  'limitations': ['Provisional shop origin/orientation; no accepted independent registration.',
                                  'Review floor explicitly chosen for clearance; not a measured ODN floor.',
                                  'Terrain is the 2022-01-05 survey, not current ground.',
                                  'Grass material and exported subsurface foundation fill are illustrative.',
                                  'No paths, ride, station, lakes, internal floor or building foundations reconstructed.',
                                  'No terrain excavation, accepted placement, or full-park insertion performed.']}
        report['world'] = export_world(rows, out, report, name='Wicker Shop Terrain — PROVISIONAL floor '+str(provisional_floor), ground_depth=4)
        (out/'quality-report.json').write_text(json.dumps(report, indent=2)+'\n')
        (out/'README.txt').write_text('WICKER SHOP — PROVISIONAL 1:1 TERRAIN SECTION\n\nImport park.mcworld. Creative-mode spawn is beside the shop.\n'
                                    'Includes the 2022 terrain crop and context-preferred slab/fence/trapdoor shop hypothesis.\n'
                                    f'Review floor: {provisional_floor} m; roof self-fit: {hypothesis["floor_self_fit_odn_m"]:.3f} m.\n'
                                    'Floor/orientation are estimates for visual review. This is not accepted park placement.\n'
                                    'Read quality-report.json and placement-preflight.json for conflicts and source provenance.\n')
        return report
    finally:
        terrain.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('dtm','dsm','model','lidar','context','output'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--provisional-floor', type=float, required=True, help='Explicit review-only ODN grid floor; never inferred or accepted')
    a = p.parse_args()
    result = build(a.dtm, a.dsm, a.model, a.lidar, a.context, a.output, a.provisional_floor)
    print(json.dumps({'status': result['status'], 'shop_cells': result['shop_cells'], 'terrain_columns': result['terrain_columns'], 'world': result['world']}))


if __name__ == '__main__':
    main()
