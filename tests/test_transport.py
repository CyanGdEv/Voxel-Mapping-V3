import json
import tempfile
import unittest
from pathlib import Path

import amulet
import rasterio

from voxel_mapper.cli import build, parse_osm
from voxel_mapper.transport import width_metres, transport_profile, SURFACE_MATERIALS
from voxel_mapper.bedrock import export_world, material_block
import test_terrain_osm as fixtures


class TransportTests(unittest.TestCase):
    def test_material_normalization_and_ambiguous_surfaces(self):
        self.assertEqual(transport_profile({'surface':' Brick '}, 'path', False)['material'], 'bricks')
        self.assertEqual(transport_profile({'surface':'metal'}, 'path', False)['material'], 'iron_block')
        ambiguous = transport_profile({'surface':'asphalt;paving_stones'}, 'path', False)
        self.assertEqual(ambiguous['material_method'], 'assumed')
        self.assertTrue(transport_profile({'surface':'paved'}, 'path', False)['warnings'])
    def test_units_and_ambiguous_widths(self):
        for value, expected in [('3 m', 3), ('10 ft', 3.048), ('6\' 6"', 1.9812), (2.5, 2.5)]:
            self.assertAlmostEqual(width_metres(value), expected)
        for value in ('3;4', '2-4', 'nan', '-2', '0', '200', '6\' 14"'):
            with self.assertRaises(ValueError):
                width_metres(value)

    def test_estimated_width_is_not_a_measurement_or_maxwidth(self):
        profile = transport_profile({'width':'2;3','est_width':'3 m','maxwidth':'9','surface':'gravel'}, 'path', True)
        self.assertEqual(profile['width_m'], 3)
        self.assertEqual(profile['width_source'], 'est_width')
        self.assertIn('mapped width is an estimate', profile['warnings'])
        profile = transport_profile({'maxwidth':'9'}, 'road', True)
        self.assertEqual(profile['width_m'], 6)
        self.assertEqual(profile['width_source'], 'class_default_assumed')
        self.assertEqual(profile['material_method'], 'assumed')

    def test_osm_classes_areas_and_inactive_omissions(self):
        tags = [{'highway':'service'}, {'highway':'footway'},
                {'highway':'footway','footway':'sidewalk'}, {'highway':'footway','queue':'yes'},
                {'highway':'cycleway'}, {'highway':'steps'}, {'area:highway':'pedestrian'},
                {'highway':'construction'}]
        elements = [{'type':'way','id':i,'tags':tag,'geometry':[{'lon':x,'lat':y} for x,y in [(0,0),(1,0),(1,1),(0,0)]]} for i,tag in enumerate(tags)]
        collection, skipped = parse_osm({'elements':elements})
        self.assertEqual([f['properties']['kind'] for f in collection['features']], ['road','path','sidewalk','queue','cycleway','steps','path'])
        self.assertEqual(collection['features'][0]['geometry']['type'], 'LineString')
        self.assertEqual(collection['features'][-1]['geometry']['type'], 'Polygon')
        self.assertEqual(len(skipped), 1)

    def test_fractional_ground_is_single_surface_and_material_survives_export(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config, features = fixtures.TerrainTests().fixture(root)
            with rasterio.open(config['terrain']['path'], 'r+') as raster:
                values = raster.read(1); values[:] = 25.7; raster.write(values, 1)
            features['features'][0]['properties'].update(highway='footway', surface='paving_stones')
            report = build(config, features, root/'out')
            records = [json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            paving = [r for r in records if r.get('feature') == 'path']
            self.assertEqual({r['y'] for r in paving}, {25})
            self.assertEqual(len(paving), len({(r['x'],r['z']) for r in paving}))
            self.assertEqual(report['transport_profiles'][0]['width_source'], 'mapped_polygon')
            self.assertEqual(report['issues'], [])
            world_report = export_world(root/'out/voxels.jsonl', root/'out', report)
            world = amulet.load_level(str(root/'out/bedrock-world'))
            try:
                record = paving[0]; x,z,y = record['x'], -record['z'], record['y']+world_report['vertical_offset_blocks']
                self.assertEqual(world.get_block(x,y,z,'minecraft:overworld').base_name, 'stone_bricks')
                self.assertEqual(world.get_block(x,y+1,z,'minecraft:overworld').base_name, 'air')
            finally:
                world.close()

    def test_tagged_width_changes_footprint_and_reports_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config, features = fixtures.TerrainTests().fixture(root)
            config['terrain']['emit_surface'] = False
            feature = features['features'][0]
            feature['geometry'] = {'type':'LineString','coordinates':[[.0003,.0005],[.0007,.0005]]}
            feature['properties'].update(highway='footway', width='2 m', surface='concrete')
            narrow = build(config, features, root/'narrow')
            feature['properties']['width'] = '6 m'
            wide = build(config, features, root/'wide')
            self.assertGreater(wide['voxel_records'], narrow['voxel_records']*2)
            self.assertEqual(wide['transport_profiles'][0]['width_source'], 'width')
            self.assertEqual(wide['transport_profiles'][0]['width_m'], 6)

    def test_all_surface_materials_round_trip_and_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = root/'voxels.jsonl'
            materials = sorted(set(SURFACE_MATERIALS.values()))
            path.write_text('\n'.join(json.dumps(dict(x=i,y=0,z=0,kind='path',material=m)) for i,m in enumerate(materials)))
            export_world(path, root/'valid', {'voxel_size_m':1})
            world = amulet.load_level(str(root/'valid/bedrock-world'))
            try:
                for i, material in enumerate(materials):
                    actual = world.get_block(i,64,0,'minecraft:overworld')
                    expected = material_block(material)
                    self.assertEqual(actual.namespaced_name, expected.namespaced_name)
                    for key, value in expected.properties.items():
                        self.assertEqual(actual.properties[key], value)
            finally:
                world.close()
            path.write_text(json.dumps(dict(x=0,y=0,z=0,kind='path',material='fake_block')))
            with self.assertRaisesRegex(ValueError, 'Unsupported block material'):
                export_world(path, root/'invalid', {'voxel_size_m':1})
            self.assertFalse((root/'invalid/park.mcworld').exists())
