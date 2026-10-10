import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from voxel_mapper.shop_study import raster_mesh,plan,run,join_wall_columns

MODEL=Path(__file__).resolve().parents[1]/'evidence/wicker-shop-wall-model.json'
SHA='5d791eb4dd6665fce7d889d6a32f5f65672cf8db82628d307cde864f89e9ab22'


class ShopStudyTests(unittest.TestCase):
    def test_joins_preserve_lower_holes_and_refuse_remote_or_missing_roofs(self):
        wall={(0,0,0),(0,2,0)};roof={(0,4,0)}
        added,audit=join_wall_columns(wall,roof,1)
        self.assertEqual(added,{(0,3,0)})
        self.assertNotIn((0,1,0),wall|added)
        self.assertEqual(audit['added_cells'],1)
        self.assertEqual(join_wall_columns(wall,{(0,2,0)},1)[0],set())
        for invalid in (set(),{(0,5,0)},{(0,1,0)}):
            with self.assertRaises(ValueError):join_wall_columns(wall,invalid,1)

    def test_joined_review_connects_every_wall_column_preserves_doors_and_source(self):
        model=MODEL.with_name('wicker-shop-projection-model.json')
        sha='4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1'
        before=model.read_bytes()
        for scale in (1,4):
            rows,r=plan(model,sha,scale,True)
            cells={(p['x'],p['y'],p['z']) for p in rows if p['kind']=='study_surface'}
            self.assertGreater(r['estimated_join_audit']['added_cells'],0)
            self.assertGreater(r['projection_cells'],0)
            for col in r['estimated_join_audit']['columns']:
                x,z=col['local_xz']
                self.assertTrue(all((x,y,z) in cells for y in range(col['wall_top'],col['roof_bottom']+1)))
            self.assertTrue(all(o['all_centre_samples_air'] for o in r['opening_centre_sample_audit']))
            self.assertEqual(r['park_world_blocks_added'],0)
        self.assertEqual(model.read_bytes(),before)

    def test_surface_projection_is_winding_invariant_and_covers_triangle_seam(self):
        mesh={'vertices':[[0,0,2],[2,0,2],[2,2,2],[0,2,2]],'triangles':[[0,1,2],[0,2,3]]}
        cells,audit=raster_mesh(mesh,1)
        self.assertEqual(cells,{(0,2,0),(1,2,0),(0,2,1),(1,2,1)})
        mesh['triangles']=[list(reversed(t)) for t in mesh['triangles']]
        self.assertEqual(raster_mesh(mesh,1)[0],cells)

    def test_missing_opening_triangles_remain_air(self):
        mesh={'vertices':[[0,0,0],[0,1,0],[0,1,3],[0,0,3],[0,2,0],[0,3,0],[0,3,3],[0,2,3]],
              'triangles':[[0,1,2],[0,2,3],[4,5,6],[4,6,7]]}
        cells,_=raster_mesh(mesh,1)
        self.assertNotIn((0,1,1),cells)
        self.assertIn((0,1,0),cells);self.assertIn((0,1,2),cells)

    def test_isolated_source_model_contract_and_repeatability(self):
        rows,r=plan(MODEL,SHA,4)
        self.assertEqual((rows,r),plan(MODEL,SHA,4))
        self.assertIsNone(r['crs']);self.assertEqual(r['vertical_datum'],'STUDY_ZERO')
        self.assertEqual(r['park_world_blocks_added'],0)
        self.assertIsNone(r['wall_thickness_metres'])
        self.assertGreater(r['surface_cells'],0)
        self.assertTrue(all(o['all_centre_samples_air'] for o in r['opening_centre_sample_audit']))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'changed.json';p.write_bytes(MODEL.read_bytes()+b' ')
            with self.assertRaises(ValueError):plan(p,SHA,1)

    def test_invalid_scale_degenerate_and_nonfinite_meshes_are_refused(self):
        mesh={'vertices':[[0,0,0],[1,0,0],[2,0,0]],'triangles':[[0,1,2]]}
        with self.assertRaises(ValueError):raster_mesh(mesh,1)
        for scale in (True,2):
            with self.assertRaises(ValueError):raster_mesh(mesh,scale)
        mesh['vertices'][0][0]=float('nan')
        with self.assertRaises(ValueError):raster_mesh(mesh,1)

    def test_native_study_export_requires_cold_reopen_validation(self):
        with tempfile.TemporaryDirectory() as d:
            report=run(MODEL,SHA,Path(d)/'study',1)
            self.assertEqual(report['world']['round_trip_validation'],'all written blocks and all unwritten air cells verified')
            self.assertTrue((Path(d)/'study/park.mcworld').is_file())
