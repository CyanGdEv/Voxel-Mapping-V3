import copy
from concurrent.futures import CancelledError
import tempfile
from pathlib import Path
import unittest

import pymupdf
from shapely.geometry import Polygon,box,mapping,shape

from voxel_mapper import planning_gap_boundaries as gaps,planning_hatch_regions


def paving(geometries):
    return {'version':planning_hatch_regions.VERSION,'document_sha256':'a'*64,'page':1,
        'coordinate_frame':'pdf_native_points_y_up','analysis_complete':True,
        'records':[{'geometry':mapping(g),'legend_claim':{'printed_state':'existing'},'paint_kind':'solid'} for g in geometries],
        'summary':{'source_hatch_regions':0,'legend_associated_paving_regions':len(geometries),'curved_paving_regions':0}}


def island():return Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(20,20),(40,20),(40,40),(20,40)]])


class GapBoundaryTests(unittest.TestCase):
    def test_persisted_user_default_and_island_interior(self):
        result=gaps.review(paving([island()]))
        self.assertEqual(result['summary']['assumed_rock_boundaries'],1)
        r=result['records'][0]
        self.assertEqual(r['material'],'rock')
        self.assertTrue(r['is_boundary']);self.assertTrue(r['assumed'])
        self.assertFalse(r['interior_filled_with_rock'])
        self.assertIsNone(r['height_m']);self.assertIsNone(r['width_m'])
        self.assertEqual(shape(r['gap_geometry_pdf_native']).area,400)
        self.assertEqual(shape(r['boundary_geometry_pdf_native']).length,80)
        self.assertFalse(r['training_label_eligible'])
        self.assertEqual(result['policy']['policy_origin'],'user_instruction')

    def test_open_corridor_is_not_closed_or_bridged(self):
        result=gaps.review(paving([box(0,0,40,100),box(60,0,100,100)]))
        self.assertEqual(result['records'],[])

    def test_building_claim_overrides_default_where_it_occupies_gap(self):
        layout={'version':'planning-area-layout-v1','document_sha256':'a'*64,'page':1,'analysis_complete':True,
            'candidates':[{'id':'building','role':'building','geometry_pdf_native':mapping(box(20,20,40,40))}]}
        result=gaps.review(paving([island()]),layout);r=result['records'][0]
        self.assertFalse(r['assumed']);self.assertEqual(r['boundary_kind'],'building')
        self.assertEqual(r['source_building_claim_ids'],['building']);self.assertIsNone(r['material'])

    def test_small_building_inside_planted_island_does_not_reclassify_its_entire_edge(self):
        layout={'version':'planning-area-layout-v1','document_sha256':'a'*64,'page':1,'analysis_complete':True,
            'candidates':[{'id':'building','role':'building','geometry_pdf_native':mapping(box(25,25,30,30))}]}
        self.assertEqual(gaps.review(paving([island()]),layout)['records'][0]['material'],'rock')

    def test_explicit_opening_overrides_rock_and_boundary(self):
        source=paving([island()]);identifier=gaps.review(source)['records'][0]['id']
        result=gaps.review(source,overrides={identifier:{'kind':'opening','evidence':'Plan explicitly marks an entrance'}})
        r=result['records'][0];self.assertFalse(r['is_boundary']);self.assertFalse(r['assumed'])
        self.assertEqual(r['navigation_policy'],'source_opening_claim')
        self.assertIsNone(r['material'])

    def test_explicit_fence_overrides_default_without_inventing_dimensions(self):
        source=paving([island()]);identifier=gaps.review(source)['records'][0]['id']
        r=gaps.review(source,overrides={identifier:{'kind':'fence','evidence':'Source fence annotation'}})['records'][0]
        self.assertEqual(r['boundary_kind'],'fence');self.assertIsNone(r['height_m'])
        self.assertEqual(r['classification_basis'],'explicit_override')

    def test_stale_override_cannot_be_applied_to_other_gap(self):
        result=gaps.review(paving([island()]),overrides={'missing':{'kind':'wall','evidence':'Wrong source'}})
        self.assertFalse(result['analysis_complete']);self.assertEqual(result['records'],[])

    def test_budgets_clear_whole_review(self):
        two=Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(10,10),(20,10),(20,20),(10,20)],[(40,40),(60,40),(60,60),(40,60)]])
        for options in ({'max_gaps':1},{'max_input_points':1},{'max_gap_points':1},{'max_output_bytes':1}):
            with self.subTest(options=options):
                result=gaps.review(paving([two]),options=options)
                self.assertFalse(result['analysis_complete']);self.assertEqual(result['records'],[])
                self.assertNotIn('summary',result)

        limited=gaps.review(paving([island(),box(100,0,150,100)]),options={'max_union_work':1})
        self.assertFalse(limited['analysis_complete']);self.assertEqual(limited['records'],[])

    def test_source_validation_and_cancellation(self):
        source=paving([island()]);bad=copy.deepcopy(source);bad['analysis_complete']=False
        self.assertFalse(gaps.review(bad)['analysis_complete'])
        with self.assertRaises(CancelledError):gaps.review(source,cancelled=lambda:True)
        with self.assertRaises(ValueError):gaps.review(source,options={'max_gaps':True})
        with self.assertRaises(ValueError):gaps.review(source,overrides={'id':{'kind':'lava','evidence':'No source'}})
        bad=copy.deepcopy(source);bad['document_sha256']='z'*64
        with self.assertRaises(ValueError):gaps.review(bad)

    def test_union_preserves_holes_and_stable_ids(self):
        first=paving([island(),box(100,0,150,100)]);second=paving([box(100,0,150,100),island()])
        a=gaps.review(first);b=gaps.review(second)
        self.assertEqual(a['records'],b['records']);self.assertEqual(first['records'][0]['geometry'],mapping(island()))

    def test_visible_building_label_and_matching_white_fill_override_rocks(self):
        source=paving([island()])
        source['records'].append({'geometry':mapping(box(20,20,40,40)),'legend_claim':None,
            'paint_kind':'solid','fill_opacity':1,'solid_colour_space':'/DeviceRGB',
            'solid_colour_components':[1.,1.,1.],'paint_operation_index':12})
        claim={'id':'shop-label','document_sha256':'a'*64,'page':1,'role':'building',
            'label_geometry_pdf_native':mapping(box(25,25,35,30)),
            'glyph_screen':{'status':'raster_consistent_candidate'}}
        result=gaps.review(source,source_claims=[claim])
        r=result['records'][0]
        self.assertEqual(r['boundary_kind'],'building');self.assertFalse(r['assumed'])
        self.assertTrue(any('shop-label' in identifier for identifier in r['source_building_claim_ids']))

    def test_partial_building_edge_only_suppresses_rock_on_that_edge(self):
        source=paving([island()])
        source['records'].append({'geometry':mapping(box(20,20,25,40)),'legend_claim':None,
            'paint_kind':'solid','fill_opacity':1,'solid_colour_space':'/DeviceRGB',
            'solid_colour_components':[1.,1.,1.],'paint_operation_index':12})
        claim={'id':'partial-shop','document_sha256':'a'*64,'page':1,'role':'building',
            'label_geometry_pdf_native':mapping(box(21,25,24,30)),
            'glyph_screen':{'status':'raster_consistent_candidate'}}
        result=gaps.review(source,source_claims=[claim]);r=result['records'][0]
        self.assertTrue(r['assumed']);self.assertEqual(r['material'],'rock')
        self.assertTrue(r['source_boundary_overrides'])
        self.assertLess(shape(r['assumed_rock_geometry_pdf_native']).length,80)
        self.assertGreater(shape(r['assumed_rock_geometry_pdf_native']).length,0)
        self.assertEqual(shape(r['boundary_geometry_pdf_native']).length,80)
        limited=gaps.review(source,source_claims=[claim],options={'max_segment_checks':1})
        self.assertFalse(limited['analysis_complete']);self.assertEqual(limited['records'],[])

    def test_native_building_label_screen_and_page_binding(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=300);page.insert_text((50,50),'Shop',fontsize=12)
            source=paving([island()]);claims=gaps.page_building_claims(page,source)
            self.assertEqual(len(claims),1)
            self.assertEqual(claims[0]['text'],'Shop')
            self.assertEqual(claims[0]['glyph_screen']['status'],'raster_consistent_candidate')
            source['page']=2
            with self.assertRaises(ValueError):gaps.page_building_claims(page,source)

    def test_legend_display_cutout_is_not_a_rock_gap(self):
        source=paving([box(0,0,100,100)])
        source['records'][0]['review_geometry']=mapping(island())
        self.assertEqual(gaps.review(source)['records'],[])

    def test_overlay_adds_boundary_stroke_without_rock_fill(self):
        with pymupdf.open() as doc,tempfile.TemporaryDirectory() as directory:
            page=doc.new_page(width=300,height=300)
            from voxel_mapper.planning_area_pilot import _preview
            root=Path(directory);preview=_preview(page,root/'page.png',600);source=paving([island()])
            overlay=gaps.write_overlay(gaps.review(source),source,preview,root/'gaps.svg')
            text=(root/'gaps.svg').read_text()
            self.assertIn('Assumed rock boundary',text);self.assertIn('fill="none" stroke="#ad5b16"',text)
            self.assertEqual(overlay['assumed_rock_boundaries'],1)

    def test_area_pilot_records_policy_and_keeps_world_inputs_separate(self):
        from tests.test_existing_paving_fills import solid_source
        from voxel_mapper.planning_area_pilot import _page
        with pymupdf.open() as doc:
            page=solid_source(doc);result=_page(page,'a'*64,1,'site-plan')
            review=result['gap_boundary_review']
            self.assertEqual(review['summary']['assumed_rock_boundaries'],1)
            self.assertEqual(review['world_geometry_additions'],0)
            self.assertIn('gap_boundary_material_uses_user_rock_assumption',result['summary']['blockers'])


if __name__=='__main__':unittest.main()
