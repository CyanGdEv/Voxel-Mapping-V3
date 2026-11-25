import unittest
import numpy as np
from tools.evaluate_ground_candidates import score


class CandidateEvaluationTests(unittest.TestCase):
    def test_ignore_false_positives_and_confidence_one_bin(self):
        result=score(np.array([1,1,9,9,255]),np.array([1,9,9,9,0]),np.array([1.,1.,1.,1.,np.nan]))
        self.assertEqual(result['reviewed_pixels'],4)
        self.assertEqual(result['top_label_ece_15_bins'],.25)
        self.assertEqual(result['per_class']['9']['false_positive_rate'],.5)
        self.assertEqual(result['per_class']['1']['recall'],.5)
        self.assertEqual(result['reliability_bins'][-1]['count'],4)
        self.assertIsNone(result['missing_geometry_rate'])

    def test_rejects_invalid_confidence(self):
        for value in (np.nan,-.1,1.1):
            with self.assertRaises(ValueError):score(np.array([1]),np.array([1]),np.array([value]))
