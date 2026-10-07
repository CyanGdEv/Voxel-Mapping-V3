import json
import tempfile
import unittest
from pathlib import Path

import amulet
from amulet_nbt import StringTag

from voxel_mapper.cli import build
from voxel_mapper.bedrock import export_world
from voxel_mapper.planning_geometry import physical_features


class TunnelTests(unittest.TestCase):
    def fixture(self):
        ring = [[-.00005,-.00012],[.00005,-.00012],[.00005,.00012],[-.00005,.00012],[-.00005,-.00012]]
        config={'bbox':[-.001,-.001,.001,.001],'voxel_size_m':1,'max_area_m2':1_000_000,
                'sources':[{'id':'drawing','url':'https://example.test/drawing','license':'test-fixture'}],
                'terrain':{'vertical_datum':'fixture-datum'}}
        record={'id':'tunnel','source_id':'drawing','document_id':'fixture-plan','verification_reference':'fixture-control',
                'reuse_allowed':True,'registration_verified':True,'as_built_verified':True,
                'feature_type':'sound_tunnel','geometry':{'type':'Polygon','coordinates':[ring]},
                'centerline':{'type':'LineString','coordinates':[[0,-.00012],[0,.00012]]},
                'elevation':{'base_m':20,'top_m':26,'vertical_datum':'fixture-datum'},
                'section':{'shape':'flat_rectangular','floor_thickness_m':1,'roof_thickness_m':1,'wall_thickness_m':1,'clear_height_m':4},
                'structural_material':'dark_stained_timber'}
        return config,record

    def test_hollow_interior_open_portals_and_dark_timber_survive_world_export(self):
        config,record=self.fixture()
        normalized,decisions=physical_features([record],{'drawing':{}},config['bbox'],'fixture-datum')
        self.assertEqual(decisions[0]['status'],'accepted_verified_adapter_record')
        # This fixture has explicit heights, so a raster is unnecessary.
        config.pop('terrain')
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            report=build(config,{'features':normalized},output)
            rows=[json.loads(line) for line in (output/'voxels.jsonl').read_text().splitlines()]
            occupied={(r['x'],r['y'],r['z']) for r in rows if r.get('material')!='air'}
            self.assertIn((0,20,0),occupied)
            self.assertIn((0,25,0),occupied)
            self.assertNotIn((0,22,0),occupied)
            self.assertIn((5,22,0),occupied)
            self.assertNotIn((5,22,13),occupied)
            self.assertTrue(any(r['material']=='air' and r['x']==0 and r['y']==22 and r['z']==0 for r in rows))
            # A later terrain layer would fill the interior without explicit air
            # carving. Test the composed world, not just omitted voxel records.
            with (output/'voxels.jsonl').open('a') as stream:
                stream.write(json.dumps({'x':0,'y':24,'z':0,'kind':'terrain','source':'drawing'})+'\n')
            metadata=export_world(output/'voxels.jsonl',output,report)
            self.assertGreater(metadata['explicit_air_cells'],0)
            world=amulet.load_level(str(output/'bedrock-world'))
            try:
                offset=metadata['vertical_offset_blocks']
                self.assertEqual(world.get_block(0,22+offset,0,'minecraft:overworld').base_name,'air')
                material=world.get_block(5,22+offset,0,'minecraft:overworld')
                self.assertEqual(material.properties['material'],StringTag('dark_oak'))
            finally:world.close()

    def test_missing_height_and_unsupported_section_are_withheld(self):
        config,record=self.fixture();record.pop('elevation')
        features,decisions=physical_features([record],{'drawing':{}},config['bbox'],'fixture-datum')
        self.assertFalse(features)
        config,record=self.fixture();record['section']['shape']='unmeasured_arch'
        features,decisions=physical_features([record],{'drawing':{}},config['bbox'],'fixture-datum')
        self.assertFalse(features)
