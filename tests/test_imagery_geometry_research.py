import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings

import numpy as np
from pyproj import Transformer
from shapely.geometry import box,LineString,shape,mapping
from shapely.ops import transform
from voxel_mapper import imagery_geometry_research as geo, aerial_material_research as aerial
from test_aerial_material_research import config as aerial_config, cache_fixture

warnings.filterwarnings('ignore',category=DeprecationWarning,module='voxel_mapper.imagery_geometry_research')


def scene():
    image=np.full((256,256,4),255,np.uint8);image[:,:,:3]=[40,145,45]
    image[10:240,10:240,:3]=[145,145,145]
    image[20:80,20:90,:3]=[145,80,55]
    image[20:80,140:210,:3]=[40,110,200]
    image[35:55,160:180,:3]=[40,145,45]
    image[90:120,10:50,:3]=[10,10,10]
    def pixel_box(left,top,right,bottom):return box(left/2,128-bottom/2,right/2,128-top/2)
    refs=[{'id':'roof','kind':'building','geometry':pixel_box(22,22,88,78),'tags':{}},
        {'id':'pond','kind':'water','geometry':pixel_box(140,20,210,80),'tags':{}},
        {'id':'walk','kind':'paving','geometry':LineString([(10,30),(115,30)]),'tags':{}},
        {'id':'queue','kind':'queue','geometry':LineString([(15,48),(90,48)]),'tags':{'footway':'queue'}}]
    inverse=Transformer.from_crs(3857,4326,always_xy=True)
    a,b=inverse.transform(0,0);c,d=inverse.transform(128,128)
    return image,[0,0,128,128],[a,b,c,d],refs,pixel_box(200,150,235,210)


def aligned_aerial_config():
    a=aerial_config();project=Transformer.from_crs(3857,4326,always_xy=True)
    west,south=project.transform(-210000,6980000);east,north=project.transform(-209800,6980200)
    a['bounds_wgs84']=[west,south,east,north];return a


def options():return {'min_area_m2':1,'max_growth_m':3,'colour_distance':18,'max_features':256,'simplify_pixels':0}


class ImageryGeometryTests(unittest.TestCase):
    def extract(self,refs=None,protected=None):
        image,extent,bounds,original,plan=scene()
        return geo.extract(image,extent,bounds,original if refs is None else refs,plan if protected is None else protected,options(),footer=0)

    def test_rgb_region_boundaries_are_extracted_with_roof_role_and_pond_hole(self):
        features,queues,report=self.extract()
        kinds=[f['properties']['kind'] for f in features]
        self.assertIn('building',kinds);self.assertIn('water',kinds);self.assertIn('paving',kinds)
        roof=next(f for f in features if f['properties']['kind']=='building')
        self.assertEqual(roof['properties']['boundary_role'],'roof_colour_region_not_ground_footprint')
        project=Transformer.from_crs(4326,3857,always_xy=True)
        roof_shape=transform(project.transform,shape(roof['geometry']))
        self.assertGreater(roof_shape.area,scene()[3][0]['geometry'].area)
        pond=next(f for f in features if f['properties']['kind']=='water')
        self.assertTrue(shape(pond['geometry']).interiors)
        self.assertTrue(all(not f['properties']['registration_verified'] for f in features))

    def test_protected_plan_polygons_are_not_overwritten_and_queue_width_is_not_invented(self):
        features,queues,report=self.extract();protected=scene()[4];project=Transformer.from_crs(4326,3857,always_xy=True)
        self.assertGreater(report['protected_pixels_excluded'],0)
        for f in features:
            self.assertLess(transform(project.transform,shape(f['geometry'])).intersection(protected).area,1e-7)
        self.assertEqual(len(queues),1);self.assertFalse(queues[0]['properties']['width_inferred'])
        self.assertFalse(queues[0]['properties']['switchbacks_invented'])
        self.assertEqual(queues[0]['properties']['geometry_source'],'mapped_queue_centreline')

    def test_covered_queue_is_retained_as_map_reference_without_claiming_rgb_visibility(self):
        image,extent,bounds,refs,plan=scene()
        refs[-1]['tags']['covered']='yes'
        features,queues,report=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        self.assertEqual(queues[0]['properties']['rgb_support_status'],'mapped_reference_covered_not_visible')
        self.assertEqual(report['queue_lines_with_rgb_support'],0)
        refs[-1]['tags']={};refs[-1]['geometry']=LineString([(15,108),(40,108)])
        features,queues,report=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        self.assertEqual(queues[0]['properties']['rgb_visible_support_fraction'],0)

    def test_colour_alone_does_not_invent_buildings_water_identity_or_queue_lines(self):
        features,queues,report=self.extract(refs=[])
        kinds={f['properties']['kind'] for f in features}
        self.assertNotIn('building',kinds);self.assertNotIn('water',kinds)
        self.assertIn('unclassified_blue_surface',kinds);self.assertEqual(queues,[])
        self.assertGreater(report['shadow_pixels_unresolved'],0)

    def test_paving_does_not_promote_a_whole_connected_hard_surface(self):
        image,extent,bounds,refs,plan=scene()
        # Uniform paving-looking asphalt stretches far beyond the short map
        # reference. It must remain unclassified outside the growth window.
        refs=[{'id':'short-walk','kind':'paving','geometry':LineString([(20,15),(30,15)]),'tags':{}}]
        features,_,report=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        project=Transformer.from_crs(4326,3857,always_xy=True)
        paved=[transform(project.transform,shape(f['geometry'])) for f in features if f['properties']['kind']=='paving']
        self.assertTrue(paved)
        for g in paved:
            # Include the half-metre seed/search padding and raster cell edge.
            self.assertLess(g.difference(refs[0]['geometry'].buffer(4.3)).area,1e-7)
        self.assertIn('unclassified_hard_surface',{f['properties']['kind'] for f in features})
        self.assertFalse(report['paving_refinement']['neural_weights_updated'])

    def test_paving_keeps_grass_building_water_parking_and_plan_as_holes(self):
        image,extent,bounds,refs,plan=scene()
        def pb(l,t,r,b):return box(l/2,128-b/2,r/2,128-t/2)
        refs.append({'id':'whole-square','kind':'paving','geometry':pb(10,10,240,240),'tags':{}})
        refs.append({'id':'car-park','kind':'parking','geometry':pb(100,140,130,170),'tags':{}})
        image[140:170,140:170,:3]=[40,145,45]
        features,_,_=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        project=Transformer.from_crs(4326,3857,always_xy=True)
        for f in features:
            if f['properties']['kind']!='paving':continue
            g=transform(project.transform,shape(f['geometry']))
            for barrier in [refs[0]['geometry'],refs[1]['geometry'],refs[-1]['geometry'],pb(141,141,169,169),plan]:
                self.assertLess(g.intersection(barrier).area,1e-7)
            self.assertEqual(f['properties']['geometry_source'],'map_seeded_rgb_paving')

    def test_covered_paving_and_missing_map_do_not_produce_visible_paving(self):
        image,extent,bounds,refs,plan=scene()
        for ref in refs:
            if ref['kind'] in ('paving','queue'):ref['tags']['covered']='yes'
        features,_,report=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        self.assertNotIn('paving',{f['properties']['kind'] for f in features})
        self.assertEqual(len(report['paving_refinement']['withheld_references']),2)

    def test_opaque_nodata_and_cancellation_stay_unresolved(self):
        image,extent,bounds,refs,plan=scene();image[:,:,3]=0
        features,queues,report=geo.extract(image,extent,bounds,refs,plan,options(),footer=0)
        self.assertEqual(features,[])
        with self.assertRaises(aerial.CancelledError):geo.extract(image,extent,bounds,refs,plan,options(),cancelled=lambda:True)

    def test_geometry_outside_requested_area_is_not_exported(self):
        image,extent,bounds,refs,plan=scene()
        features,queues,report=geo.extract(image,extent,[10,10,10.001,10.001],refs,plan,options(),footer=0)
        self.assertEqual(features,[]);self.assertEqual(queues,[])

    def test_coverage_hash_crs_and_geometry_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'coverage.geojson';p.write_text(json.dumps({'type':'FeatureCollection','features':[{'geometry':mapping(box(0,0,1,1))}]}))
            spec={'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'crs':'EPSG:3857'}
            protected,pin=geo.protected_coverage(spec);self.assertEqual(protected.area,1)
            p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):geo.protected_coverage(spec)

    def test_job_and_desktop_use_pinned_rgb_and_resolve_relative_coverage(self):
        from voxel_mapper.desktop_runtime import DesktopRuntime
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=aligned_aerial_config();cache_fixture(root,a)
            c={'version':geo.VERSION,'site_id':a['site_id'],'site':a['site'],'imagery':a,
                'options':{'min_area_m2':1,'simplify_pixels':0}}
            plan=root/'plan.geojson';plan.write_text(json.dumps({'type':'FeatureCollection','features':[]}))
            c['protected_plan_coverage']={'file':'plan.geojson','sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'crs':'EPSG:4326'}
            request=root/'request.json';request.write_text(json.dumps(c));desktop=root/'desktop';shutil.copytree(root/'cache',desktop/'web-cache')
            runtime=DesktopRuntime(desktop,workers=1,memory_budget_mb=2048)
            try:
                jid=runtime.submit('imagery_geometry_research',request);runtime._futures[jid].result(timeout=40)
                job=runtime.store.job(jid);self.assertEqual(job['status'],'completed',job.get('error'))
                self.assertIn('unclassified_hard_surface',job['result']['candidate_counts'])
                self.assertEqual(job['result']['world_blocks_generated'],0)
                self.assertEqual(job['result']['network_bytes'],0)
                self.assertTrue(job['result']['paving_refinement']['map_guided'])
                self.assertIn('imagery_geometry_observation',runtime.store.context(20000))
            finally:runtime.close(wait=True)

    def test_research_cycle_retains_geometry_and_reuses_neural_checkpoint(self):
        from test_research_learning_cycle import ResearchLearningCycleTests
        from voxel_mapper import research_learning_cycle as cycle
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=aligned_aerial_config();cache_fixture(root,a);c=ResearchLearningCycleTests().config(root);c['max_research_jobs']=0
            c['public_sites'][0]['imagery_geometry_context']={'version':geo.VERSION,'site_id':a['site_id'],'site':a['site'],'imagery':a,'options':{'min_area_m2':1}}
            first=cycle.run(c,root/'first',root/'memory',root/'cache')
            second=cycle.run(c,root/'second',root/'memory',root/'cache')
            self.assertTrue(first['imagery_geometry_reports']);self.assertFalse(second['model_weights_updated'])
            self.assertEqual(first['checkpoint_sha256'],second['checkpoint_sha256'])
            self.assertEqual(first['web_sources_automatically_labelled'],0)


if __name__=='__main__':unittest.main()
