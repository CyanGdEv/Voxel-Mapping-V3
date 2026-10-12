"""Ensure drawing correspondence cannot conceal scale or link mismatches."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from shapely.geometry import Polygon
from scripts.review_wicker_architectural_outlines import fixed_scale_alignments, transform
from scripts import acquire_wicker_site_sections as acquisition


class ArchitecturalOutlineTests(unittest.TestCase):
    def test_known_rigid_correspondence_retains_half_turn(self):
        source = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])
        angle = .35; r = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
        target = transform(source, r, [71, 103])
        fits = fixed_scale_alignments(source, target)
        self.assertEqual(len(fits), 2)
        self.assertTrue(all(v['shop_corner_max_metres'] < 1e-10 for v in fits))
        for fit in fits:
            rotation = np.asarray(fit['row_rotation'])
            np.testing.assert_allclose(rotation.T @ rotation, np.eye(2), atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(rotation), 1)

    def test_scale_error_is_not_absorbed(self):
        source = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])
        target = transform(source, np.eye(2)*1.2, [10, 20])
        fits = fixed_scale_alignments(source, target)
        self.assertTrue(all(v['shop_corner_rms_metres'] > 2 for v in fits))

    def test_non_four_corner_outline_rejected(self):
        triangle = Polygon([(0, 0), (1, 0), (0, 1)])
        with self.assertRaises(ValueError): fixed_scale_alignments(triangle, triangle)

    def test_unobserved_and_duplicate_links_never_downloaded(self):
        raw = b"<a href=\"javascript:AppBlobImage('12');\">Plan</a>"
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'page.html'; path.write_bytes(raw)
            with patch.object(acquisition, 'PAGE_SHA', hashlib.sha256(raw).hexdigest()), patch.object(acquisition, 'urlopen') as network:
                for ids in [[], [12, 12], [99], list(range(33))]:
                    with self.assertRaises(ValueError): acquisition.acquire(path, Path(tmp)/'out', ids)
                network.assert_not_called()


if __name__ == '__main__': unittest.main()
