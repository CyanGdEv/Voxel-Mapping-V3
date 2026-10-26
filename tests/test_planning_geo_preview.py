"""Map alignment keeps scale fixed and terrain coverage fails closed."""
from concurrent.futures import CancelledError
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box,LineString,mapping
from voxel_mapper import planning_geo_preview as geo
from voxel_mapper import courtyard_plan_expansion


class GeographicPreviewTests(unittest.TestCase):
    def test_rigid_fit_preserves_metres_without_stretching(self):
        source=np.array([[0,0],[10,0],[0,10]])
        angle=.2;R=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        target=source@R.T+[100,200];aff=geo.rigid_fit(source,target)
        np.testing.assert_allclose(np.array(aff[:4]).reshape(2,2),R,atol=1e-12)
        np.testing.assert_allclose(aff[4:],[100,200],atol=1e-12)
        stretched=geo.rigid_fit(source,2*source+[100,200]);matrix=np.array(stretched[:4]).reshape(2,2)
        np.testing.assert_allclose(matrix.T@matrix,np.eye(2),atol=1e-12)

    def test_reflection_collinearity_and_duplicate_controls_are_rejected(self):
        a=[[0,0],[10,0],[0,10]]
        for first,second in [(a,[[0,0],[-10,0],[0,10]]),([[0,0],[1,0],[2,0]],[[0,1],[1,1],[2,1]]),([[0,0],[0,0],[1,1]],a)]:
            with self.assertRaises(ValueError):geo.rigid_fit(first,second)

    def test_terrain_has_no_interpolation_or_silent_cropping(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'dtm.tif';data=np.full((4,4),180.7,dtype='float32')
            def save():
                with rasterio.open(path,'w',driver='GTiff',width=4,height=4,count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(0,4,1,1),nodata=-9999) as ds:ds.write(data,1)
            save();sampled={'bounds':[0,0,4,4]};aff=[1,0,0,1,0,0]
            heights,report=geo.terrain_heights(sampled,aff,path)
            self.assertEqual(set(heights.values()),{180});self.assertEqual(report['sampled_cells'],16)
            self.assertFalse(report['finished_floor_levels_verified'])
            data[2,2]=-9999;save()
            with self.assertRaises(ValueError):geo.terrain_heights(sampled,aff,path)
            with self.assertRaises(ValueError):geo.terrain_heights({'bounds':[-1,0,4,4]},aff,path)
            with self.assertRaises(CancelledError):geo.terrain_heights(sampled,aff,path,cancelled=lambda:True)

    def test_multiple_objects_fit_and_other_map_checks_stay_held_out(self):
        preset=copy.deepcopy(geo.profile());preset['source_metres_per_native_point']=1
        source=[box(-1,-1,1,1),box(9,-1,11,1),box(-1,9,1,11)];rows=[];elements=[]
        from shapely.affinity import translate
        for c,g in zip(preset['controls'],source):
            rows.append({'id':c['label'],'labels':[{'text':c['label']}],'geometry_pdf_native':mapping(g)})
            elements.append({'type':'way','id':c['osm_way_id'],'geometry':[{'lon':x,'lat':y} for x,y in translate(g,100,200).exterior.coords],'tags':{'building':'yes'}})
        held=preset['held_out_references'];court=box(20,20,30,30);near=box(35,35,40,40)
        for identifier,g in [(held['courtyard_inner_way_id'],court),(held['nearby_building_way_id'],near)]:
            elements.append({'type':'way','id':identifier,'geometry':[{'lon':x+100,'lat':y+200} for x,y in g.exterior.coords],'tags':{}})
        elements.append({'type':'way','id':100,'geometry':[{'lon':100,'lat':200},{'lon':110,'lat':200}],'tags':{'name':'Wicker Man','roller_coaster':'track'}})
        data={'layout':{'document_sha256':preset['document_sha256'],'candidates':[{'id':held['nearby_building_candidate_prefix'],'geometry_nominal_local':mapping(near)}]},
              'buildings':{'records':rows},'markings':{'records':[{'role':'track_centre','geometry_pdf_native':mapping(LineString([(0,0),(10,0)]))}]}}
        class Identity:
            def transform(self,x,y):return x,y
            def report(self):return {'fixture':True}
        with patch.object(geo,'profile',return_value=preset),patch.object(courtyard_plan_expansion,'geometry',return_value=([{'key':'courtyard-floor','geometry_nominal_local':mapping(court)}],{})):
            result,_=geo.alignment(data,{'elements':elements},Identity())
        self.assertEqual(result['scale'],1);self.assertFalse(result['independent_registration_verified'])
        self.assertFalse(result['production_placement_eligible'])
        for check in result['held_out_map_checks'].values():self.assertFalse(check['used_to_fit'])
        self.assertLess(result['held_out_map_checks']['track']['p95_distance_m'],1e-10)

    def test_changed_pinned_input_fails_before_world_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);osm=root/'osm.json';osm.write_text('{}')
            config={'version':'planning-geographic-preview-v1','terrain_vertical_datum':'ODN','geometry_request':{}}
            for key in ('osm','dtm','grid'):config[key+'_path']=str(osm);config[key+'_sha256']='0'*64
            with self.assertRaises(ValueError):geo.run(config,root/'world')
            self.assertFalse((root/'world').exists())


if __name__=='__main__':unittest.main()
