import unittest

import numpy as np

from voxel_mapper.wicker_reconstruction import preview_profile
from voxel_mapper.wicker_station import drawing_floor_level, lift_profile, phase_controls
from voxel_mapper.wicker_track import REVIEW_DOCUMENT


class StationLiftTests(unittest.TestCase):
    def test_named_floor_label_is_not_an_unrelated_building_ffl(self):
        evidence={'documents':[{'sha256':REVIEW_DOCUMENT,'pages':[{'annotations':[
            {'text':'Station','bbox':[10,10,40,20]},
            {'text':'FFL 183.25','bbox':[10,22,45,32]},
            {'text':'FFL 182.5','bbox':[100,22,145,32]}]}]}]}
        self.assertEqual(drawing_floor_level(evidence,'Station')[0],183.25)
        evidence['documents'][0]['pages'][0]['annotations'].append(
            {'text':'FFL 184','bbox':[10,25,45,35]})
        with self.assertRaises(ValueError):drawing_floor_level(evidence,'Station')

    def test_station_phase_stays_level_then_exit_descends_before_lift(self):
        c={'level_start_m':40,'level_end_m':60,'station_rail_level_m':182.25,
           'lift_start_m':90,'lift_foot_level_m':180.25}
        b=phase_controls(c)+[{'status':'provisional_annotation_binding','point_label':'HP1',
                            'nearest_candidate':{'station_m':130},'printed_level_m':201}]
        h=preview_profile({'route_length_m':200},b,[40,45,50,55,60,70,80,90])
        np.testing.assert_allclose(h[:5],182.25)
        self.assertTrue(np.all(np.diff(h[4:])<0))
        self.assertEqual(h[-1],180.25)

    def test_lift_has_steeper_lower_incline_and_continuous_gradient_change(self):
        x=np.arange(100,173,.01)
        h=lift_profile(x,100,172,180.25,201)
        self.assertAlmostEqual(h[0],180.25)
        self.assertAlmostEqual(h[-1],201)
        self.assertTrue(np.all(np.diff(h)>=-1e-10))
        self.assertGreaterEqual(h.min(),180.25)
        self.assertLessEqual(h.max(),201)
        slope=np.gradient(h,.01)
        self.assertGreater(slope[1000],2*slope[5000])
        self.assertLess(slope[0],.002)
        self.assertLess(slope[7200],.002)
        self.assertLess(np.max(np.abs(np.diff(slope))),.002)
        with self.assertRaises(ValueError):lift_profile(x,100,100,180,201)
        with self.assertRaises(ValueError):lift_profile(x,100,172,201,180)


if __name__=='__main__':unittest.main()
