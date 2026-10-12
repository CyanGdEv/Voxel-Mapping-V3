import unittest

import numpy as np

from voxel_mapper.wicker_registration import straight_ring, printed_scale, similarity_candidates, apply_candidate


class WickerRegistrationTests(unittest.TestCase):
    def test_separate_subpaths_cannot_be_joined_into_a_building(self):
        drawing = {'items': [['l', [0, 0], [10, 0]], ['l', [10, 10], [0, 10]], ['l', [0, 10], [0, 0]]]}
        self.assertIsNone(straight_ring(drawing))

    def test_scale_uses_tick_numbers_without_unit_suffix_displacement(self):
        annotations = [{'text': str(i), 'bbox': [i*10-2, 100, i*10+2, 110]} for i in (0, 10, 20, 30, 40)]
        annotations.append({'text': '50 m', 'bbox': [498, 100, 560, 110]})
        self.assertAlmostEqual(printed_scale(annotations), .1)
        annotations.append({'text': '20', 'bbox': [300, 100, 304, 110]})
        with self.assertRaises(ValueError):
            printed_scale(annotations)

    def test_similarity_fits_translation_rotation_and_uniform_scale_only(self):
        pdf = np.asarray([[0, 0], [100, 0], [100, 50], [0, 50]], dtype=float)
        mapped = np.asarray([[500, 1000], [510, 1000], [510, 995], [500, 995]], dtype=float)
        candidates = similarity_candidates(pdf, mapped)
        candidate = min(candidates, key=lambda c: np.max(np.abs(apply_candidate(pdf, c)-mapped)))
        self.assertLess(candidate['shop_corner_rms_m'], 1e-8)
        np.testing.assert_allclose(apply_candidate([[50, 25]], candidate), [[505, 997.5]])
        # Anisotropic distortion cannot be silently fitted as a perfect affine.
        mapped[2:, 1] -= 10
        self.assertGreater(min(c['shop_corner_rms_m'] for c in similarity_candidates(pdf, mapped)), 1)

    def test_degenerate_control_footprint_rejected(self):
        with self.assertRaises(ValueError):
            similarity_candidates([[0, 0]]*4, [[0, 0]]*4)
