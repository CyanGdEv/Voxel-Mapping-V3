import unittest
from shapely.geometry import box
from scripts.build_wicker_landscape_section import material_for_polygon,overlay,paving_spawn


class LandscapeSectionTests(unittest.TestCase):
    def test_spawn_uses_broad_paving_near_shop_and_excludes_beds(self):
        rows=[{'x':x,'z':z,'y':10,'kind':'path','material':'bricks'} for x in range(3) for z in range(3)]
        rows+=[{'x':x,'z':z,'y':10,'kind':'path','material':'dirt'} for x in range(4,7) for z in range(3)]
        self.assertEqual(paving_spawn(rows,{(7,1)}),[1,12,1])
        with self.assertRaises(ValueError):paving_spawn(rows[:1],{(7,1)})

    def test_whole_polygon_material_precedence_and_fallback(self):
        polygon=box(0,0,2,2)
        def annotations(*labels):
            return [{'text':label,'bbox':[.1,.1,.3,.3]} for label in labels]
        cases=[(('stone','brick'),'bricks'),(('concrete','brick'),'bricks'),
               (('stone','tarmac'),'black_concrete'),(('concrete','tar mac'),'black_concrete'),
               (('stone','concrete'),'light_gray_concrete'),(('stone',),'stone'),
               (('concrete',),'light_gray_concrete'),((),'stone'),
               (('brick','tarmac'),'bricks'),(('gravel',),'gravel')]
        from voxel_mapper.bedrock import ALLOWED_MATERIALS
        for labels,expected in cases:
            for state in ('existing','new'):
                for order in (labels,tuple(reversed(labels))):
                    with self.subTest(labels=order,state=state):
                        material,_,_=material_for_polygon(polygon,annotations(*order),state)
                        self.assertEqual(material,expected)
                        self.assertIn(material,ALLOWED_MATERIALS)
        outside=[{'text':'brick','bbox':[5,5,6,6]}]
        self.assertEqual(material_for_polygon(polygon,outside,'existing')[0],'stone')
        self.assertIn('unconfirmed',material_for_polygon(polygon,[],'new')[1])

    def test_clip_protection_grounding_and_missing_terrain(self):
        class Terrain:
            def sample(self,x,z):return None if x>2 else 10.8
        features=[{'polygon':box(-5,-5,5,5),'kind':'paving','material':'bricks','material_status':'documented'}]
        rows,report=overlay(features,Terrain(),[0,0,3,2],{(0,0)})
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['y']==10 and r['material']=='bricks' for r in rows))
        self.assertTrue(all(0<=r['x']<3 and 0<=r['z']<2 for r in rows))
        self.assertFalse(any(r['x']==r['z']==0 for r in rows))
        self.assertEqual(report[0]['missing_terrain_columns'],2)
        self.assertEqual(report[0]['protected_columns_skipped'],1)

    def test_planted_beds_and_rock_edges_use_above_ground_details(self):
        class Terrain:
            def sample(self,x,z):return 10.
        fs=[{'polygon':box(0,0,2,2),'kind':'planting_bed','material':'dirt','material_status':'estimated'},
            {'polygon':box(0,0,1,1),'kind':'rock_edge','material':'stone','material_status':'estimated'}]
        rows,_=overlay(fs,Terrain(),[0,0,2,2],set())
        self.assertTrue(any(r['material']=='dirt' and r['y']==10 for r in rows))
        self.assertTrue(any(r['material']=='stone' and r['y']==11 for r in rows))
        self.assertFalse(any(r['y']>11 for r in rows))
