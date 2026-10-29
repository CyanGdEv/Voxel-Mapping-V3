from copy import deepcopy
from types import SimpleNamespace
import unittest

import numpy as np

from voxel_mapper.alton_aligned_world import WICKER_AFFINE
from voxel_mapper.wicker_support_bays import support_bay_caps


class SupportBayTests(unittest.TestCase):
    def context(self):
        def row(index,station,x):
            return {'source_foot_index':index,'target_sample_station_m':station,
                'source_post':{'xy':[x,0],'symbol_family':'outer','offset_m':1},
                'target':{'xy':[x,5]},'deck_underside_m':100}
        rows=[row(1,10,0),row(2,12,2)]
        return SimpleNamespace(ground=np.zeros((64,64),np.int16),width=64,height=64,
            e0=WICKER_AFFINE[4]-20,n0=WICKER_AFFINE[5]-40,offset=0,
            wicker_quality={'fence_supports':{'constructed_supports':rows}})

    def test_bay_uses_the_exported_row_offset_and_full_fence_height(self):
        l=self.context();before=deepcopy(l.wicker_quality)
        r=support_bay_caps(l,{'maximum_adjacent_station_gap_m':3,'maximum_adjacent_footing_gap_m':5})
        self.assertEqual(r['bays'],1)
        # Z=-46 exists only with the source nominal-Y to exported-row +1.
        self.assertEqual(l.ride_support_bay_caps[64-46,21],98)
        self.assertTrue(np.all(l.ride_support_bay_caps[l.ride_support_bay_caps>-32768]+1.5<=100))
        self.assertEqual(l.wicker_quality,before)

    def test_overlapping_xy_from_another_track_visit_is_not_joined(self):
        l=self.context();row=deepcopy(l.wicker_quality['fence_supports']['constructed_supports'][0])
        row['target_sample_station_m']=110;row['source_foot_index']=3
        l.wicker_quality['fence_supports']['constructed_supports'].append(row)
        r=support_bay_caps(l,{'maximum_adjacent_station_gap_m':3,'maximum_adjacent_footing_gap_m':5})
        self.assertEqual(r['bays'],1);self.assertEqual(r['withheld_pairs']['station_gap'],1)


if __name__=='__main__':unittest.main()
