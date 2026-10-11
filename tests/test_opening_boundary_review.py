import copy
import unittest
from shapely.geometry import Polygon,box,mapping
from voxel_mapper.opening_boundary_review import compare


def candidate(g=None,key='outline',error=0):
    return {'id':key,'document_sha256':'a'*64,'page':1,'coordinate_frame':'pdf_native_points_y_up',
            'geometry':mapping(g if g is not None else box(10,10,50,60)),
            'paint_references':[{'stroke_style':{'dashes_pdf':'[] 0'}}],
            'curve_approximation':{'chord_error_bound_pdf_points':error},'extraction_kind':'drawing_components'}


def review(records,**kwargs):
    return compare([{'id':'w3.01','points_pixels':[[10,10],[50,10],[50,60],[10,60]]}],
                   records,[1,0,0,1,0,0],[0,0,100,100],2,**kwargs)


class OpeningBoundaryTests(unittest.TestCase):
    def test_unique_complete_outline_is_only_a_review_candidate(self):
        r=review([candidate()]);row=r['rows'][0]
        self.assertEqual(row['status'],'unique_review_trace_refinement_candidate')
        self.assertEqual(row['refinement_candidate_id'],'outline')
        self.assertFalse(row['physical_aperture_verified']);self.assertFalse(r['geometry_export_authorized'])

    def test_panes_retained_but_do_not_replace_full_opening(self):
        row=review([candidate(box(10,10,30,60),'pane'),candidate()])['rows'][0]
        self.assertEqual(len(row['candidates']),2)
        self.assertEqual(row['refinement_candidate_id'],'outline')
        self.assertFalse(next(c for c in row['candidates'] if c['source_candidate_id']=='pane')['within_reviewed_sampling_bound'])

    def test_competing_whole_outlines_never_select_largest_or_closest(self):
        row=review([candidate(),candidate(box(9,9,51,61),'other')])['rows'][0]
        self.assertEqual(row['status'],'competing_review_trace_refinements');self.assertIsNone(row['refinement_candidate_id'])

    def test_frame_hole_is_preserved_and_disqualifies_refinement(self):
        ring=Polygon(box(10,10,50,60).exterior.coords,[box(12,12,48,58).exterior.coords])
        c=review([candidate(ring)])['rows'][0]['candidates'][0]
        self.assertEqual(c['source_holes'],1);self.assertFalse(c['within_reviewed_sampling_bound'])
        self.assertEqual(len(c['geometry_pixels']['coordinates']),2)

    def test_curve_error_is_added_to_sampling_distance(self):
        row=review([candidate(box(11,10,50,60),error=1.1)])['rows'][0]
        self.assertEqual(row['status'],'no_complete_outline_within_trace_bound')
        self.assertAlmostEqual(row['candidates'][0]['boundary_plus_curve_bound_pixels'],2.1)

    def test_native_closed_curve_retains_bounded_approximation(self):
        row=review([candidate(error=.1)])['rows'][0]
        self.assertEqual(row['status'],'unique_review_trace_refinement_candidate')
        self.assertEqual(row['candidates'][0]['curve_error_bound_pixels'],.1)

    def test_dashed_unknown_truncated_paint_not_authorized(self):
        for patch in [{'paint_reference_truncated':True},{'paint_references':[]},
                      {'paint_references':[{'stroke_style':{'dashes_pdf':'[1 2] 0'}}]}]:
            c=candidate();c.update(patch)
            self.assertEqual(review([c])['rows'][0]['status'],'no_complete_outline_within_trace_bound')

    def test_late_budget_exhaustion_discards_earlier_qualifying_outline(self):
        r=review([candidate(),candidate(key='second')],max_checks=3)
        self.assertEqual(r['status'],'boundary_comparison_budget_withheld');self.assertEqual(r['rows'],[])

    def test_open_line_cannot_become_closed_outline(self):
        from shapely.geometry import LineString
        self.assertEqual(review([candidate(LineString([(10,10),(50,10),(50,60)]))])['rows'][0]['candidates'],[])

    def test_source_order_and_input_coordinates_remain_unchanged(self):
        rows=[candidate(),candidate(box(20,10,50,60),'pane')];before=copy.deepcopy(rows)
        self.assertEqual(review(rows),review(list(reversed(rows))))
        self.assertEqual(rows,before)

    def test_wrong_page_or_nonfinite_curve_bound_rejected(self):
        other=candidate(key='other');other['page']=2
        with self.assertRaisesRegex(ValueError,'One native'):review([candidate(),other])
        with self.assertRaisesRegex(ValueError,'curve bound'):review([candidate(error=float('nan'))])

    def test_whole_polygon_crossing_scope_is_not_cropped(self):
        self.assertEqual(review([candidate(box(-1,10,50,60))])['rows'][0]['candidates'],[])

    def test_proximity_buffer_does_not_close_missing_head(self):
        from shapely.geometry import LineString
        line=candidate(LineString([(10,10),(10,60),(50,60),(50,10)]))
        row=review([line])['rows'][0]
        self.assertIsNone(row['refinement_candidate_id'])
        support=row['trace_proximity_review']
        self.assertGreater(support['near_source_fraction'],.7)
        self.assertLess(support['near_source_fraction'],1)
        self.assertFalse(shape_is_empty(support['unsupported_reviewed_trace']))

    def test_small_endpoint_gap_is_retained_without_source_repair(self):
        from shapely.geometry import LineString
        rows=[candidate(LineString([(10,10),(50,10)]),'head'),
              candidate(LineString([(50.1,10),(50.1,60)]),'jamb')]
        before=copy.deepcopy(rows);row=review(rows)['rows'][0]
        self.assertAlmostEqual(row['endpoint_gap_candidates'][0]['distance_pixels'],.1)
        self.assertFalse(row['endpoint_gap_candidates'][0]['source_gap_repaired'])
        self.assertIsNone(row['refinement_candidate_id']);self.assertEqual(rows,before)


def shape_is_empty(geometry):
    from shapely.geometry import shape
    return shape(geometry).is_empty
