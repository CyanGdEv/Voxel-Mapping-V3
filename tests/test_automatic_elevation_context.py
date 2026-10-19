import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf
from shapely.geometry import box,mapping

from voxel_mapper import automatic_elevation_context as context
from voxel_mapper import elevation_levels
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.reconstruction_evidence_queue import digest
from tests import test_elevation_levels as fixtures

UNIT=fixtures.UNIT


class AutomaticLevelTests(unittest.TestCase):
    def test_whole_view_markers_use_original_labels_leaders_and_unique_membership(self):
        document,views=fixtures.LevelTests().drawing()
        try:
            views[0]['display_bounds']=[0,0,500,400]
            before=document.tobytes(no_new_id=True)
            result=elevation_levels.extract(document[0],'a'*64,1,views,scope_mode='whole_view_containment')
            self.assertEqual(len(result['records']),2)
            self.assertTrue(all(r['status']=='unverified_native_level_reference_candidate' for r in result['records']))
            self.assertEqual(elevation_levels.relative_reference(result,views[0]['view_key_candidate'])['status'],'unverified_source_relative_shop_level')
            self.assertTrue(all(r['view_scope_recipe']=='whole_view_containment' for r in result['records']))
            self.assertEqual(document.tobytes(no_new_id=True),before)
            original=elevation_levels.extract(document[0],'a'*64,1,views)
            self.assertTrue(all(r['status']=='withheld_nonunique_level_label_line_or_view' for r in original['records']))
        finally:document.close()

    def test_crossing_annotations_duplicate_scopes_and_unscaled_competitors_are_not_dropped(self):
        document,views=fixtures.LevelTests().drawing()
        try:
            views[0]['display_bounds']=[0,0,500,400]
            duplicate=copy.deepcopy(views[0]);duplicate['nominal_metres_per_pdf_point_candidate']=None
            result=elevation_levels.extract(document[0],'a'*64,1,[*views,duplicate],scope_mode='whole_view_containment')
            self.assertTrue(all(len(r['view_key_candidates'])==2 for r in result['records']))
            self.assertTrue(all(r['status']=='withheld_nonunique_level_label_line_or_view' for r in result['records']))
            result=elevation_levels.extract(document[0],'a'*64,1,[duplicate],scope_mode='whole_view_containment')
            self.assertTrue(all(r['status']=='withheld_missing_nominal_view_scale' for r in result['records']))
            views[0]['display_bounds']=[285,0,500,400]  # Circle fits, source captions/leaders cross.
            result=elevation_levels.extract(document[0],'a'*64,1,views,scope_mode='whole_view_containment')
            self.assertTrue(all(not r['view_key_candidates'] for r in result['records']))
            with self.assertRaises(ValueError):elevation_levels.extract(document[0],'a'*64,1,views,scope_mode='nearest')
            with self.assertRaises(ValueError):elevation_levels.extract(document[0],'a'*64,1,[duplicate])
        finally:document.close()

    def inventory(self,soft_top=False):
        gray=np.full((180,140),255,dtype=np.uint8)
        gray[76:140,20:23]=50;gray[76:140,60:63]=50;gray[76:79,20:63]=50
        if soft_top:gray[75,20:63]=230
        found=scan(gray,representation='indexed')
        self.assertEqual(len(found['index']['consensus_families']),1)
        inv={'nominal_metres_per_pdf_point':.03,'residual_raster_scan':found}
        return inv,gray

    def test_every_threshold_witness_preserves_full_source_rows_below_the_level(self):
        inventory,gray=self.inventory();before=copy.deepcopy(inventory);pixels=gray.copy();charges=[]
        result=context.family_review(inventory,0,{'datum_y_display_points':100},[1,0,0,1,0,0],lambda:charges.append(1))
        self.assertEqual(result['status'],'all_threshold_witnesses_support_above_level_rows')
        self.assertEqual(result['observed_above_level_row_count_range'],[24,24])
        self.assertEqual(len(result['witnesses']),len(charges))
        for witness in result['witnesses']:
            self.assertEqual(witness['common_jamb_row_interval_pixels'],[76,140])
            self.assertEqual(witness['whole_rows_above_printed_level_interval_pixels'],[76,100])
            self.assertLess(witness['nominal_bottom_above_printed_level_m'],0)
        self.assertEqual(inventory,before);self.assertTrue(np.array_equal(gray,pixels))
        self.assertFalse(result['physical_opening_verified']);self.assertFalse(result['source_geometry_changed'])
        self.assertFalse(result['vertical_datum_verified'])

    def test_a_head_above_level_is_insufficient_without_whole_original_rows(self):
        inventory,_=self.inventory()
        result=context.family_review(inventory,0,{'datum_y_display_points':79},[1,0,0,1,0,0],lambda:None)
        self.assertEqual(result['status'],'insufficient_above_level_rows_in_all_witnesses')
        self.assertEqual(result['observed_above_level_row_count_range'],[3,3])
        self.assertGreater(result['observed_head_height_range_nominal_m'][0],0)
        result=context.family_review(inventory,0,{'datum_y_display_points':99.999},[1,0,0,1,0,0],lambda:None)
        self.assertEqual(result['observed_above_level_row_count_range'],[23,23])
        result=context.family_review(inventory,0,{'datum_y_display_points':50},[1,0,0,1,0,0],lambda:None)
        self.assertTrue(all(w['whole_rows_above_printed_level_interval_pixels'] is None for w in result['witnesses']))

    def test_real_threshold_disagreement_cannot_select_the_favourable_witness(self):
        inventory,_=self.inventory(soft_top=True)
        result=context.family_review(inventory,0,{'datum_y_display_points':99},[1,0,0,1,0,0],lambda:None)
        self.assertEqual(result['status'],'threshold_witnesses_disagree_about_above_level_rows')
        self.assertEqual(result['observed_above_level_row_count_range'],[23,24])
        self.assertEqual({w['threshold'] for w in result['witnesses']},{220,235})

    def test_invalid_frames_and_incomplete_consensus_are_rejected(self):
        inventory,_=self.inventory()
        for matrix in ([0,1,1,0,0,0],[1,0,0,-1,0,180],[1,0,0,float('nan'),0,0]):
            with self.assertRaises(ValueError):context.family_review(inventory,0,{'datum_y_display_points':100},matrix,lambda:None)
        inventory['residual_raster_scan']['index']['consensus_families'][0]['second_pair_indices']=[]
        with self.assertRaises(ValueError):context.family_review(inventory,0,{'datum_y_display_points':100},[1,0,0,1,0,0],lambda:None)

    def fixture(self,root):
        document,_=fixtures.LevelTests().drawing()
        page=document[0]
        page.draw_rect((40,100,75,250),width=2)
        page.draw_rect((110,120,145,250),width=2)
        pixels=page.get_pixmap(colorspace=pymupdf.csGRAY,alpha=False)
        gray=np.frombuffer(pixels.samples,np.uint8).reshape(pixels.height,pixels.width).copy()
        data=document.tobytes();document.close();sha=hashlib.sha256(data).hexdigest()
        (root/'files').mkdir();(root/'files'/(sha+'.pdf')).write_bytes(data)
        found=scan(gray,representation='indexed');self.assertGreaterEqual(len(found['index']['consensus_families']),2)
        view={'id':'auto-view','document_sha256':sha,'page':1,'printed_claim':{'view_kind':'elevation'},
              'geometry':mapping(box(0,0,500,400)),'nominal_metres_per_pdf_point':UNIT}
        inventory={'view_id':view['id'],'document_sha256':sha,'page':1,'printed_claim':view['printed_claim'],
            'nominal_metres_per_pdf_point':UNIT,'raster_coordinate_receipt':{'pixel_edge_to_pdf_native_matrix':[1,0,0,-1,0,400]},
            'residual_raster_scan':found,'residual_raster_hypotheses':[{'id':'family-'+str(i),
                'consensus_family_index':i,'status':'residual_jamb_head_context_candidate'} for i in range(len(found['index']['consensus_families']))]}
        source=[{'document_sha256':sha,'page':1,'views':[view]}]
        building={'status':'numbered_source_facade_candidates_only','width_links':[{'elevation_view_id':view['id'],
            'residual_family_id':h['id'],'projection_id':'plan-projection','source_width_link_id':'width-'+str(i)}
            for i,h in enumerate(inventory['residual_raster_hypotheses'])]}
        return SimpleNamespace(root=root),source,[inventory],building,sha

    def test_original_pdf_level_and_raster_review_connects_to_all_input_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);corpus,pages,inventories,building,sha=self.fixture(root)
            result=context.run(corpus,pages,inventories,building)
            self.assertEqual(result['status'],'source_relative_elevation_context_only')
            self.assertEqual(result['counts']['relative_view_references'],1)
            self.assertEqual(result['counts']['native_level_marker_records'],2)
            self.assertTrue(result['level_supported_width_links'])
            self.assertEqual(result['source_inventory_sha256']['auto-view'],digest(inventories[0]))
            self.assertEqual(result['source_building_links_sha256'],digest(building))
            self.assertFalse(result['position_alignment_verified']);self.assertFalse(result['physical_opening_verified'])
            self.assertEqual(hashlib.sha256((root/'files'/(sha+'.pdf')).read_bytes()).hexdigest(),sha)
            self.assertEqual(result['pages'][0]['source_scopes'][0]['view_key_candidate'],['automatic_view','auto-view'])

    def test_native_and_late_witness_budget_holds_discard_all_partial_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            corpus,pages,inventories,building,_=self.fixture(Path(temporary))
            result=context.run(corpus,pages,inventories,building,max_checks=1)
            self.assertEqual(result['status'],'elevation_context_budget_withheld')
            self.assertEqual(result['views'],[]);self.assertEqual(result['pages'],[])
            original=context.family_review;calls=[]
            def late_hold(*args,**kwargs):
                calls.append(1)
                if len(calls)==2:raise OverflowError('level_witness_work_budget')
                return original(*args,**kwargs)
            with patch.object(context,'family_review',side_effect=late_hold):
                result=context.run(corpus,pages,inventories,building)
            self.assertEqual(len(calls),2);self.assertEqual(result['status'],'elevation_context_budget_withheld')
            self.assertEqual(result['views'],[]);self.assertEqual(result['pages'],[]);self.assertEqual(result['level_supported_width_links'],[])

    def test_missing_scale_duplicate_views_and_withheld_scans_keep_original_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            corpus,pages,inventories,building,_=self.fixture(Path(temporary))
            pages[0]['views'].append(copy.deepcopy(pages[0]['views'][0]))
            result=context.run(corpus,pages,inventories,building)
            self.assertEqual(result['level_supported_width_links'],[])
            self.assertEqual(result['views'][0]['relative_reference']['status'],'withheld_nonunique_or_missing_shop_level')
            pages[0]['views'].pop();pages[0]['views'][0]['nominal_metres_per_pdf_point']=None
            result=context.run(corpus,pages,inventories,building)
            self.assertEqual(result['level_supported_width_links'],[])
            pages[0]['views'][0]['nominal_metres_per_pdf_point']=UNIT
            inventories[0]['residual_raster_scan']['index']=None
            result=context.run(corpus,pages,inventories,building)
            self.assertEqual(result['views'][0]['status'],'source_residual_scan_required')
            self.assertEqual(len(result['pages'][0]['level_review']['records']),2)
            with self.assertRaises(ValueError):context.run(corpus,pages,[inventories[0],inventories[0]],building)
            for value in (0,True,100001):
                with self.assertRaises(ValueError):context.run(corpus,pages,inventories,building,max_checks=value)


if __name__=='__main__':unittest.main()
