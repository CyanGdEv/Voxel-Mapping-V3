"""Wall-based shells preserve source scale, openings and bounded closure."""
from concurrent.futures import CancelledError
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,Point
from voxel_mapper import planning_wall_shell as shell
from voxel_mapper.shop_shell import leak_audit

ROOT=Path(__file__).resolve().parents[1]


def model_and_wall():
    model=json.loads((ROOT/'evidence/wicker-shop-wall-model.json').read_text())
    polygon=Polygon(np.asarray(model['outer_wall_base_outline'])[:,:2])
    return model,affine_transform(polygon,[.8,-.6,.6,.8,100,120])


class WallShellTests(unittest.TestCase):
    def test_ordered_fit_rejects_stretch_reflection_and_degeneracy(self):
        points=np.array([[0,0],[0,5],[8,5],[8,0]])
        rotation=np.array([[0,-1],[1,0]])
        r,t,error=shell.ordered_rigid(points,points@rotation+[10,20])
        np.testing.assert_allclose(r,rotation,atol=1e-12);self.assertLess(error,1e-12)
        for target in [points*1.1,points*np.array([-1,1]),np.zeros((4,2))]:
            with self.assertRaises(ValueError):shell.ordered_rigid(points,target)

    def test_rotated_source_shell_preserves_clear_openings_and_air_closure(self):
        model,wall=model_and_wall();before=copy.deepcopy(model)
        blocks,boundary,report=shell.shop_shell(model,wall,182)
        self.assertEqual(model,before);self.assertEqual(len(report['openings']),3)
        self.assertGreater(report['previous_full_cell_envelope_air_flood']['interior_air_cells_checked'],100)
        self.assertFalse(report['previous_full_cell_envelope_air_flood']['interior_reached_from_exterior'])
        self.assertLess(report['ordered_corner_max_residual_m'],1e-9)
        self.assertEqual(set(blocks.values()),{'spruce_planks','dark_oak_slab','dark_oak_slab_top'})
        self.assertEqual(report['timber_fascia_blocks'],0)
        self.assertEqual(report['roof_full_blocks'],0)
        self.assertGreater(report['roof_top_slabs'],0)
        self.assertLessEqual(report['maximum_roof_smoothing_m'],.5)
        self.assertFalse(report['native_slab_shape_air_flood']['interior_reached_from_exterior'])
        for opening in report['openings']:
            self.assertFalse(opening['external_access_verified'])
            for x,y in opening['display_columns_xy']:
                self.assertIn((x,y),boundary)
                for h in range(opening['display_clearance_blocks']):self.assertNotIn((x,182+h,y),blocks)

    def test_air_audit_detects_deliberately_removed_roof_column(self):
        model,wall=model_and_wall();blocks,boundary,report=shell.shop_shell(model,wall,0)
        doors={tuple(k):o['display_clearance_blocks'] for o in report['openings'] for k in o['display_columns_xy']}
        column=next((x,y) for x,h,y in blocks if wall.contains(Point(x+.5,y+.5)) and (x,y) not in boundary)
        damaged={p for p in blocks if (p[0],p[2])!=column}
        audit=leak_audit(damaged,boundary,doors,[[*p,0] for p in list(wall.exterior.coords)[:-1]],1)
        self.assertTrue(audit['interior_reached_from_exterior'])

    def test_oversized_roofs_low_openings_and_cancel_are_rejected(self):
        model,wall=model_and_wall();oversized=copy.deepcopy(model)
        for p in oversized['roof_mesh']['vertices']:p[0]*=30
        with self.assertRaises(ValueError):shell.shop_shell(oversized,wall,182)
        low=copy.deepcopy(model);low['opening_base_segments'][0]['height_metres']=1.8
        with self.assertRaises(ValueError):shell.shop_shell(low,wall,182)
        with self.assertRaises(CancelledError):shell.shop_shell(model,wall,182,cancelled=lambda:True)

    def test_study_canopy_and_facade_preserve_shell_and_door_clearance(self):
        model,wall=model_and_wall();guide=json.loads((ROOT/'evidence/wicker-shop-projection-model.json').read_text())
        model['projection_surfaces']=guide['projection_surfaces'];model['projection_review']=guide['projection_review']
        base,_,main=shell.shop_shell(model,wall,182);before=dict(base)
        terrain={(x,y):180 for x in range(75,125) for y in range(100,140)}
        blocks,review=shell.study_guide_features(model,wall,base,terrain,{},182)
        self.assertEqual(base,before)
        self.assertTrue(all(blocks[k]==v for k,v in base.items()))
        self.assertGreater(review['canopy_slab_blocks'],0);self.assertGreater(review['facade_detail_blocks'],0)
        self.assertTrue(all('slab' in r['material'] for r in review['canopy_blocks']))
        self.assertEqual({r['material'].split('_trapdoor_')[0] for r in review['facade_details']},{'dark_oak_fence','spruce'})
        for r in review['facade_details']:self.assertEqual(blocks[tuple(r['wall_anchor_source_xyz'])],'spruce_planks')
        for opening in main['openings']:
            for x,y in opening['display_columns_xy']:
                for h in range(opening['display_clearance_blocks']):self.assertNotIn((x,182+h,y),blocks)
        first=review['canopy_blocks'][0]['source_xyz'];high={k:183 for k in terrain}
        edging={(first[0],first[2]):[(first[1]-183,'stone')]}
        with self.assertRaises(ValueError):shell.study_guide_features(model,wall,base,high,edging,182)

    def test_shop_ground_fit_levels_thresholds_and_protects_boundaries(self):
        from shapely.geometry import box,LineString,mapping
        wall=box(0,0,3,3);floors={(x,y):182 for x in range(3) for y in range(3)}
        heights={(x,y):183 for x in range(-2,5) for y in range(-2,5)};heights.update(floors)
        opening={'id':'entry','display_columns_xy':[[0,1]],'geometry_nominal_local':mapping(LineString([(0,.5),(0,2.5)]))}
        ground={(-1,1):'stone'};rocks={(-1,0):[(1,'oak_fence')]}
        report=shell.fit_shop_approaches(wall,[opening],heights,floors,ground,rocks,{},183)
        self.assertEqual(heights[-1,1],182);self.assertEqual(ground[-1,1],'stone')
        self.assertEqual(heights[-1,0],183);self.assertEqual(heights[-2,1],183)
        self.assertEqual(report['openings'][0]['threshold_step_blocks'],0)
        self.assertEqual(report['maximum_cut_or_fill_blocks'],1)
        high={(x,y):185 for x,y in heights};high.update(floors)
        with self.assertRaises(ValueError):shell.fit_shop_approaches(wall,[opening],high,floors,{},rocks,{},183)
        blocked=dict(heights)
        with self.assertRaises(ValueError):shell.fit_shop_approaches(wall,[opening],blocked,floors,{}, {(-1,1):[(1,'stone')]},{},183)

    def test_only_bounded_inferred_fences_yield_to_source_wall_traces(self):
        sampled={'rocks':{(0,0):[(1,'oak_fence')],(1,0):[(1,'stone')]},'boundary_blocks':2}
        policy={'policy_origin':'user_instruction','explicit_claims_override_default':True}
        before=copy.deepcopy(sampled)
        with self.assertRaises(ValueError):shell.resolve_inferred_fences(sampled,{(0,0),(1,0)},policy)
        self.assertEqual(sampled,before)
        with self.assertRaises(ValueError):shell.resolve_inferred_fences(sampled,{(0,0)},{})
        self.assertEqual(sampled,before)
        changes=shell.resolve_inferred_fences(sampled,{(0,0)},policy)
        self.assertEqual(len(changes),1);self.assertEqual(sampled['rocks'],{(1,0):[(1,'stone')]})
        self.assertEqual(sampled['boundary_blocks'],1)

    def test_conditional_datum_and_source_integrity_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'world'
            with self.assertRaises(ValueError):shell.run({},'missing','missing','missing','missing',output)
            with self.assertRaises(CancelledError):shell.run({},'missing','missing','missing','missing',output,assume_plan_ffl_odn=True,cancelled=lambda:True)
            self.assertFalse(output.exists())
            profile=json.loads(shell.PROFILE.read_text());(root/'wicker-shop-wall-model.json').write_text('{}')
            with self.assertRaises(ValueError):shell.verify_shop_sources(root,root,profile)


if __name__=='__main__':unittest.main()
