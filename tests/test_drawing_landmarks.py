import unittest
from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform
from voxel_mapper.drawing_landmarks import inspect_named_landmarks


class LandmarkTests(unittest.TestCase):
    def fixture(self):
        controls=[(x,y,503500+x,168350+y) for x in (0,100) for y in (0,100)]
        polygon=transform(Transformer.from_crs(27700,4326,always_xy=True).transform,
                          box(503540,168390,503560,168410))
        feature={'id':'osm/dome','properties':{'kind':'building','source_id':'osm','name':'The Dome'},
                 'geometry':mapping(polygon)}
        return controls,feature

    def test_containment_under_hypothesis_is_not_independent_verification(self):
        controls,feature=self.fixture()
        result=inspect_named_landmarks(controls,[{'text':'Dome','origin':[50,50]}],[feature],27700)
        self.assertEqual(result['checks'][0]['status'],'label_inside_reference_footprint')
        self.assertFalse(result['registration_verified'])
        self.assertEqual(result['independent_accuracy'],'not_verified')
        self.assertEqual(result['world_geometry_additions'],0)

    def test_extrapolation_ambiguity_and_disagreement(self):
        controls,feature=self.fixture()
        result=inspect_named_landmarks(controls,[{'text':'Dome','origin':[150,50]}],[feature],27700)
        self.assertEqual(result['checks'][0]['status'],'label_outside_control_hull')
        result=inspect_named_landmarks(controls,[{'text':'Dome','origin':[20,20]}],[feature],27700)
        self.assertEqual(result['checks'][0]['status'],'label_outside_reference_footprint')
        self.assertEqual(inspect_named_landmarks(controls,[{'text':'Dome','origin':[50,50]}],[feature,feature],27700)['checks'],[])

    def test_invalid_controls_and_limits(self):
        self.assertEqual(inspect_named_landmarks([],[],[],27700)['status'],'insufficient_landmark_transform')
        self.assertEqual(inspect_named_landmarks([],[],[{}]*5001,27700)['status'],'landmark_budget_exceeded')
