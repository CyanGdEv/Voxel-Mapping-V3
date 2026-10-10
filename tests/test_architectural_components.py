import unittest
from shapely.geometry import Point,box,mapping,Polygon
from voxel_mapper.reconstruction.model import Source,Feature
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.reconstruction.engine import Context,ReconstructionEngine
from voxel_mapper.reconstruction.generators import default_registry

class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.sources={'survey':Source('survey','survey','fixture://survey','test','EPSG:27700','ODN','accepted')}
        self.ctx=Context(self.sources,lambda x,z:100,box(-50,-50,50,50),'ODN')
        self.engine=ReconstructionEngine(default_registry())
    def part(self,id,geom,bottom=0,top=3,material='stone'):
        return {'id':id,'geometry_source':'survey','geometry':mapping(geom),'parameters':{k:evidence(v,'survey') for k,v in {'bottom_m':bottom,'top_m':top,'material':material}.items()}}
    def feature(self,parts,angle=0):
        return Feature('tower','architectural_components',mapping(Point(0,0)),'survey',{k:evidence(v,'survey') for k,v in {'base_elevation_m':100,'rotation_degrees':angle,'components':parts}.items()})
    def test_separate_columns_balcony_and_inner_void(self):
        ring=Polygon([(0,0),(6,0),(6,6),(0,6)],holes=[[(1,1),(5,1),(5,5),(1,5)]])
        f=self.feature([self.part('ring',ring),self.part('balcony',box(-1,-1,7,7),3,4)])
        rows,report=self.engine.plan([f],self.ctx);cells={(r['x'],r['y'],r['z']) for r in rows}
        self.assertEqual(report['decisions'][0]['status'],'planned')
        self.assertNotIn((2,101,2),cells);self.assertIn((2,103,2),cells)
    def test_rotation_and_thin_column_retained(self):
        rows,_=self.engine.plan([self.feature([self.part('post',box(2,.1,2.1,.2),0,2)],90)],self.ctx)
        self.assertEqual({(r['x'],r['z']) for r in rows},{(-1,2)})
    def test_estimated_part_and_unknown_registration_withheld(self):
        p=self.part('post',box(0,0,1,1));p['parameters']['top_m']['status']='estimated'
        f=self.feature([p]);self.assertFalse(self.engine.plan([f],self.ctx)[0])
        self.ctx.allow_estimates=True;self.assertTrue(self.engine.plan([f],self.ctx)[0])
        p['geometry_source']='missing';self.assertFalse(self.engine.plan([f],self.ctx)[0])
    def test_conflict_and_existing_collision_roll_back_whole_structure(self):
        f=self.feature([self.part('one',box(0,0,1,1)),self.part('two',box(0,0,1,1),material='oak_planks')])
        self.assertFalse(self.engine.plan([f],self.ctx)[0])
        from voxel_mapper.bedrock import material_block
        self.ctx.occupied=lambda x,y,z:material_block('oak_planks')
        self.assertFalse(self.engine.plan([self.feature([self.part('one',box(0,0,1,1))])],self.ctx)[0])
    def test_bad_datum_and_duplicate_component_rejected(self):
        p=self.part('one',box(0,0,1,1));self.assertFalse(self.engine.plan([self.feature([p,p])],self.ctx)[0])
        self.ctx.vertical_datum='ellipsoid';self.assertFalse(self.engine.plan([self.feature([p])],self.ctx)[0])
