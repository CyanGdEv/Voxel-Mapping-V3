import tempfile
import unittest
from pathlib import Path
from shapely.geometry import Point,box
from voxel_mapper.wicker_queue import source_walkway,raster_review,placement


class QueueReviewTests(unittest.TestCase):
    def test_inferred_rails_keep_walkway_and_open_ends_clear(self):
        polygon=box(0,0,4,20)
        rows,audit=raster_review(polygon,lambda x,z:100,set(),rails=True)
        self.assertEqual(audit['paving_columns'],80)
        self.assertGreater(audit['rail_cells'],0)
        for (x,y,z),row in rows.items():
            if row['material']=='oak_fence':
                self.assertFalse(polygon.covers(Point(x+.5,z+.5)))
                self.assertGreaterEqual(z,1);self.assertLess(z,19)
                self.assertEqual(y,101)
        self.assertTrue(all(rows[x,100,z]['material']=='stone' for x in range(4) for z in range(20)))

    def test_missing_native_ground_and_protected_columns_stay_untouched(self):
        rows,audit=raster_review(box(0,0,4,20),lambda x,z:None if z==3 else 100,{(0,0),(4,5)},rails=True)
        self.assertFalse(any((x,z) in {(0,0),(4,5)} or z==3 for x,y,z in rows))
        self.assertEqual(audit['protected_or_missing_columns'],5)

    def test_station_pose_preserves_source_dimensions(self):
        source=box(0,0,3,20)
        review={'parts':[{'id':'station','rotation_degrees':37,'anchor_bng_m':[1000,2000],
                         'source_outline':{'geometry':box(0,0,10,10).__geo_interface__}}]}
        placed=placement(source,review)
        self.assertAlmostEqual(placed.area,source.area)
        self.assertAlmostEqual(placed.length,source.length)

    def test_unpinned_floor_pdf_cannot_supply_queue_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong.pdf';p.write_bytes(b'not the reviewed drawing')
            with self.assertRaisesRegex(ValueError,'Pinned floor'):
                source_walkway(p,{'floor_sha256':'x'})
