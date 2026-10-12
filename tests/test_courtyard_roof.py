import math
import unittest
from types import SimpleNamespace
from shapely.geometry import Polygon,box,Point
from voxel_mapper.courtyard_roof import pitched_shell
from voxel_mapper.mutiny_bay_courtyard import guard_native

class PitchedRoofTests(unittest.TestCase):
    def setUp(self):self.ring=Polygon(box(0,0,20,20).exterior,[box(5,5,15,15).exterior])
    def observed(self,x,z):
        p=Point(x,z)
        return 182+.6*min(p.distance(self.ring.exterior),p.distance(Polygon(self.ring.interiors[0]).boundary))
    def test_isolated_high_return_cannot_create_roof_spike(self):
        clean,c=pitched_shell(self.ring,lambda *p:178,self.observed)
        noisy,n=pitched_shell(self.ring,lambda *p:178,lambda x,z:210 if x<3 and z<3 else self.observed(x,z))
        self.assertLess(abs(c['eaves_odn_m']-n['eaves_odn_m']),.1)
        self.assertLess(max(r['y'] for r in noisy),187)
        self.assertEqual(len({(r['x'],r['z']) for r in noisy}),300)
        self.assertTrue(all(not box(5,5,15,15).contains(Point(r['x']+.5,r['z']+.5)) for r in noisy))
    def test_roof_voxels_form_one_connected_surface(self):
        rows,_=pitched_shell(self.ring,lambda *p:178,self.observed)
        roof={(r['x'],r['y'],r['z']) for r in rows if r['material']=='red_terracotta'}
        remaining=set(roof);queue=[remaining.pop()]
        while queue:
            x,y,z=queue.pop()
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                p=x+dx,y+dy,z+dz
                if p in remaining:remaining.remove(p);queue.append(p)
        self.assertEqual(len(remaining),0)
    def test_missing_height_is_not_filled_silently(self):
        with self.assertRaises(ValueError):pitched_shell(self.ring,lambda *p:178,lambda *p:None)
    def test_overhead_structure_survives_without_withholding_wall(self):
        rows=[dict(x=0,y=y,z=0,material='bricks') for y in (180,181)]
        def block(x,y,z):return SimpleNamespace(base_name='bars' if y==187 else 'stone_bricks' if y<=183 else 'air',extra_blocks=())
        kept,protected=guard_native(rows,block,preserve_overhead=True)
        self.assertEqual(protected,[])
        self.assertNotIn(187,{r['y'] for r in kept})
        self.assertEqual({r['y'] for r in kept if r['material']=='air'},{182,183})
    def test_direct_structural_collision_remains_protected(self):
        with self.assertRaises(ValueError):guard_native([dict(x=0,y=180,z=0)],lambda *p:SimpleNamespace(base_name='bars',extra_blocks=()),preserve_overhead=True)

    def test_quantized_block_top_does_not_add_an_extra_metre(self):
        rows,r=pitched_shell(self.ring,lambda *p:178,self.observed)
        self.assertEqual(max(row['y'] for row in rows)+1,math.ceil(r['roof_top_odn_range_m'][1]))
