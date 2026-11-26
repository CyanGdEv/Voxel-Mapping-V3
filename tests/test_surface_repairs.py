import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from voxel_mapper.ground_surface import assess_lawn_column
from tools.plan_surface_repairs import accept


def cell():
    return {'x':8,'z':10,'label':1,'safe_interior':True,'dtm':192.,'dsm':192.02,
      'supported_storage':True,'block_entities':False,'native_top_y':95,
      'native_profile':{'92':'minecraft:dirt','93':'minecraft:stone_bricks','94':'minecraft:air',
                        '95':'minecraft:deepslate_tiles','96':'minecraft:air'}}


class SurfaceRepairTests(unittest.TestCase):
    def test_measured_lawn_proposal_is_not_automatic_acceptance(self):
        p=assess_lawn_column(cell(),surface_offset_m=98)
        self.assertEqual(p['status'],'candidate');self.assertEqual(len(p['edits']),2)
        self.assertEqual(p['height_update'],{'xz':[8,10],'before':96,'after':94})
        self.assertTrue(all('accepted' not in e for e in p['edits']))
        c=cell();c['native_top_y']=93;c['native_profile']={'92':'minecraft:dirt','93':'minecraft:grass_block','94':'minecraft:air'}
        self.assertEqual(assess_lawn_column(c,surface_offset_m=98)['status'],'already_matches')

    def test_generic_paving_permits_roof_removal_without_material_replacement(self):
        c=cell();c['label']=9
        self.assertEqual(assess_lawn_column(c,surface_offset_m=98)['status'],'withheld')
        result=assess_lawn_column(c,surface_offset_m=98,allow_paving_roof_only=True)
        self.assertEqual(len(result['edits']),1)
        self.assertEqual(result['edits'][0]['after'],'minecraft:air')
        self.assertTrue(all(e['xyz'][1]!=93 for e in result['edits']))
        c['native_profile']['93']='minecraft:grass_block'
        self.assertEqual(assess_lawn_column(c,surface_offset_m=98,allow_paving_roof_only=True)['status'],'withheld')

    def test_uncertain_heights_boundaries_and_retained_geometry_survive(self):
        variants=[]
        for key,val in [('safe_interior',False),('label',9),('dtm',None),('dsm',float('nan')),
                        ('dsm',191.99),('dsm',193.),('dtm',192.3),('block_entities',True),('supported_storage',False)]:
            c=cell();c[key]=val;variants.append(c)
        for y,block in [('92','minecraft:air'),('93','minecraft:deepslate_tiles'),('94','minecraft:oak_leaves'),
                        ('94','minecraft:water'),('95','minecraft:stone_bricks')]:
            c=cell();c['native_profile'][y]=block;variants.append(c)
        c=cell();del c['native_profile']['94'];variants.append(c)
        c=cell();c['dtm']=192.3;c['dsm']=192.32;variants.append(c)
        for c in variants:
            r=assess_lawn_column(c,surface_offset_m=98)
            self.assertEqual(r['status'],'withheld',c);self.assertEqual(r['edits'],[])

    def test_existing_canopy_overhang_is_preserved_and_identified(self):
        c=cell();c.update(supported_storage=False,native_column_status='height_metadata_differs_from_observed_top',
                         native_observed_top_y=112,native_observed_top_block='minecraft:oak_leaves')
        result=assess_lawn_column(c,surface_offset_m=98)
        self.assertEqual(result['reason'],'retained_overhanging_vegetation')
        self.assertEqual(result['edits'],[])

    def test_review_is_bound_to_proposals_and_only_qualified_coordinates(self):
        p=assess_lawn_column(cell(),surface_offset_m=98)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);proposals=root/'proposals.json';review=root/'review.json'
            proposals.write_text(json.dumps({'baseline_sha256':'a'*64,'cells':[{'x':8,'z':10,**p}]}))
            r={'proposals_sha256':hashlib.sha256(proposals.read_bytes()).hexdigest(),
               'accepted_for_scoped_preview':True,'accepted_columns':[[8,10]]}
            review.write_text(json.dumps(r));args=argparse.Namespace(proposals=proposals,review=review)
            result=accept(args);self.assertEqual(len(result['edits']),2)
            self.assertEqual(result['baseline_sha256'],'a'*64)
            for key,value in [('proposals_sha256','wrong'),('accepted_for_scoped_preview',False),('accepted_columns',[[999,10]])]:
                bad={**r,key:value};review.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):accept(args)


class GridPreparationTests(unittest.TestCase):
    def test_rejects_shifted_pixel_centres_and_coarse_height_evidence(self):
        import io
        import zipfile
        import numpy as np
        import rasterio
        from rasterio.transform import Affine
        from PIL import Image
        from tools.plan_surface_repairs import prepare
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);dataset=root/'source.zip';reg=root/'registration.json'
            reg.write_text(json.dumps({'blocks_per_metre':1,'horizontal_crs':'EPSG:27700',
                'world_grid_edge_to_bng_affine':[1,0,1000,0,-1,2000],
                'vertical_ground_surface':{'rounded_surface_offset_m':98}}))
            blob=io.BytesIO();Image.fromarray(np.ones((8,8),np.uint8)).save(blob,format='PNG')
            for shift,res in [(0,1),(.25,1),(0,2)]:
                with zipfile.ZipFile(dataset,'w') as z:
                    z.writestr('labels.png',blob.getvalue())
                    z.writestr('manifest.json',json.dumps({'label_map':{'1':'grass_unspecified'},'samples':[
                        {'sample_id':'fixture','labels':'labels.png','georef':{'crs':'EPSG:27700','transform':[1,0,1000+shift,0,-1,2000]}}]}))
                tif=root/'height.tif'
                with rasterio.open(tif,'w',driver='GTiff',height=8,width=8,count=1,dtype='float32',
                    crs='EPSG:27700',transform=Affine(res,0,1000,0,-res,2000)) as dst:
                    dst.write(np.full((8,8),192,np.float32),1)
                args=argparse.Namespace(dataset=dataset,sample='fixture',registration=reg,dtm=tif,dsm=tif)
                if not shift and res==1:
                    result=prepare(args);self.assertEqual(len(result['cells']),64)
                    self.assertEqual(result['cells'][0]['x'],0);self.assertFalse(result['accepted_for_block_edits'])
                else:
                    with self.assertRaises(ValueError):prepare(args)


class AreaMergeTests(unittest.TestCase):
    def request(self,name='one',label=1,safe=False):
        return {'surface_offset_m':98,'registration_sha256':'r','dataset_sha256':'d',
                'dtm_sha256':'t','dsm_sha256':'s','paving_roof_only':True,'source_sample':name,
                'source_split_group':'area','accepted_for_block_edits':False,
                'cells':[{'x':0,'z':0,'easting':1000.5,'northing':1999.5,'dtm':192.,'dsm':192.01,
                          'label':label,'safe_interior':safe}]}

    def test_overlapping_samples_do_not_duplicate_evidence_or_revive_conflicts(self):
        from tools.plan_surface_repairs import merge_area_requests
        result=merge_area_requests([self.request(),self.request('two',safe=True)])
        self.assertEqual(result['unique_native_cells'],1)
        self.assertEqual(result['overlapping_observations_deduplicated'],1)
        self.assertTrue(result['cells'][0]['safe_interior'])
        self.assertEqual(result['source_split_groups'],['area'])
        self.assertNotIn('source_split_group',result)
        self.assertFalse(result['accepted_for_block_edits'])
        accepted=self.request();accepted['accepted_for_block_edits']=True
        self.assertFalse(merge_area_requests([accepted])['accepted_for_block_edits'])
        conflict=merge_area_requests([self.request(),self.request('two',label=9),self.request('three',safe=True)])
        self.assertEqual(conflict['cells'][0]['label'],255)
        self.assertFalse(conflict['cells'][0]['safe_interior'])
        self.assertEqual(conflict['conflicting_cells_ignored'],1)

    def test_mixed_sources_and_shifted_overlaps_are_rejected(self):
        from tools.plan_surface_repairs import merge_area_requests
        other=self.request('two');other['dtm_sha256']='different'
        with self.assertRaises(ValueError):merge_area_requests([self.request(),other])
        other=self.request('two');other['cells'][0]['northing']+=.25
        with self.assertRaises(ValueError):merge_area_requests([self.request(),other])
