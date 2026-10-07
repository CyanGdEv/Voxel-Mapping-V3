import unittest
import tempfile
import json
from pathlib import Path
from shapely.geometry import box,Point
from voxel_mapper.wicker_details import straightened,pitched_roof
from voxel_mapper.wicker_surfaces import painted_polygon
from voxel_mapper.bedrock import material_block,export_world


class DetailTests(unittest.TestCase):
    def test_curved_fill_preserves_shape(self):
        p=straightened({'items':[['c',[0,0],[0,8],[8,8],[8,0]],['l',[8,0],[0,0]]]})
        self.assertGreater(painted_polygon(p).area,20)

    def test_quad_order_is_not_a_bow_tie(self):
        p=straightened({'items':[['qu',[[0,0],[0,2],[8,0],[8,2]]]]})
        self.assertEqual(painted_polygon(p).area,16)

    def test_unsupported_paths_are_withheld(self):
        self.assertIsNone(painted_polygon(straightened({'items':[['unknown']]})))

    def test_roof_ridge_follows_long_axis_and_has_minimum_clearance(self):
        p=box(0,0,20,10)
        ridge=pitched_roof(p,Point(10,5),190,183)
        self.assertGreater(ridge,pitched_roof(p,Point(10,.5),190,183))
        self.assertEqual(ridge,pitched_roof(p,Point(2,5),190,183))
        self.assertGreaterEqual(pitched_roof(p,Point(10,.5),180,183),187)

    def test_vegetation_materials_keep_species(self):
        for species in ('oak','spruce'):
            self.assertEqual(material_block(species+'_log').properties['material'].py_str,species)
            self.assertEqual(material_block(species+'_leaves').properties['material'].py_str,species)

    def test_vegetation_round_trip_preserves_bedrock_species_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            rows=[{'x':i,'y':180,'z':0,'kind':'structure','material':material}
                  for i,material in enumerate(('oak_log','spruce_log','oak_leaves','spruce_leaves'))]
            (p/'voxels.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            report=export_world(p/'voxels.jsonl',p,{'voxel_size_m':1})
            self.assertEqual(report['round_trip_validation'],'all written blocks and all unwritten air cells verified')
