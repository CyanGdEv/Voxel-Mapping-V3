"""Maintenance heights, slab geometry and retained scene seams."""
from concurrent.futures import CancelledError
from pathlib import Path
import copy
import json
import tempfile
import unittest
import numpy as np
from shapely.geometry import box,mapping
from voxel_mapper import maintenance_world as module


class MaintenanceTests(unittest.TestCase):
    def test_inspection_datum_does_not_raise_roof_from_display_plate(self):
        trace={'datum_pixel':[0,740],'eave_pixel':[0,625],'ridge_pixel':[0,555],
               'inspection_level_m':181.5,'datum_label':'inspection','endpoint_sampling_bound_pixels':2}
        a=module.traced_heights(trace,.0445,184);b=module.traced_heights(trace,.0445,183)
        self.assertEqual(a['absolute_display_assumption_m'],b['absolute_display_assumption_m'])
        self.assertAlmostEqual(a['above_display_floor_m']['eave'],181.5+115*.0445-184)
        self.assertAlmostEqual(b['above_display_floor_m']['ridge']-a['above_display_floor_m']['ridge'],1)
        with self.assertRaises(ValueError):module.traced_heights(trace,.0445,188)

    def component(self):
        opening={'id':'z-/ride','endpoints':[[-1,-5,0],[1,-5,0]],'height_metres':2.3,'width_metres':2}
        args=(box(-4,-5,4,5),(9,11),np.eye(2),184,{'eave':2.7,'ridge':5.5},[opening])
        return module.make_component(*args)

    def test_maintenance_shell_keeps_slab_roof_and_stone_lower_course(self):
        blocks,wall,boundary,portals,q=self.component()
        self.assertEqual(q['full_roof_blocks'],0);self.assertGreater(q['roof_slab_blocks'],0)
        self.assertIn('sandstone',blocks.values());self.assertFalse(q['native_slab_shape_air_flood']['interior_reached_from_exterior'])
        for p in portals:
            for x,y in p['columns_xy']:
                for h in [184,185]:self.assertNotIn((x,h,y),blocks)

    def test_retained_full_block_wins_material_alias_without_opening_roof(self):
        blocks,wall,boundary,portals,q=self.component()
        roof_key=next(k for k,m in blocks.items() if m=='oak_slab')
        old={roof_key:'spruce_planks'};before=copy.deepcopy(old)
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,'portal-air.json').write_text('[]')
            air,r=module.retained_seam(blocks,old,wall,boundary,portals,
                {'parts':[{'id':'station','wall_geometry_nominal_local':mapping(box(5,-5,9,5))}]},temp,184)
        self.assertEqual(old,before);self.assertEqual(blocks[roof_key],'spruce_planks')
        self.assertEqual(len(r['retained_material_aliases']),1)
        self.assertFalse(r['compound_native_half_shape_air_flood']['interior_reached_from_exterior'])

    def test_cancellation_and_opt_in_create_no_partial_world(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'world'
            with self.assertRaises(ValueError):module.run('missing','missing','missing','missing',out)
            with self.assertRaises(CancelledError):module.run('missing','missing','missing','missing',out,allow_provisional=True,cancelled=lambda:True)
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
