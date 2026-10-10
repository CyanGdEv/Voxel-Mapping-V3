import json
from pathlib import Path
import unittest
from voxel_mapper.shop_shell import boundary_columns,opening_columns,leak_audit
from voxel_mapper.shop_study import plan,raster_mesh,join_wall_columns

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'evidence/wicker-shop-projection-model.json'
SHA='4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1'


class ShopShellTests(unittest.TestCase):
    def test_outside_air_detects_side_and_roof_holes_but_ignores_declared_door(self):
        boundary={(x,z) for x in range(-2,3) for z in range(-2,3) if abs(x)==2 or abs(z)==2}
        doors={(-2,0):2}
        cells={(x,y,z) for x,z in boundary for y in range(3)}
        cells|={(x,3,z) for x in range(-2,3) for z in range(-2,3)}
        cells-={(-2,0,0),(-2,1,0)}
        self.assertFalse(leak_audit(cells,boundary,doors)['interior_reached_from_exterior'])
        for hole in ((2,2,0),(0,3,0)):
            self.assertTrue(leak_audit(cells-{hole},boundary,doors)['interior_reached_from_exterior'])

    def test_previous_four_to_one_column_closure_still_leaks(self):
        model=json.loads(MODEL.read_text());scale=4
        walls,_=raster_mesh(model['wall_mesh'],scale);roof,_=raster_mesh(model['roof_mesh'],scale)
        joins,_=join_wall_columns(walls,roof,scale)
        audit=leak_audit(walls|roof|joins,boundary_columns(model['outer_wall_base_outline'],scale),
                         opening_columns(model['opening_base_segments'],scale),model['outer_wall_base_outline'],scale)
        self.assertTrue(audit['interior_reached_from_exterior'])

    def test_closed_boundary_both_scales_preserves_all_declared_door_air(self):
        model=json.loads(MODEL.read_text())
        for scale in (1,4):
            rows,r=plan(MODEL,SHA,scale,True,True)
            cells={(p['x'],p['y'],p['z']) for p in rows if p['kind']=='study_surface'}
            audit=r['boundary_closure_audit']
            self.assertFalse(audit['leak_audit']['interior_reached_from_exterior'])
            self.assertGreater(audit['leak_audit']['interior_air_cells_checked'],100)
            self.assertTrue(audit['door_air_verified'])
            for (x,z),head in opening_columns(model['opening_base_segments'],scale).items():
                self.assertTrue(all((x,y,z) not in cells for y in range(head)))
            self.assertIsNone(r['crs']);self.assertEqual(r['park_world_blocks_added'],0)
        with self.assertRaises(ValueError):plan(MODEL,SHA,1,False,True)
