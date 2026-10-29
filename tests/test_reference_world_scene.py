from collections import defaultdict
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image
from shapely.geometry import LineString, Polygon, Point

from voxel_mapper.alton_aligned_world import _local_mask
from voxel_mapper.reference_world_scene import ReferenceScene, thin
from voxel_mapper.supported_ride_layouts import grid_segment, mapped_ways, crossing_constraints, resolve_profiles


class ReferenceWorldTests(unittest.TestCase):
    def test_shaded_queue_strokes_thin_without_joining_separate_lanes(self):
        a=np.zeros((40,50),bool);a[5:12,5:40]=True;a[23:30,5:40]=True
        b=thin(a)
        self.assertLess(b.sum(),a.sum()/3)
        self.assertTrue(b[5:12].any());self.assertTrue(b[23:30].any())
        self.assertFalse(b[12:23].any())

    def test_steep_native_track_segments_are_face_connected(self):
        a=(1,4,-8);b=(5,11,-4);points=list(grid_segment(a,b))
        self.assertEqual(points[0],a);self.assertEqual(points[-1],b)
        self.assertTrue(all(sum(abs(x-y) for x,y in zip(p,q))==1 for p,q in zip(points,points[1:])))

    def test_shared_osm_nodes_extend_route_but_xy_crossing_does_not(self):
        xml='''<osm>
        <node id="1" lon="1" lat="1"/><node id="2" lon="3" lat="1"/>
        <node id="3" lon="3" lat="3"/><node id="4" lon="2" lat="0"/><node id="5" lon="2" lat="2"/>
        <node id="6" lon="2" lat="1"/><node id="7" lon="2" lat="3"/>
        <way id="10"><nd ref="1"/><nd ref="6"/><nd ref="2"/><tag k="roller_coaster" v="track"/><tag k="name" v="Galactica"/></way>
        <way id="11"><nd ref="2"/><nd ref="3"/><tag k="roller_coaster" v="track"/></way>
        <way id="12"><nd ref="4"/><nd ref="5"/><tag k="roller_coaster" v="track"/></way>
        <way id="13"><nd ref="6"/><nd ref="7"/><tag k="roller_coaster" v="track"/></way>
        </osm>'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'osm.xml';p.write_text(xml)
            rows=mapped_ways(p,SimpleNamespace(transform=lambda x,y:(x,y)),['Galactica'])
        self.assertEqual({r['id'] for r in rows},{'10','11','13'})

    def way(self,id,points,layer,nodes):
        line=LineString(points);s=np.linspace(0,line.length,21)
        return {'id':str(id),'nodes':nodes,'line':line,'layer':layer,'ride':'Galactica',
                'node_stations':np.array([0,line.length]),'s':s,'height':np.full(21,10.),
                'minimum':np.zeros(21),'upper':np.full(21,np.inf)}

    def test_distinct_crossing_passes_keep_different_heights(self):
        a=self.way(1,[(-10,0),(10,0)],0,['a','b'])
        b=self.way(2,[(0,-10),(0,10)],1,['c','d'])
        c=crossing_constraints([a,b]);self.assertEqual(len(c),1)
        error=resolve_profiles([a,b],c)
        self.assertLess(error,.01);self.assertGreaterEqual(b['height'][10]-a['height'][10],5.98)
        self.assertEqual(a['nodes'],['a','b'])

    def test_true_shared_endpoint_is_a_joint_and_not_an_overpass(self):
        a=self.way(1,[(0,0),(10,0)],0,['a','join'])
        b=self.way(2,[(10,0),(10,10)],1,['join','b']);b['height'][:]=20
        c=crossing_constraints([a,b]);self.assertEqual(c,[])
        self.assertLess(resolve_profiles([a,b],c),.01)
        self.assertAlmostEqual(a['height'][-1],b['height'][0])

    def scene(self):
        scene=ReferenceScene.__new__(ReferenceScene)
        rr,cc=np.indices((16,16))
        scene.l=SimpleNamespace(width=16,height=16,e0=0,n0=0,n1=16,bounds=[0,0,16,16],
            ground=np.full((16,16),64),footprints=np.zeros((16,16),bool),water=np.full((16,16),-32768),
            family=np.zeros((16,16),np.uint8),surface_source=np.zeros((16,16),np.uint8),
            material=np.full((16,16),'grass_block',dtype='U24'),rgb=np.full((16,16,3),70,np.float32),
            visible=np.zeros((16,16),bool),ee=cc+.5,nn=15.5-rr)
        scene.old_solid={(3,68,-5)};scene.old_air={(3,69,-5)};scene.air=set();scene.blocks={}
        scene.roles=defaultdict(set);scene.local_mask=_local_mask;scene.records=[]
        scene.nonpaving=np.zeros((16,16),bool);scene.before_material=scene.l.material.copy()
        scene.changed_surface=np.zeros((16,16),bool)
        return scene

    def test_user_boundary_paving_survives_canopy_and_keeps_building_water_out(self):
        scene=self.scene();scene.l.footprints[12,3]=True;scene.l.water[13,3]=64
        scene.paint(Polygon([(2,2),(6,2),(6,6),(2,6)]),'explicit-path')
        self.assertEqual(int((scene.l.family>0).sum()),14)
        self.assertEqual(scene.l.material[12,3],'grass_block')
        self.assertTrue(np.all(scene.l.ground==64))

    def test_new_structure_cannot_fill_retained_track_or_running_air(self):
        scene=self.scene()
        self.assertFalse(scene.add(3,68,-5,'oak_log','new'))
        self.assertFalse(scene.add(3,69,-5,'oak_log','new'))
        self.assertTrue(scene.add(3,72,-5,'oak_log','new'))

    def test_acoustic_wall_replaces_its_own_air_but_not_retained_running_air(self):
        scene=self.scene();scene.clearance(3,72,-5)
        self.assertTrue(scene.add(3,72,-5,'dark_oak_planks','wall',respect_air=False))
        self.assertNotIn((3,72,-5),scene.air)
        self.assertFalse(scene.add(3,69,-5,'dark_oak_planks','wall',respect_air=False))

    def test_queue_railings_are_outside_the_marked_walkable_lane(self):
        scene=self.scene();labels=np.full((40,50),255,np.uint8);labels[20:27,8:44]=13
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);Image.fromarray(labels).save(folder/'reference-labels.png')
            scene.references={'queue':(folder,{}, {})}
            scene.xy=lambda key,p:np.column_stack([np.asarray(p)[:,0]/5,16-np.asarray(p)[:,1]/5])
            scene.queue({'id':'queue','source':'queue','label_code':13})
        self.assertTrue(scene.blocks)
        self.assertNotEqual(scene.l.material[5,5],'grass_block')
        self.assertFalse(any(abs(x+.5-5)<1 and abs((-z-.5)-11.4)<.5 for x,y,z in scene.blocks))
