"""Drawing matches require a held-out check and never override world conflicts."""
from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
import unittest
import numpy as np
from shapely.geometry import box,LineString,mapping
from voxel_mapper import basement_alignment as module


class BasementAlignmentTests(unittest.TestCase):
    def test_rigid_fit_uses_three_corners_and_an_untouched_holdout(self):
        source=np.array([[0,0],[100,0],[100,200],[0,200]],float)
        rotation=np.array([[.8,-.6],[.6,.8]]);target=source@rotation+[80,110]
        observed=target.copy();observed[2]+=[1,0]
        r,t,review=module.rigid_correspondence(source,observed)
        self.assertTrue(np.allclose(r,rotation));self.assertTrue(np.allclose(t,[80,110]))
        self.assertEqual(review['fit_corner_indices'],[0,1,3])
        self.assertAlmostEqual(review['heldout_residual_m'],module.UNIT)
        self.assertEqual(review['scale'],1)
        self.assertFalse(review['independent_survey_check'])

    def test_bad_holdout_scale_reflection_and_collinear_controls_rejected(self):
        source=np.array([[0,0],[100,0],[100,200],[0,200]],float)
        bad=source.copy();bad[2]+=[10,0]
        for target in [bad,source*1.1,source*[-1,1]]:
            with self.assertRaises(ValueError):module.rigid_correspondence(source,target)
        with self.assertRaises(ValueError):module.rigid_correspondence(np.zeros((4,2)),source)
        with self.assertRaises(ValueError):module.rigid_correspondence(source,source,holdout=-1)

    def test_strokes_check_actual_endpoints_not_only_matching_bounds(self):
        class Page:
            def __init__(self,points):self.points=points
            def get_drawings(self):return [{'type':'s','items':[('l',*self.points)]}]
        expected={'0':[[0,0],[10,20]]}
        self.assertEqual(len(module.replay_strokes(Page([[0,0],[10,20]]),expected)),1)
        with self.assertRaises(ValueError):module.replay_strokes(Page([[0,20],[10,0]]),expected)

    def test_current_entry_marker_and_terrain_conflicts_never_authorize_cutting(self):
        current=box(1,1,3,3);outer=box(0,0,4,4)
        report={'undercroft_geometry_nominal_local':mapping(current),
                'entry_flight':{'surfaces':[{'source_cell_xy':[0,0]}]},
                'parts':[{'id':'preshow_low','wall_geometry_nominal_local':mapping(current),
                          'openings':[{'geometry_nominal_local':mapping(LineString([(1,1),(2,1)]))}]}]}
        rows=[{'x':x,'y':180,'z':y+1,'kind':'terrain','material':'orange_wool' if (x,y)==(0,0) else 'grass_block'} for x in range(4) for y in range(4)]
        r=module.conflict_review(report,rows,outer,current,LineString([(0,0),(4,0)]))
        self.assertFalse(r['world_replacement_allowed']);self.assertEqual(r['world_geometry_added'],0)
        self.assertEqual(r['existing_entry_columns_inside_aligned_basement'],[[0,0]])
        self.assertEqual(len(r['retained_plan_marker_columns_inside_aligned_basement']),1)
        self.assertEqual(r['maximum_current_ground_cut_to_178_floor_blocks'],3)

    def test_cancel_and_existing_output_fail_without_partial_review(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'new'
            with self.assertRaises(CancelledError):module.run('missing','missing','missing','missing',out,cancelled=lambda:True)
            self.assertFalse(out.exists())
            with self.assertRaises(ValueError):module.run('missing','missing','missing','missing',temp)


if __name__=='__main__':unittest.main()
