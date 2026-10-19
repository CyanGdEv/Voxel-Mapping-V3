import copy
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import Polygon, box, mapping, shape

from voxel_mapper import automatic_building_scope as scope
from voxel_mapper.automatic_opening_links import plan_gaps
from voxel_mapper.reconstruction_evidence_queue import digest


class BuildingScopeTests(unittest.TestCase):
    def view(self):
        return {'id':'p', 'document_sha256':'a'*64, 'page':1,
            'geometry':mapping(box(0,0,400,300)),
            'printed_claim':{'view_kind':'plan','printed_state':'unspecified'},
            'nominal_metres_per_pdf_point':.03}

    def page(self, document):
        page = document.new_page(width=400,height=300)
        page.draw_rect((20,40,180,200))
        page.insert_text((70,110),'Shop',fontsize=10)
        page.draw_rect((230,40,380,200))
        page.insert_text((245,110),'Comms Building',fontsize=10)
        # This source gap overlaps only the named Shop enclosure.
        for rect in [(25,180,70,190),(100,180,170,190)]:
            page.draw_rect(rect,color=None,fill=(.5,.5,.5))
        return page

    def test_literal_source_labels_get_all_whole_enclosures_and_exact_overlap_links(self):
        with pymupdf.open() as document:
            page=self.page(document);view=self.view();gaps=plan_gaps(page,view)
            result=scope.review(page,view,gaps)
            self.assertEqual(result['status'],'named_source_enclosure_candidates_only')
            self.assertEqual({r['text'] for r in result['labels']},{'Shop','Comms Building'})
            self.assertTrue(all(r['glyph_screen']['status']=='raster_consistent_candidate' for r in result['labels']))
            shop=next(r for r in result['labels'] if r['text']=='Shop')
            self.assertEqual(len(shop['candidates']),1)
            native=shape(shop['candidates'][0]['geometry_pdf_native'])
            self.assertTrue(native.contains(shape(shop['geometry_pdf_native'])))
            self.assertEqual(len(result['gap_links']),1)
            self.assertEqual(result['gap_links'][0]['label_id'],shop['id'])
            self.assertEqual(result['gap_links'][0]['source_gap_id'],gaps['gaps'][0]['id'])
            self.assertFalse(result['gap_links'][0]['physical_building_assignment_verified'])
            self.assertIsNone(result['selected_physical_footprint_id'])
            self.assertTrue(all(not r['source_only_enclosure_review']['gap_effects'] for r in result['labels']))

    def test_a_label_center_does_not_certify_a_whole_label_or_repair_an_open_enclosure(self):
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=300)
            page.draw_rect((50,70,70,130));page.insert_text((45,100),'Shop',fontsize=10)
            # Isolate the whole-label topology gate from ink touching the wall.
            with patch.object(scope,'screen_architectural_span',return_value={'status':'raster_consistent_candidate'}):
                result=scope.review(page,self.view(),plan_gaps(page,self.view()))
            row=result['labels'][0]
            self.assertEqual(row['candidates'],[])
            self.assertTrue(row['whole_label_crossing_candidate_ids'])
            self.assertEqual(row['status'],'no_whole_label_source_enclosure')
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=300)
            for a,b in [((20,40),(180,40)),((180,40),(180,200)),((180,200),(20,200))]:page.draw_line(a,b)
            page.insert_text((70,110),'Shop',fontsize=10)
            result=scope.review(page,self.view(),plan_gaps(page,self.view()))
            self.assertEqual(result['labels'][0]['candidates'],[])

    def test_partial_kernel_and_label_budget_results_are_discarded(self):
        with pymupdf.open() as document:
            page=self.page(document);gaps=plan_gaps(page,self.view())
            with patch.object(scope.footprint_hypotheses,'propose',return_value={'status':'hypothesis_budget_withheld','reason':'work_budget'}):
                result=scope.review(page,self.view(),gaps)
            self.assertEqual(result['status'],'building_scope_budget_withheld')
            self.assertEqual(result['labels'],[]);self.assertEqual(result['gap_links'],[])
            original=scope.footprint_hypotheses.propose; calls=[]
            def late_hold(*args,**kwargs):
                calls.append(1)
                return original(*args,**kwargs) if len(calls)==1 else {'status':'hypothesis_budget_withheld','reason':'work_budget'}
            with patch.object(scope.footprint_hypotheses,'propose',side_effect=late_hold):
                result=scope.review(page,self.view(),gaps)
            self.assertEqual(len(calls),2);self.assertEqual(result['labels'],[]);self.assertEqual(result['gap_links'],[])
            with patch.object(scope,'MAX_LABELS',1):
                result=scope.review(page,self.view(),gaps)
            self.assertEqual(result['reason'],'named_label_budget');self.assertEqual(result['labels'],[])
            self.assertEqual(scope.review(page,self.view(),gaps,max_checks=1)['status'],'building_scope_budget_withheld')

    def test_missing_source_inputs_and_unreadable_labels_stay_unassigned(self):
        with pymupdf.open() as document:
            page=self.page(document);view=self.view();gaps=plan_gaps(page,view)
            with patch.object(scope,'screen_architectural_span',return_value={'status':'withheld'}):
                result=scope.review(page,view,gaps)
            self.assertTrue(all(r['status']=='label_glyph_screen_withheld' for r in result['labels']))
            self.assertEqual(result['gap_links'],[])
            self.assertEqual(scope.review(None,view,gaps)['status'],'original_source_page_required')
            self.assertEqual(scope.review(page,view,{'status':'plan_gap_budget_withheld'})['status'],'source_plan_gaps_required')
            roof=copy.deepcopy(view);roof['printed_claim']['plan_level_or_form']='roof'
            self.assertEqual(scope.review(page,roof,gaps)['status'],'not_a_floor_plan')
        self.assertEqual(scope.references(None,self.view())['status'],'original_source_page_required')

    def test_elevation_target_keys_require_original_visible_sheet_identity(self):
        with pymupdf.open() as document:
            page=document.new_page(width=400,height=300);page.insert_text((200,20),'1234-26',fontsize=10)
            view=self.view();view['printed_claim']={'view_kind':'elevation','view_number':3,'printed_state':'unspecified'}
            result=scope.references(page,view)
            self.assertEqual(result['view_key_candidate'],['1234',26,3]);self.assertIsNone(result['plan_references'])
            self.assertEqual(result['sheet_identity']['trace_index'],0)
            with patch.object(scope,'screen_architectural_span',return_value={'status':'withheld'}):
                self.assertIsNone(scope.references(page,view)['view_key_candidate'])
            view['printed_claim'].pop('view_number')
            self.assertIsNone(scope.references(page,view)['view_key_candidate'])

    def evidence(self):
        polygon=Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(10,10),(20,10),(20,20),(10,20)]])
        reference={'status':'unverified_native_view_reference_candidate','target_view_key_candidate':['1234',26,1],
            'circle_bbox_page_points':[108,48,112,52],'corner_fill_bbox_page_points':[104,49,106,51]}
        plan={'view_id':'p','nominal_metres_per_pdf_point':.1,
            'building_scope_review':{'status':'named_source_enclosure_candidates_only','labels':[{'id':'label','candidates':[
                {'id':'enclosure','geometry_pdf_native':mapping(polygon)}]}],
                'gap_links':[{'label_id':'label','enclosure_id':'enclosure','source_gap_id':'gap'}]},
            'drawing_reference_review':{'view_key_candidate':None,'plan_references':{'references':[reference]},
                'whole_view_reference_sha256':[digest(reference)]},
            'plan_gap_review':{'unrotated_mupdf_to_pdf_native_matrix':[1,0,0,1,0,0],'gaps':[
                {'id':'gap','gap_endpoints_pdf_native':[[99,40],[99,60]]}]}}
        elevation={'view_id':'e','building_scope_review':{'status':'not_a_floor_plan'},
            'drawing_reference_review':{'view_key_candidate':['1234',26,1],'plan_references':None}}
        widths={'status':'nominal_width_links_only','matches':[{'id':'w','plan_view_id':'p','source_gap_id':'gap',
            'elevation_view_id':'e','residual_family_id':'family'}]}
        return [plan,elevation],widths

    def test_numbered_marker_scope_projects_gaps_without_inventing_elevation_origins(self):
        views,widths=self.evidence();before=copy.deepcopy(views);result=scope.link(views,widths)
        self.assertEqual(views,before)
        self.assertEqual(len(result['projected_gaps']),1);self.assertEqual(len(result['width_links']),1)
        projection=result['projected_gaps'][0]
        self.assertAlmostEqual(projection['maximum_gap_plane_offset_nominal_m'],.1)
        self.assertEqual(projection['nominal_plan_position_interval_m'],[4.,6.])
        self.assertFalse(result['position_alignment_verified'])
        self.assertEqual(result['width_links'][0]['source_width_link_sha256'],digest(widths['matches'][0]))
        self.assertEqual(result['source_inventory_sha256'],{v['view_id']:digest(v) for v in views})
        self.assertEqual(len(shape(views[0]['building_scope_review']['labels'][0]['candidates'][0]['geometry_pdf_native']).interiors),1)

    def test_wrong_reference_key_and_nonparallel_or_distant_gaps_do_not_link(self):
        views,widths=self.evidence();views[1]['drawing_reference_review']['view_key_candidate'][-1]=2
        result=scope.link(views,widths)
        self.assertEqual(result['width_links'],[]);self.assertEqual(len(result['projected_gaps']),1)
        views,widths=self.evidence();views[0]['drawing_reference_review']['whole_view_reference_sha256']=[]
        self.assertEqual(scope.link(views,widths)['frames'],[])
        for points in ([[90,40],[90,60]],[[90,50],[100,50]]):
            views,widths=self.evidence();views[0]['plan_gap_review']['gaps'][0]['gap_endpoints_pdf_native']=points
            self.assertEqual(scope.link(views,widths)['projected_gaps'],[])

    def test_inside_markers_and_late_work_exhaustion_do_not_leave_partial_links(self):
        views,widths=self.evidence();ref=views[0]['drawing_reference_review']['plan_references']['references'][0]
        ref['circle_bbox_page_points']=[48,48,52,52];ref['corner_fill_bbox_page_points']=[44,49,46,51]
        views[0]['drawing_reference_review']['whole_view_reference_sha256']=[digest(ref)]
        result=scope.link(views,widths)
        self.assertEqual(result['frames'][0]['frame_review']['status'],'withheld_marker_inside_enclosure')
        self.assertEqual(result['projected_gaps'],[])
        views,widths=self.evidence();result=scope.link(views,widths,max_checks=7)
        self.assertEqual(result['status'],'building_facade_budget_withheld')
        self.assertEqual(result['frames'],[]);self.assertEqual(result['projected_gaps'],[]);self.assertEqual(result['width_links'],[])

    def test_repeated_target_keys_remain_multiple_alternatives(self):
        views,widths=self.evidence();other=copy.deepcopy(views[1]);other['view_id']='e2';views.append(other)
        row=copy.deepcopy(widths['matches'][0]);row.update(id='w2',elevation_view_id='e2',residual_family_id='f2');widths['matches'].append(row)
        result=scope.link(views,widths)
        self.assertEqual(len(result['width_links']),2)
        self.assertEqual({r['target_view_multiplicity'] for r in result['width_links']},{2})
        self.assertTrue(all(not r['physical_correspondence_verified'] for r in result['width_links']))
        with self.assertRaises(ValueError):scope.link([views[0],views[0]],widths)
        self.assertEqual(scope.link(views,{'status':'opening_link_budget_withheld'})['status'],'source_width_links_required')


if __name__=='__main__':unittest.main()
