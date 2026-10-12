import unittest
from types import SimpleNamespace
from shapely.geometry import Polygon,box,Point
from voxel_mapper.mutiny_bay_courtyard import wing_shell,guard_native

class CourtyardTests(unittest.TestCase):
    def setUp(self):self.ring=Polygon(box(0,0,10,10).exterior,[box(3,3,7,7).exterior])
    def test_shell_preserves_hole_and_ground_and_hollows_wings(self):
        rows,r=wing_shell(self.ring,lambda x,z:178.2,lambda x,z:185.2)
        self.assertEqual(r['mapped_columns'],84)
        self.assertTrue(any(x['material']=='air' for x in rows))
        self.assertTrue(all(x['y']>=180 for x in rows))
        self.assertTrue(all(not box(3,3,7,7).contains(Point(x['x']+.5,x['z']+.5)) for x in rows))
        self.assertEqual({x['y'] for x in rows if x['material']=='red_terracotta'},{186})
    def test_missing_or_unsupported_surface_rejects_build(self):
        for surface in (lambda x,z:None,lambda x,z:float('nan'),lambda x,z:180,lambda x,z:200):
            with self.assertRaises(ValueError):wing_shell(self.ring,lambda x,z:178,surface)
    def test_conflict_and_canopy_column_are_protected(self):
        rows=[dict(x=x,y=y,z=0,material='air') for x in range(3) for y in (180,181)]
        def native(x,y,z):
            return SimpleNamespace(base_name='iron_block' if x==1 and y==181 else 'air' if x==2 else 'stone_bricks',extra_blocks=())
        kept,protected=guard_native(rows,native)
        self.assertEqual({r['x'] for r in kept},{0});self.assertEqual(protected,[[1,0],[2,0]])
    def test_extra_blocks_are_not_cleared(self):
        with self.assertRaises(ValueError):guard_native([dict(x=0,y=180,z=0)],lambda *p:SimpleNamespace(base_name='stone_bricks',extra_blocks=('water',)))

    def test_former_flat_cap_is_cleared_without_extending_roof(self):
        rows=[dict(x=0,y=y,z=0,material='red_terracotta' if y==184 else 'air') for y in range(180,185)]
        def native(x,y,z):return SimpleNamespace(base_name='stone_bricks' if y<=185 else 'stone' if y==186 else 'air',extra_blocks=())
        kept,protected=guard_native(rows,native)
        self.assertEqual(protected,[])
        self.assertEqual({r['y'] for r in kept if r['y']>184},{185,186})
        self.assertTrue(all(r['material']=='air' for r in kept if r['y']>184))
