import json
from pathlib import Path
import unittest
import numpy as np
from voxel_mapper.wicker_building_models import station_parts
from voxel_mapper.wicker_access import build_access


class AccessTests(unittest.TestCase):
    def test_raw_pdf_y_is_converted_before_preshow_placement(self):
        review=json.loads((Path(__file__).parents[1]/'evidence/wicker-architectural-outline-review.json').read_text())
        parts={p['id']:p for p in station_parts(review)}
        for name in ('preshow_low','preshow_tower'):
            outline=parts[name]['source_outline'];raw=outline['raw_pdf_bounds'];up=outline['native_pdf_bounds']
            self.assertEqual(up[1],2384-raw[3]);self.assertEqual(up[3],2384-raw[1])
        self.assertGreater(parts['preshow_tower']['source_plan_centre_m'][1],parts['preshow_low']['source_plan_centre_m'][1])

    def test_steps_replace_landing_without_leaving_an_overhead_deck(self):
        rows,audit=build_access(np.eye(2),np.array([0,0]),[],lambda x,z:180.2,183.3,set(),[-100,-100,100,100])
        self.assertEqual(len(audit['features']),3)
        steps={p:r for p,r in rows.items() if 'steps' in r['feature'] and r['material']=='oak_slab'}
        self.assertTrue(steps)
        for x,y,z in steps:
            self.assertFalse(any(rows.get((x,yy,z),{}).get('material') in ('oak_planks','stone') for yy in (y+1,y+2)))
        columns={}
        for (x,y,z),r in rows.items():columns.setdefault((x,z),[]).append(y)
        for ys in columns.values():
            self.assertEqual(min(ys),181)
            self.assertEqual(sorted(ys),list(range(min(ys),max(ys)+1)))

    def test_outside_chunk_extent_is_rejected(self):
        with self.assertRaises(ValueError):
            build_access(np.eye(2),np.array([0,0]),[],lambda x,z:180.2,183.3,set(),[0,0,1,1])
