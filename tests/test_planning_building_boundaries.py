"""Original-fill 2D review, ambiguities, provenance and native boundary markers."""
from concurrent.futures import CancelledError
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import box,mapping,shape
from shapely.affinity import affine_transform

from voxel_mapper import planning_building_boundaries as buildings,planning_hatch_regions,planning_gap_boundaries
from voxel_mapper import planning_geometry_world as world
from tests.test_planning_geometry_world import inputs,request

SHA='a'*64


def fixture():
    paving={'version':planning_hatch_regions.VERSION,'document_sha256':SHA,'page':1,
        'coordinate_frame':'pdf_native_points_y_up','analysis_complete':True,'records':[]}
    claim={'id':'b'*64,'document_sha256':SHA,'page':1,'role':'building','text':'Shop',
        'label_geometry_pdf_native':mapping(box(12,12,15,15)),
        'glyph_screen':{'status':'raster_consistent_candidate'}}
    for i in (1,2):
        paving['records'].append({'id':str(i),'paint_kind':'solid','fill_opacity':1,
            'solid_colour_space':'/DeviceRGB','solid_colour_components':[1,1,1],
            'paint_operation_index':i,'geometry':mapping(box(10,10,20,20))})
    return paving,claim


class BuildingBoundaryTests(unittest.TestCase):
    def test_identical_paints_merge_without_duplicate_buildings(self):
        paving,claim=fixture();r=buildings.review(paving,source_claims=[claim])
        self.assertTrue(r['analysis_complete']);self.assertEqual(len(r['records']),1)
        row=r['records'][0];self.assertEqual(len(row['source_fills']),2)
        self.assertTrue(shape(row['geometry_pdf_native']).equals(box(10,10,20,20)))
        self.assertFalse(row['height_reconstruction_eligible']);self.assertFalse(r['model_weights_updated'])

    def test_competing_nested_fills_are_not_resolved_by_smallest_or_latest(self):
        paving,claim=fixture();paving['records'][1]['geometry']=mapping(box(9,9,21,21))
        r=buildings.review(paving,source_claims=[claim])
        self.assertEqual(r['records'],[]);self.assertEqual(r['label_decisions'][0]['status'],'ambiguous_source_fills')

    def test_translucent_coloured_and_legend_backplates_do_not_create_buildings(self):
        for change in ('opacity','colour','backplate'):
            with self.subTest(change=change):
                paving,claim=fixture()
                if change=='opacity':
                    for row in paving['records']:row['fill_opacity']=.5
                elif change=='colour':
                    for row in paving['records']:row['solid_colour_components']=[.8,.8,.8]
                else:paving['legend_backplates']=[{'paint_operation_index':1},{'paint_operation_index':2}]
                r=buildings.review(paving,source_claims=[claim]);self.assertEqual(r['records'],[])

    def test_white_page_background_does_not_become_a_building(self):
        paving,claim=fixture()
        for row in paving['records']:row['geometry']=mapping(box(0,0,100,100))
        r=buildings.review(paving,source_claims=[claim],native_page_bounds=[0,0,100,100])
        self.assertFalse(r['records'])

    def test_cross_page_hidden_or_incomplete_evidence_clears_results(self):
        for change in ('page','hidden','incomplete'):
            with self.subTest(change=change):
                paving,claim=fixture()
                if change=='page':claim['page']=2
                elif change=='hidden':claim['glyph_screen']['status']='hidden'
                else:paving['analysis_complete']=False
                r=buildings.review(paving,source_claims=[claim]);self.assertFalse(r['analysis_complete']);self.assertFalse(r['records'])

    def test_point_and_comparison_quotas_and_cancellation(self):
        paving,claim=fixture()
        for limits in ({'max_points':1},{'max_checks':1},{'max_fills':1},{'max_output_bytes':1}):
            r=buildings.review(paving,source_claims=[claim],options=limits);self.assertFalse(r['analysis_complete']);self.assertFalse(r['records'])
        with self.assertRaises(CancelledError):buildings.review(paving,source_claims=[claim],cancelled=lambda:True)

    def test_actual_original_pdf_label_proof_and_fill_recovery(self):
        with pymupdf.open() as d:
            page=d.new_page(width=600,height=400)
            for _ in range(2):page.draw_rect((40,40,160,160),fill=(1,1,1))
            page.insert_text((70,100),'Shop',fontsize=14)
            raw=d.tobytes();sha=hashlib.sha256(raw).hexdigest()
            with pymupdf.open(stream=raw,filetype='pdf') as original:
                p=original[0];fills=planning_hatch_regions.page_review(p,sha,1)
                r=buildings.page_review(p,fills)
                self.assertTrue(r['analysis_complete']);self.assertEqual(len(r['records']),1)
                self.assertEqual(len(r['records'][0]['source_fills']),2)
                self.assertEqual(r['records'][0]['labels'][0]['text'],'Shop')
                self.assertEqual(r['records'][0]['labels'][0]['glyph_screen']['status'],'raster_consistent_candidate')

    def test_incomplete_building_review_remains_a_pilot_blocker(self):
        from unittest.mock import patch
        from tests.test_planning_area_pilot import fixture
        from voxel_mapper import planning_area_pilot as pilot
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);config=fixture(root)
            with patch.object(buildings,'review',return_value={'analysis_complete':False,'records':[]}):
                report=pilot.run(config,lambda p:root/p,root/'review')
            self.assertIn('building_boundary_review_incomplete',report['pages'][0]['summary']['blockers'])

    def test_optional_pinned_buildings_export_boundaries_without_filling_interior(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);data=inputs();layout=data['layout'];scale=layout['shared_frame']['metres_per_pdf_point']
            native=lambda g:mapping(affine_transform(g,[1/scale,0,0,1/scale,0,0]))
            claim={'id':'c'*64,'document_sha256':layout['document_sha256'],'page':layout['page'],'role':'building','text':'Shop',
                'label_geometry_pdf_native':native(box(12,12,13,13)),'glyph_screen':{'status':'raster_consistent_candidate'}}
            data['paving']['records'].append({'id':'shop','paint_kind':'solid','solid_colour_space':'/DeviceRGB',
                'solid_colour_components':[1,1,1],'fill_opacity':1,'paint_operation_index':9,'geometry':native(box(10,10,20,20))})
            data['gaps']=planning_gap_boundaries.review(data['paving'],layout,source_claims=[claim])
            data['buildings']=buildings.review(data['paving'],layout,source_claims=[claim])
            config=request(root,data);world.read_inputs(config);sampled=world.rasterize(data)
            self.assertNotIn((15,15),sampled['markers']);self.assertIn((10,10),sampled['markers'])
            self.assertEqual(sampled['ground'][(10,10)],'light_blue_concrete')
            self.assertFalse(sampled['markers']&sampled['paving'])
            r=world.run(config,root/'world');self.assertEqual(r['building_marker_mode'],'2d_boundary_only')
            self.assertTrue(r['saved_geometry_validation']['native_block_states_verified'])
            self.assertEqual(r['reconstructed_buildings'],0)
            altered=copy.deepcopy(data['buildings']);altered['records'][0]['geometry_pdf_native']=native(box(30,30,40,40))
            config=request(root,{**data,'buildings':altered})
            with self.assertRaises(ValueError):world.read_inputs(config)


if __name__=='__main__':unittest.main()
