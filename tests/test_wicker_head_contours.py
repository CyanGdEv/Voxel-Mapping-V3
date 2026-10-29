import json
import math
from pathlib import Path
import unittest

import numpy as np
from scipy import ndimage as ndi

from voxel_mapper.bedrock import ALLOWED_MATERIALS
from voxel_mapper.wicker_structure_semantics import effigy_model
from voxel_mapper.wicker_head_contours import contoured_head


class WickerHeadContourTests(unittest.TestCase):
    def profile(self):
        path=Path(__file__).resolve().parents[1]/'voxel_mapper/data/wicker-structural-reconstruction-v4.json'
        return json.loads(path.read_text())['big_bob']

    def test_human_face_points_towards_the_marked_plaza_approach(self):
        p=self.profile();human=-np.asarray(p['head_front_bng_direction'])
        # The user's plaza inspection position is 646,159,-645 in this frame.
        approach=np.array([406896+646,342880+645])-p['head_center_bng_en']
        self.assertGreater(float(human@approach/np.linalg.norm(approach)),.9)

    def test_head_location_stays_with_the_identified_upper_lidar_cluster(self):
        p=self.profile();context_mean=np.array([407554.42826086946,343550.19304347824])
        self.assertLess(np.linalg.norm(np.asarray(p['head_center_bng_en'])-context_mean),.1)

    def test_head_uses_native_half_block_contours_and_stays_connected(self):
        m=contoured_head(self.profile(),406896,342880,-31)
        self.assertFalse(set(m.values())-ALLOWED_MATERIALS)
        self.assertGreater(sum('stairs' in v or 'slab' in v for v in m.values()),30)
        xyz=np.array(list(m));lo=xyz.min(0);hi=xyz.max(0);a=np.zeros(hi-lo+1,bool)
        a[tuple((xyz-lo).T)]=True
        self.assertEqual(ndi.label(a)[1],1)

    def test_both_horn_curls_keep_open_centres_after_native_quantisation(self):
        p=self.profile();m=contoured_head(p,406896,342880,-31)
        front=np.asarray(p['head_front_bng_direction']);side=np.array([-front[1],front[0]])
        u,v,h=p['contoured_head']['horn_opening_test_u_v_h']
        for sign in (-1,1):
            en=np.asarray(p['head_center_bng_en'])+sign*u*side+v*front
            key=math.floor(en[0]-406896),math.floor(p['base_odn_m']+h-31),math.floor(342880-en[1])
            self.assertNotIn(key,m)

    def test_whole_figure_keeps_padded_emitters_and_connected_head(self):
        m=effigy_model(self.profile(),406896,342880,-31)
        xyz=np.array(list(m));lo=xyz.min(0);hi=xyz.max(0);a=np.zeros(hi-lo+1,bool);a[tuple((xyz-lo).T)]=True
        self.assertEqual(ndi.label(a)[1],1)
        fires=[k for k,v in m.items() if v=='campfire'];self.assertEqual(len(fires),2)
        for x,y,z in fires:self.assertIn((x,y-1,z),m)


if __name__=='__main__':unittest.main()
