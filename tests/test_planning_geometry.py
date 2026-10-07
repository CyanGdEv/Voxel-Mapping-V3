import copy
import json
import tempfile
import unittest
from pathlib import Path
import amulet
from amulet_nbt import StringTag
from voxel_mapper.planning_geometry import physical_features
from voxel_mapper.cli import build
from voxel_mapper.bedrock import export_world
import test_terrain_osm as fixtures


class PlanningGeometryTests(unittest.TestCase):
    def test_planning_material_overlays_osm_paving_preserving_holes_and_buildings(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,collection=fixtures.TerrainTests().fixture(root)
            config['terrain']['emit_surface']=False
            collection['features'][0]['properties'].update(highway='footway',surface='asphalt')
            geometry=copy.deepcopy(collection['features'][0]['geometry'])
            geometry['coordinates'].append([[.00047,.00047],[.00053,.00047],[.00053,.00053],[.00047,.00053],[.00047,.00047]])
            collection['planning_geometry_records']=[self.record(geometry)]
            report=build(config,collection,root/'build')
            rows=[json.loads(line) for line in (root/'build/voxels.jsonl').read_text().splitlines()]
            paving=[r for r in rows if r['kind']=='plaza']
            self.assertTrue(all(r.get('material_origin')=='accepted_planning_paving' for r in paving))
            protected=paving[-1]
            rows.append(dict(x=protected['x'],y=protected['y'],z=protected['z'],kind='building'))
            for reverse in (False,True):
                out=root/str(reverse);out.mkdir()
                path=out/'voxels.jsonl'
                path.write_text('\n'.join(json.dumps(r) for r in (list(reversed(rows)) if reverse else rows)))
                metadata=export_world(path,out,report)
                world=amulet.load_level(str(out/'bedrock-world'))
                try:
                    r=paving[0];offset=metadata['vertical_offset_blocks']
                    self.assertEqual(world.get_block(r['x'],25+offset,-r['z'],'minecraft:overworld').properties['color'],StringTag('green'))
                    self.assertEqual(world.get_block(0,25+offset,0,'minecraft:overworld').properties['color'],StringTag('black'))
                    self.assertEqual(world.get_block(protected['x'],25+offset,-protected['z'],'minecraft:overworld').base_name,'stone_bricks')
                finally:
                    world.close()

    def test_unspecified_planning_material_has_no_override_priority(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,collection=fixtures.TerrainTests().fixture(root)
            record=self.record(collection['features'][0]['geometry'])
            record.pop('surface');record.pop('surface_colour')
            collection['planning_geometry_records']=[record]
            build(config,collection,root/'out')
            rows=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            self.assertFalse(any(r.get('material_origin')=='accepted_planning_paving' for r in rows))

    def record(self,geometry):
        return {'id':'component-1','source_id':'dem','document_id':'drawing-1/revision-C',
                'verification_reference':'survey-2026/component-1','reuse_allowed':True,
                'registration_verified':True,'as_built_verified':True,'feature_type':'plaza',
                'surface':'concrete','surface_colour':'green','geometry':copy.deepcopy(geometry)}

    def test_polygons_materials_and_absolute_structure_elevation_export(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,collection=fixtures.TerrainTests().fixture(root)
            config['terrain']['emit_surface']=False
            geometry=collection['features'][0]['geometry']
            geometry['coordinates'].append([[.00047,.00047],[.00053,.00047],[.00053,.00053],[.00047,.00053],[.00047,.00047]])
            plaza=self.record(geometry)
            structure=copy.deepcopy(plaza)
            structure.update(id='ride-support',feature_type='ride_structure',surface='metal')
            structure.pop('surface_colour')
            structure['elevation']={'base_m':35,'top_m':39,'vertical_datum':'test-datum'}
            collection={'features':[],'planning_geometry_records':[plaza,structure]}
            report=build(config,collection,root/'out')
            self.assertEqual(len(report['planning_geometry_decisions']),2)
            rows=[json.loads(line) for line in (root/'out/voxels.jsonl').read_text().splitlines()]
            paving=[r for r in rows if r['kind']=='plaza']
            supports=[r for r in rows if r['kind']=='structure']
            self.assertTrue(paving);self.assertTrue(supports)
            self.assertEqual({r['material'] for r in paving},{'green_concrete'})
            self.assertEqual({r['y'] for r in supports},{35,36,37,38})
            self.assertEqual({r['material'] for r in supports},{'iron_block'})
            accepted=json.loads((root/'out/features-local.geojson').read_text())
            self.assertEqual(len(accepted['features'][0]['geometry']['coordinates']),2)
            normalized,_=physical_features([plaza],{'dem':{}},config['bbox'],'test-datum')
            self.assertEqual(len(normalized[0]['geometry']['coordinates']),2)
            metadata=export_world(root/'out/voxels.jsonl',root/'out',report)
            world=amulet.load_level(str(root/'out/bedrock-world'))
            try:
                r=paving[0];x,z=r['x'],-r['z'];offset=metadata['vertical_offset_blocks']
                self.assertEqual(world.get_block(x,25+offset,z,'minecraft:overworld').properties['color'],StringTag('green'))
                self.assertEqual(world.get_block(x,34+offset,z,'minecraft:overworld').base_name,'air')
                self.assertEqual(world.get_block(x,35+offset,z,'minecraft:overworld').base_name,'iron_block')
                self.assertEqual(world.get_block(0,25+offset,0,'minecraft:overworld').base_name,'air')
                self.assertEqual(world.get_block(0,35+offset,0,'minecraft:overworld').base_name,'air')
            finally:
                world.close()

    def test_proposal_registration_reuse_datum_and_layer_rejections(self):
        with tempfile.TemporaryDirectory() as d:
            config,collection=fixtures.TerrainTests().fixture(Path(d))
            baseline=self.record(collection['features'][0]['geometry'])
            self.assertEqual(physical_features([baseline],{'dem':{'license':'copyright-consultation-only'}},config['bbox'],'test-datum')[0],[])
            for key in ('reuse_allowed','registration_verified','as_built_verified'):
                r=copy.deepcopy(baseline);r[key]=False
                features,decisions=physical_features([r],{'dem':{}},config['bbox'],'test-datum')
                self.assertEqual(features,[]);self.assertEqual(decisions[0]['status'],'withheld')
            r=copy.deepcopy(baseline);r.update(feature_type='ride_structure',layer=12)
            features,decisions=physical_features([r],{'dem':{}},config['bbox'],'test-datum')
            self.assertEqual(features,[])
            r['elevation']={'base_m':30,'top_m':40,'vertical_datum':'wrong'}
            self.assertEqual(physical_features([r],{'dem':{}},config['bbox'],'test-datum')[0],[])
            r['elevation']['vertical_datum']='test-datum';r['elevation']['top_m']=float('nan')
            self.assertEqual(physical_features([r],{'dem':{}},config['bbox'],'test-datum')[0],[])
            with self.assertRaisesRegex(ValueError,'budget'):
                physical_features([baseline],{'dem':{}},config['bbox'],'test-datum',max_records=0)
