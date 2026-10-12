import json
from pathlib import Path
import unittest
from voxel_mapper.wicker_building_models import rectangular_model,station_parts
from voxel_mapper.shop_slabs import assemble
from voxel_mapper.shop_shell import opening_columns
from voxel_mapper.shop_foundations import level_pad
from voxel_mapper.reconstruction.local_buildings import rotate_model
from scripts.build_wicker_station_section import placement


class BuildingModelTests(unittest.TestCase):
    def test_all_parts_use_slab_pipeline_and_preserve_apertures_after_rotation(self):
        review=json.loads((Path(__file__).parents[1]/'evidence/wicker-architectural-outline-review.json').read_text())
        parts=station_parts(review)
        self.assertEqual({p['id'] for p in parts},{'station','preshow_tower','preshow_low'})
        matrix,shift,h=placement(review,[407563,343584])
        self.assertGreater(h['plan_correspondence_checks']['station']['roof_vs_site_inner']['iou'],.98)
        import math
        angle=math.degrees(math.atan2(matrix[1,0],matrix[0,0]))
        for part in parts:
            model=rotate_model(part['model'],angle)
            cells,audit=assemble(model)
            self.assertFalse(audit['native_shape_leak_audit']['interior_reached_from_exterior'])
            self.assertTrue(any(m.startswith('oak_slab') for m in cells.values()))
            self.assertFalse(any(m.startswith('dark_oak_slab') for m in cells.values()))
            for (x,z),height in opening_columns(model['opening_base_segments'],1).items():
                self.assertTrue(all((x,y,z) not in cells for y in range(height)))
            fill,grounding=level_pad(model,cells,[100,100],185,lambda x,z:182.2)
            self.assertTrue(grounding['continuous_terrain_contact'])
            self.assertGreater(len(fill),0)
            with self.assertRaises(ValueError):level_pad(model,cells,[100,100],185,lambda x,z:185.2)

    def test_unbounded_dimensions_and_invalid_native_palette_are_rejected(self):
        with self.assertRaises(ValueError):rectangular_model(40,10,3,5)
        model=rectangular_model(8,12,3,5)
        model['roof_palette']['bottom']='stone'
        with self.assertRaises(ValueError):assemble(model)

