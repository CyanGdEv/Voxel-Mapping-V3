import copy
from concurrent.futures import CancelledError
import hashlib
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box, mapping, shape

from voxel_mapper import planning_view_geometry as scoped
from voxel_mapper import drawing_view_candidates
from voxel_mapper.building_spec import digest


def fixture(*, hole=False, open_lines=False, rotation=0):
    document = pymupdf.open()
    page = document.new_page(width=600, height=500)
    if hole:
        drawing = page.new_shape()
        drawing.draw_rect((100, 100, 300, 300))
        drawing.draw_rect((150, 150, 250, 250))
        drawing.finish(fill=(.8, .8, .8), even_odd=True, color=None)
        drawing.commit()
    elif open_lines:
        for a, b in [((100, 100), (300, 100)), ((300, 100), (300, 300)),
                     ((300, 300), (100, 300))]:
            page.draw_line(a, b)
    else:
        # Four independent source strokes test actual exact linework recovery.
        for a, b in [((100, 100), (300, 100)), ((300, 100), (300, 300)),
                     ((300, 300), (100, 300)), ((100, 300), (100, 100))]:
            page.draw_line(a, b)
    page.insert_text((40, 450), 'Proposed Ground Floor Plan | 1:100', fontsize=10)
    page.set_rotation(rotation)
    sha = hashlib.sha256(document.tobytes()).hexdigest()
    factor = 100*.0254/72
    claim = {'view_kind': 'plan', 'printed_state': 'proposed',
             'plan_level_or_form': 'groundfloor', 'printed_scale_denominator': 100}
    caption = {'id': 'caption-1', 'text': 'Proposed Ground Floor Plan | 1:100',
        'printed_claim': claim, 'glyph_screen': {'status': 'raster_consistent_candidate'},
        'label_geometry': mapping(box(40, 45, 300, 65)),
        'reading_direction_pdf_native': [1, 0], 'adjacent_scale_candidates': []}
    view = {'id': 'view-1', 'caption_id': 'caption-1', 'caption_evidence': caption,
        'caption_text': caption['text'], 'printed_claim': claim,
        'coordinate_frame': scoped.FRAME, 'geometry': mapping(box(0, 0, 600, 500)),
        'nominal_scale_status': 'unique_view_scale_claim',
        'nominal_metres_per_pdf_point': factor,
        'native_to_nominal_local_affine': [factor, 0., 0., factor, 0., 0.]}
    pack = {'version': drawing_view_candidates.VERSION, 'document_sha256': sha, 'page': 1,
            'status': 'automatic_view_candidates_only', 'views': [view]}
    return document, page, sha, pack


class PlanningViewGeometryTests(unittest.TestCase):
    def test_source_strokes_recover_exact_closed_face_and_nominal_measurements(self):
        doc, page, sha, pack = fixture()
        try:
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['status'], 'scoped_source_geometry_candidates')
            self.assertEqual(report['summary']['closed_outlines'], 1)
            row = report['outlines'][0]
            self.assertEqual(row['source_candidate']['extraction_kind'], 'linework_boundaries')
            self.assertEqual(row['source_candidate']['recovery_options']['max_face_provenance'], 2048)
            self.assertEqual(row['measurements_pdf_points']['area'], 40000)
            self.assertEqual(row['measurements_pdf_points']['perimeter'], 800)
            self.assertAlmostEqual(row['measurements_nominal_metres']['area'], 40000*(100*.0254/72)**2)
            self.assertEqual(row['source_record_sha256'], digest(row['source_candidate']))
            self.assertEqual(row['source_view_sha256'], digest(pack['views'][0]))
            self.assertFalse(row['physical_identity_verified'])
            self.assertFalse(row['world_placement_eligible'])
            self.assertIsNone(row['geometric_accuracy'])
            self.assertEqual(report, scoped.page_candidates(page, sha, 1, pack))
        finally:
            doc.close()

    def test_native_polygon_preserves_holes_and_original_paint_references(self):
        doc, page, sha, pack = fixture(hole=True)
        try:
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 1)
            row = report['outlines'][0]
            self.assertEqual(row['measurements_pdf_points']['hole_count'], 1)
            self.assertEqual(row['measurements_pdf_points']['area'], 30000)
            self.assertEqual(len(shape(row['geometry_nominal_local']).interiors), 1)
            self.assertTrue(row['source_candidate']['paint_references'])
        finally:
            doc.close()

    def test_open_disconnected_strokes_are_never_closed_or_buffered(self):
        doc, page, sha, pack = fixture(open_lines=True)
        try:
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['summary']['complete_views'], 1)
            self.assertGreater(report['views'][0]['recovery']['counts']['dangles'], 0)
        finally:
            doc.close()

    def test_region_crossing_paint_is_withheld_without_clipping(self):
        doc, page, sha, pack = fixture(hole=True)
        try:
            view = pack['views'][0]
            view['geometry'] = mapping(box(0, 0, 200, 500))
            view['caption_evidence']['label_geometry'] = mapping(box(40, 45, 190, 65))
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['views'][0]['extraction']['rejections']['complete_primitive_crosses_region_boundary'], 1)
            self.assertEqual(report['summary']['complete_views'], 0)
            self.assertEqual(report['views'][0]['status'], 'regional_outlines_with_deferred_crossing_primitives')
        finally:
            doc.close()

    def test_ambiguous_scale_keeps_native_geometry_without_metres(self):
        doc, page, sha, pack = fixture()
        try:
            pack['views'][0]['nominal_scale_status'] = 'missing_ambiguous_or_conflicting_view_scale'
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 1)
            self.assertEqual(report['summary']['nominally_scaled_outlines'], 0)
            self.assertIsNone(report['outlines'][0]['geometry_nominal_local'])
            self.assertIsNone(report['outlines'][0]['measurements_nominal_metres'])
        finally:
            doc.close()

    def test_incorrect_scale_affine_or_unsupported_scope_stays_explicit(self):
        doc, page, sha, pack = fixture()
        try:
            mutations = [lambda v: v.update(nominal_metres_per_pdf_point=.5),
                lambda v: v.update(native_to_nominal_local_affine=[1, 0, 0, 1, 0, 0]),
                lambda v: v.update(geometry=mapping(box(-1, 0, 600, 500))),
                lambda v: v.update(geometry={'type': 'Polygon', 'coordinates': [[[0, 0], [1, 1]]]}),
                lambda v: v['caption_evidence'].update(reading_direction_pdf_native=[.7, .7]),
                lambda v: v.update(caption_id='different-caption')]
            for mutate in mutations:
                bad = copy.deepcopy(pack)
                mutate(bad['views'][0])
                report = scoped.page_candidates(page, sha, 1, bad)
                self.assertEqual(report['summary']['complete_views'], 0)
                self.assertEqual(report['views'][0]['status'], 'view_scope_withheld')
                self.assertTrue(report['views'][0]['reason'])
        finally:
            doc.close()

    def test_conflicting_per_view_scale_claims_cannot_produce_nominal_metres(self):
        doc, page, sha, pack = fixture()
        try:
            pack['views'][0]['caption_evidence']['adjacent_scale_candidates'] = [
                {'printed_denominator': 200, 'glyph_screen': {'status': 'raster_consistent_candidate'}}]
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['views'][0]['status'], 'view_scope_withheld')
            self.assertIn('scale', report['views'][0]['reason'])
        finally:
            doc.close()

    def test_source_binding_and_options_are_checked_before_extraction(self):
        doc, page, sha, pack = fixture()
        try:
            for field, value in [('document_sha256', 'a'*64), ('page', 2), ('version', 'old')]:
                bad = copy.deepcopy(pack)
                bad[field] = value
                with self.assertRaises(ValueError):
                    scoped.page_candidates(page, sha, 1, bad)
            for options in ({'max_views': True}, {'max_outlines': 501}, {'max_face_provenance': 2049}, {'unknown': 1}, {'max_output_bytes': 100}):
                with self.assertRaises(ValueError):
                    scoped.page_candidates(page, sha, 1, pack, options=options)
        finally:
            doc.close()

    def test_partial_extraction_never_recovers_or_exports_a_partial_closed_face(self):
        doc, page, sha, pack = fixture()
        try:
            with patch.object(scoped.linework_boundaries, 'recover_page', side_effect=AssertionError('Partial parents cannot close a face')):
                report = scoped.page_candidates(page, sha, 1, pack, options={'max_candidates_per_view': 2})
            self.assertEqual(report['views'][0]['status'], 'incomplete_regional_extraction')
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['summary']['complete_views'], 0)
        finally:
            doc.close()

    def test_boundary_recovery_failure_is_explicit_and_keeps_valid_native_polygons(self):
        doc, page, sha, pack = fixture(hole=True)
        try:
            with patch.object(scoped.linework_boundaries, 'recover_page', return_value=([], {'status': 'network_budget_withheld', 'reason': 'segment_budget'})):
                report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['views'][0]['status'], 'incomplete_regional_boundary_recovery')
            self.assertEqual(report['summary']['closed_outlines'], 1)
            self.assertEqual(report['summary']['complete_views'], 0)
        finally:
            doc.close()

    def test_cumulative_parents_and_view_limits_are_explicit(self):
        doc, page, sha, pack = fixture()
        try:
            other = copy.deepcopy(pack['views'][0])
            other['id'] = 'view-2'
            pack['views'].append(other)
            report = scoped.page_candidates(page, sha, 1, pack, options={'max_total_parents': 4})
            self.assertEqual(report['summary']['native_parents'], 4)
            self.assertEqual(report['views'][1]['status'], 'collection_budget_deferred')
            report = scoped.page_candidates(page, sha, 1, pack, options={'max_views': 1})
            self.assertEqual(report['views'][1]['status'], 'view_limit_deferred')
        finally:
            doc.close()

    def test_face_and_provenance_budget_deferrals_withhold_recovered_faces(self):
        doc, page, sha, pack = fixture()
        try:
            baseline = scoped.page_candidates(page, sha, 1, pack)
            face = baseline['outlines'][0]['source_candidate']
            for key in ('face_vertex_budget', 'provenance_budget_deferred', 'combined_page_budget_deferred'):
                with self.subTest(key=key), patch.object(scoped.linework_boundaries, 'recover_page',
                        return_value=([face], {'status': 'enclosed_faces_only', 'counts': {key: 1}})):
                    report = scoped.page_candidates(page, sha, 1, pack)
                self.assertEqual(report['summary']['closed_outlines'], 0)
                self.assertEqual(report['summary']['complete_views'], 0)
                self.assertEqual(report['views'][0]['status'], 'incomplete_regional_boundary_recovery')
                self.assertEqual(report['views'][0]['reason'], 'recovery_face_or_provenance_budget_deferred')
        finally:
            doc.close()

    def test_lower_face_provenance_limit_still_withholds_unrepresentable_recovered_face(self):
        doc, page, sha, pack = fixture()
        try:
            report = scoped.page_candidates(page, sha, 1, pack, options={'max_face_provenance': 3})
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['views'][0]['status'], 'incomplete_regional_boundary_recovery')
            self.assertEqual(report['views'][0]['recovery']['counts']['provenance_budget_deferred'], 1)
        finally:
            doc.close()

    def test_cancellation_and_page_rotation_are_preserved(self):
        doc, page, sha, pack = fixture(rotation=90)
        try:
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 1)
            self.assertEqual(page.rotation, 90)
            with self.assertRaises(CancelledError):
                scoped.page_candidates(page, sha, 1, pack, cancelled=lambda: True)
            self.assertEqual(page.rotation, 90)
        finally:
            doc.close()

    def test_output_limit_never_returns_complete_empty_scope_for_withheld_outlines(self):
        doc, page, sha, pack = fixture(hole=True)
        try:
            report = scoped.page_candidates(page, sha, 1, pack, options={'max_output_bytes': 16384})
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['views'][0]['status'], 'outline_output_budget_deferred')
            self.assertEqual(report['summary']['complete_views'], 0)
        finally:
            doc.close()

    def test_nondefault_pdf_user_unit_keeps_native_geometry_but_withholds_nominal_metres(self):
        doc, page, sha, pack = fixture()
        try:
            doc.xref_set_key(page.xref, 'UserUnit', '2')
            page = doc.reload_page(page)
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 1)
            self.assertEqual(report['summary']['nominally_scaled_outlines'], 0)
            self.assertEqual(report['views'][0]['status'], 'regional_native_geometry_with_scale_gap')
            self.assertTrue(report['views'][0]['nominal_scale_withheld'])
            self.assertIsNone(report['outlines'][0]['measurements_nominal_metres'])
        finally:
            doc.close()

    def test_image_occurrences_do_not_become_closed_outlines_and_empty_native_scope_keeps_raster_gap(self):
        doc, page, sha, pack = fixture(open_lines=True)
        try:
            image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2, 2), False)
            image.clear_with(180)
            page.insert_image(pymupdf.Rect(100, 100, 300, 300), pixmap=image)
            report = scoped.page_candidates(page, sha, 1, pack)
            self.assertEqual(report['summary']['closed_outlines'], 0)
            self.assertEqual(report['summary']['complete_views'], 0)
            self.assertEqual(report['views'][0]['status'], 'raster_geometry_unresolved')
            self.assertEqual(report['views'][0]['raster_source_placement_count'], 1)
            self.assertTrue(report['views'][0]['raster_geometry_unresolved'])
            self.assertTrue(report['views'][0]['raster_source_placement_ids'])
        finally:
            doc.close()


if __name__ == '__main__':
    unittest.main()
