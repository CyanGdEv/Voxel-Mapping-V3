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
        self.assertGreater(report['temporary_sealed_opening_air_flood']['interior_air_cells_checked'],100)
        self.assertFalse(report['temporary_sealed_opening_air_flood']['interior_reached_from_exterior'])
        self.assertLess(report['ordered_corner_max_residual_m'],1e-9)
        self.assertEqual(set(blocks.values()),{'spruce_planks','dark_oak_planks'})
        self.assertGreater(report['estimated_roof_riser_blocks'],0)
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
