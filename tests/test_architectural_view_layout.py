import copy
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.architectural_view_layout import view_claim,review
from voxel_mapper.architectural_graph import build
from voxel_mapper.drawing_geometry import extract_page


class ViewLayoutTests(unittest.TestCase):
    def source(self):
        doc=pymupdf.open();page=doc.new_page(width=500,height=600)
        page.draw_rect((30,40,200,160));page.insert_text((30,200),"South Elevation 'as existing' | 1:50",fontsize=10)
        page.draw_rect((30,240,200,360));page.insert_text((30,400),"Ground Floor Plan 'as proposed' | 1:100",fontsize=10)
        page.insert_text((300,560),'Scale 1:200',fontsize=10)
        sha='f'*64;parents,_=extract_page(page,sha,1,min_line_length_points=.25,max_candidates=10000)
        return doc,page,parents,build(parents)

    def test_caption_grammar_does_not_accept_prose_or_bare_scales(self):
        self.assertEqual(view_claim('Key Plan (Ground Floor) | 1:500')['view_kind'],'key_plan')
        self.assertEqual(view_claim("Section A-A 'as existing' | 1:50")['view_kind'],'section')
        self.assertEqual(view_claim("Roof Plan 'as proposed'")['printed_state'],'proposed')
        for text in ('see south elevation','1:100','section A-B','plan','South Elevation | 1:99999'):self.assertIsNone(view_claim(text))

    def test_numbered_revit_captions_keep_numbers_and_do_not_inherit_state(self):
        for number,direction,expected in [(1,'S.East','southeast'),(2,'S.West','southwest'),
                                           (3,'N. West','northwest'),(4,'N. East','northeast')]:
            claim=view_claim(f'Elevation {number} to the {direction}')
            self.assertEqual(claim['view_number'],number);self.assertEqual(claim['direction'],expected)
            self.assertEqual(claim['printed_state'],'unspecified')
            self.assertIsNone(claim['printed_scale_denominator'])
            self.assertFalse(claim['numbered_reference_verified'])
        self.assertEqual(view_claim('00. Overall Ground Floor Plan')['plan_level_or_form'],'groundfloor')
        self.assertEqual(view_claim('Overall Roof Plan')['plan_level_or_form'],'roof')
        for text in ('see Elevation 1 to the S.East','Elevation 0 to the S.East',
                     'Elevation 1 to the N.Eest','Elevation 1 to the S.East | 1:99999'):
            self.assertIsNone(view_claim(text))

    def test_mixed_views_keep_inline_state_scale_and_whole_source_geometry(self):
        doc,page,parents,graph=self.source()
        try:
            before=copy.deepcopy(graph);report=review(page,'f'*64,1,graph)
            self.assertEqual({v['printed_claim']['view_kind'] for v in report['view_captions']},{'plan','elevation'})
            self.assertEqual({v['printed_claim']['printed_scale_denominator'] for v in report['view_captions']},{50,100})
            self.assertEqual([s['printed_denominator'] for s in report['page_scale_claims']],[200])
            self.assertTrue(all(v['scale_scope_status']=='page_view_claim_difference' for v in report['view_captions']))
            self.assertEqual(report['counts']['one_layout_window_candidate'],2)
            self.assertFalse(report['view_scope_verified']);self.assertFalse(report['scale_application_verified'])
            self.assertEqual(report['world_geometry_additions'],0);self.assertEqual(graph,before)
            self.assertEqual(page.rotation,0)
            page.set_rotation(90);rotated=review(page,'f'*64,1,graph)
            self.assertEqual([v['label_geometry'] for v in rotated['view_captions']],[v['label_geometry'] for v in report['view_captions']])
            self.assertEqual(page.rotation,90)
        finally:doc.close()

    def test_crossing_duplicate_and_hidden_captions_cannot_choose_a_view(self):
        doc,page,parents,graph=self.source()
        try:
            page.draw_line((250,80),(250,350))
            parents,_=extract_page(page,'f'*64,1,min_line_length_points=.25,max_candidates=10000);graph=build(parents)
            report=review(page,'f'*64,1,graph)
            self.assertGreater(report['counts'].get('ambiguous_or_crossing_windows',0),0)
            page.insert_text((30,200),"South Elevation 'as existing' | 1:50",fontsize=10)
            duplicate=review(page,'f'*64,1,graph)
            self.assertGreater(len(duplicate['view_captions']),2)
            self.assertGreater(duplicate['counts'].get('ambiguous_or_crossing_windows',0),0)
            with patch('voxel_mapper.architectural_view_layout.screen_architectural_span',return_value={'status':'withheld'}):
                hidden=review(page,'f'*64,1,graph)
                self.assertEqual(hidden['candidate_windows'],[]);self.assertEqual(hidden['component_membership'],[])
                self.assertEqual(len(hidden['view_captions']),3)
        finally:doc.close()

    def test_unscaled_title_is_retained_without_becoming_a_measured_view(self):
        doc,page,parents,graph=self.source()
        try:
            page.insert_text((300,520),"First Floor Plan 'as existing'",fontsize=10)
            report=review(page,'f'*64,1,graph)
            title=next(v for v in report['view_captions'] if v['printed_claim'].get('plan_level_or_form')=='firstfloor')
            self.assertEqual(title['layout_candidate_status'],'unscaled_caption_scope_withheld')
            self.assertNotIn(title['id'],[w['caption_id'] for w in report['candidate_windows']])
            self.assertIsNone(title['printed_claim']['printed_scale_denominator'])
        finally:doc.close()

    def test_adjacent_revit_scale_is_a_candidate_not_an_inline_measurement(self):
        doc=pymupdf.open();page=doc.new_page(width=500,height=600)
        page.draw_rect((30,40,200,160))
        page.insert_text((30,200),'Elevation 1 to the S.East',fontsize=10)
        page.insert_text((30,218),'1 : 100',fontsize=8)
        page.insert_text((300,550),'Scale 1:200',fontsize=10)
        parents,_=extract_page(page,'a'*64,1,min_line_length_points=.25,max_candidates=10000)
        graph=build(parents)
        try:
            row=review(page,'a'*64,1,graph)['view_captions'][0]
            self.assertEqual(row['adjacent_scale_status'],'one_adjacent_printed_scale_candidate')
            self.assertEqual(row['adjacent_scale_candidates'][0]['printed_denominator'],100)
            self.assertIsNone(row['printed_claim']['printed_scale_denominator'])
            self.assertEqual(row['printed_claim']['printed_state'],'unspecified')
            self.assertFalse(row['adjacent_scale_assignment_verified'])
            page.insert_text((30,218),'1 : 100',fontsize=8)
            row=review(page,'a'*64,1,graph)['view_captions'][0]
            self.assertEqual(row['adjacent_scale_status'],'ambiguous_adjacent_printed_scales')
        finally:doc.close()

    def test_budget_discards_all_assignments_and_wrong_source_graph_rejects(self):
        doc,page,parents,graph=self.source()
        try:
            report=review(page,'f'*64,1,graph,max_assignments=1)
            self.assertEqual(report['status'],'layout_assignment_budget_withheld')
            self.assertEqual(report['component_membership'],[]);self.assertEqual(report['subgraph_membership'],[])
            with self.assertRaises(ValueError):review(page,'f'*64,1,graph,max_assignments=True)
            with self.assertRaises(ValueError):review(page,'e'*64,1,graph)
            broken=copy.deepcopy(graph);broken['status']='graph_budget_withheld'
            with self.assertRaises(ValueError):review(page,'f'*64,1,broken)
        finally:doc.close()


if __name__=='__main__':unittest.main()
