import unittest
from shapely.geometry import LineString
from voxel_mapper.reconstruction.garden_bridges import bridge_cells


class GardenBridgeTests(unittest.TestCase):
    def test_wet_span_does_not_fill_bed_or_water(self):
        wet=lambda x,z:148 if 3<=x<=7 else None
        cells,clear,walk=bridge_cells(LineString([(0,0),(10,0)]),2,151,
            lambda x,z:146 if wet(x,z) else 150,water_top=wet)
        for x in range(3,8):
            self.assertFalse(any(k[0]==x and k[2]==0 and k[1]<=148 for k in cells))
            self.assertFalse(any(k[0]==x and k[2]==0 and k[1]<=148 for k in clear))
        self.assertTrue(all((x,0) in walk for x in range(10)))

    def test_arch_keeps_lower_corridor_open(self):
        cells,clear,walk=bridge_cells(LineString([(0,0),(16,0)]),3,177,
            lambda x,z:172,'white_ashlar_arch',20)
        self.assertIn((8,173,0),clear)
        self.assertIn((8,174,0),clear)
        self.assertEqual(cells[(8,176,0)],'stone')
        self.assertFalse(set(cells)&clear)

    def test_stair_ramp_faces_bridge(self):
        cells,_,walk=bridge_cells(LineString([(0,0),(8,0)]),2,155,
            lambda x,z:150,'footbridge',6)
        stairs=[v for k,v in cells.items() if k[0]<0 and 'stairs' in v]
        self.assertTrue(stairs)
        self.assertTrue(all(v=='stone_stairs_east' for v in stairs))

    def test_rejects_invalid_dimensions(self):
        for width in (0,99,float('nan')):
            with self.assertRaises(ValueError):
                bridge_cells(LineString([(0,0),(10,0)]),width,151,lambda x,z:150)
