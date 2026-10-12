import tempfile
import unittest
import pymupdf
from shapely.geometry import box
from voxel_mapper.forbidden_valley import displayed, reviewed_outline, extract

class ValleyTests(unittest.TestCase):
    def test_rotated_native_corners_use_displayed_frame(self):
        doc = pymupdf.open()
        page = doc.new_page(width=200,height=300)
        corners = [(20,30),(80,30),(80,90),(20,90),(20,30)]
        for a,b in zip(corners,corners[1:]):
            page.draw_line(a,b)
        page.set_rotation(90)
        expected = displayed(box(20,30,80,90),page)
        found = reviewed_outline(page, list(expected.exterior.coords)[:4], tolerance=.01)
        self.assertLess(found.symmetric_difference(expected).area,.01)
        with self.assertRaises(ValueError):
            reviewed_outline(page,[(0,0),(1,0),(1,1)],tolerance=.01)
        doc.close()

    def test_missing_source_fails_before_any_components(self):
        with tempfile.TemporaryDirectory() as cache:
            with self.assertRaisesRegex(ValueError, 'Missing or changed'):
                extract(cache)
