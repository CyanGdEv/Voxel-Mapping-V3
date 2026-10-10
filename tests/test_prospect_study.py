import unittest
import itertools
from shapely.geometry import Point,box,mapping
from voxel_mapper.reconstruction.prospect import components,plan
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.generators import default_registry

class StudyTests(unittest.TestCase):
    def test_model_has_storeys_railings_stairs_and_shaped_roof(self):
        parts=components();ids={p['id'] for p in parts}
        self.assertIn('balcony-1',ids);self.assertIn('balcony-2',ids)
        self.assertIn('spiral-step-44',ids)
        self.assertTrue(any(i.startswith('roof-') for i in ids))
        self.assertEqual(len(ids),len(parts))
        for p in parts:self.assertLess(p['parameters']['bottom_m']['value'],p['parameters']['top_m']['value'])

    def test_both_studies_explicitly_withhold_park_placement(self):
        for factor in (1,4):
            rows,report,_=plan(factor)
            self.assertEqual(report['crs'],None)
            self.assertEqual(report['park_world_blocks_added'],0)
            self.assertEqual(report['geographic_placement'],'withheld')
            self.assertEqual(report['model_blocks_per_source_metre'],factor)
            self.assertTrue(rows)
            self.assertTrue(any(r['material']=='green_stained_glass_pane' for r in rows))

    def test_enlarged_export_rejects_geographic_or_survey_claims(self):
        from voxel_mapper.bedrock import export_world
        for changes in ({'crs':'EPSG:27700','vertical_datum':'STUDY_ZERO'}, {'crs':None,'vertical_datum':'ODN'}):
            with self.assertRaises(ValueError):
                export_world('unused','unused',{'voxel_size_m':1,'model_blocks_per_source_metre':4,**changes})

    def test_invalid_study_scale(self):
        for factor in (True,0,2,10):
            with self.assertRaises(ValueError):components(factor)

class RasterRuleTests(unittest.TestCase):
    def setUp(self):
        self.source=Source('s','survey','fixture://s','test','EPSG:27700','ODN','accepted')
        self.ctx=Context({'s':self.source},lambda x,z:100,box(-10,-10,10,10),'ODN')
        self.engine=ReconstructionEngine(default_registry())
    def part(self,id,geom,mat,priority):
        return {'id':id,'geometry_source':'s','geometry':mapping(geom),'parameters':{k:evidence(v,'s') for k,v in {'bottom_m':0,'top_m':1,'material':mat,'voxel_priority':priority}.items()}}
    def feature(self,parts):
        return Feature('f','architectural_components',mapping(Point(0,0)),'s',{k:evidence(v,'s') for k,v in {'base_elevation_m':100,'rotation_degrees':0,'components':parts}.items()})
    def test_priority_is_order_independent_and_equal_conflicts_withheld(self):
        a=self.part('a',box(0,0,1,1),'stone',1);b=self.part('b',box(0,0,1,1),'sandstone',2)
        for parts in ([a,b],[b,a]):
            rows,_=self.engine.plan([self.feature(parts)],self.ctx);self.assertEqual(rows[0]['material'],'sandstone')
        b['parameters']['voxel_priority']=evidence(1,'s')
        self.assertEqual(self.engine.plan([self.feature([a,b])],self.ctx)[0],[])
    def test_lower_priority_tie_does_not_override_resolved_top_material(self):
        parts=[self.part('a',box(0,0,1,1),'stone',1),self.part('b',box(0,0,1,1),'sandstone',1),self.part('c',box(0,0,1,1),'red_terracotta',2)]
        for order in itertools.permutations(parts):
            rows,_=self.engine.plan([self.feature(list(order))],self.ctx)
            self.assertEqual(rows[0]['material'],'red_terracotta')

    def test_centroid_reduces_thin_member_alias_and_rejects_large_footprints(self):
        p=self.part('a',box(.9,.9,1.1,1.1),'sandstone_wall',1)
        p['parameters']['raster_rule']=evidence('centroid','s')
        rows,_=self.engine.plan([self.feature([p])],self.ctx);self.assertEqual(len(rows),1)
        p['geometry']=mapping(box(0,0,4,4))
        self.assertEqual(self.engine.plan([self.feature([p])],self.ctx)[0],[])
    def test_invalid_and_unevidenced_priorities_withheld(self):
        for priority in (True,101,1.5):
            p=self.part('a',box(0,0,1,1),'stone',priority)
            self.assertEqual(self.engine.plan([self.feature([p])],self.ctx)[0],[])
        p=self.part('a',box(0,0,1,1),'stone',1);p['parameters']['raster_rule']='centroid'
        self.assertEqual(self.engine.plan([self.feature([p])],self.ctx)[0],[])

if __name__=='__main__':unittest.main()
