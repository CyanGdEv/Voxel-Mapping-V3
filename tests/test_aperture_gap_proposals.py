import copy
import unittest

import pymupdf
from shapely.geometry import LineString,Polygon,mapping,shape

from voxel_mapper.aperture_gap_proposals import propose
from voxel_mapper.drawing_geometry import extract_page,validated_options,contract
from voxel_mapper.drawing_page_tools import native_to_render_pixels,native_inverse


class GapProposalTests(unittest.TestCase):
    def records(self):
        lines=[[(10,10),(30,10),(30,30)],[(30,30),(10,30),(10,10.5)]]
        return [{'id':str(i),'document_sha256':'a'*64,'page':1,
                 'coordinate_frame':'pdf_native_points_y_up','geometry':mapping(LineString(line)),
                 'paint_references':[{'stroke_style':{'dashes_pdf':'[] 0'}}]}
                for i,line in enumerate(lines)]

    def propose(self,records=None,**options):
        return propose({'points_pixels':[(10,10),(30,10),(30,30),(10,30)]},
                       self.records() if records is None else records,[1,0,0,1,0,0],[0,0,100,100],**options)

    def test_one_connector_closes_original_outline_without_moving_endpoints(self):
        records=self.records();original=copy.deepcopy(records);review=self.propose(records)
        self.assertEqual(records,original)
        self.assertEqual(len(review['proposals']),1)
        proposal=review['proposals'][0]
        self.assertEqual(shape(proposal['geometry_pixels']).area,400)
        self.assertEqual(len(proposal['hypothesis_interval_proofs']),1)
        self.assertEqual(len(proposal['source_interval_proofs']),4)
        self.assertFalse(proposal['physical_aperture_verified'])
        self.assertFalse(proposal['mesh_update_authorized'])
        self.assertEqual(review['world_geometry_additions'],0)

    def test_gap_limit_does_not_snap_or_close_a_larger_gap(self):
        self.assertFalse(self.propose(gap_limit=.25)['proposals'])

    def test_multiple_required_connectors_are_not_combined(self):
        records=self.records()
        records[0]['geometry']=mapping(LineString([(10,10),(30,10),(30,29.5)]))
        records[1]['geometry']=mapping(LineString([(30.5,30),(10,30),(10,10.5)]))
        review=self.propose(records)
        self.assertGreaterEqual(len(review['gaps']),2)
        self.assertFalse(review['proposals'])

    def test_duplicate_endpoint_provenance_retains_same_geometry_variants(self):
        records=self.records();extra=copy.deepcopy(records[1]);extra['id']='extra';records.append(extra)
        review=self.propose(records)
        self.assertEqual(len(review['proposals']),2)
        self.assertEqual(len({p['geometry_identity'] for p in review['proposals']}),1)
        self.assertEqual(len({p['id'] for p in review['proposals']}),2)

    def test_original_closed_candidate_and_source_order_are_deterministic(self):
        records=self.records();records[1]['geometry']=mapping(LineString([(30,30),(10,30),(10,10)]))
        a=self.propose(records);b=self.propose(list(reversed(records)))
        self.assertEqual(a,b)
        self.assertEqual(a['proposals'][0]['status'],'original_closed_outline_candidate')
        self.assertFalse(a['proposals'][0]['hypothesis_interval_proofs'])

    def test_dashed_curved_and_mixed_frames_do_not_gain_geometry(self):
        for changes in ({'curve_approximation':{'cubic_segments':1}},
                        {'paint_references':[{'stroke_style':{'dashes_pdf':'[2 2] 0'}}]}):
            records=self.records();records[0].update(changes)
            self.assertFalse(self.propose(records)['proposals'])
        records=self.records();records[0]['page']=2
        with self.assertRaises(ValueError):self.propose(records)

    def test_budget_failure_discards_partial_results(self):
        result=self.propose(max_checks=5)
        self.assertEqual(result['status'],'gap_proposal_budget_withheld')
        self.assertEqual(result['proposals'],[]);self.assertEqual(result['gaps'],[])
        with self.assertRaises(ValueError):self.propose(max_checks=True)

    def test_filled_source_hole_is_not_promoted_to_aperture(self):
        records=self.records()
        records.append({**copy.deepcopy(records[0]),'id':'protected',
                        'geometry':mapping(Polygon([(5,5),(35,5),(35,35),(5,35)],
                                           [[(15,15),(25,15),(25,25),(15,25)]]))})
        review=self.propose(records)
        self.assertFalse(review['proposals'])

    def test_receipt_replay_and_tampering_are_checked(self):
        import json
        from tests.test_local_wing_review import WingReviewTests
        from voxel_mapper.aperture_gap_proposals import run
        fixture=WingReviewTests();fixture.setUp()
        try:
            recipe=fixture.root/'seed.json';recipe.write_text(json.dumps(fixture.recipe));output=fixture.root/'gaps'
            first=run(recipe,fixture.paths['elevation'],output)
            self.assertFalse(first['reused']);self.assertTrue(run(recipe,fixture.paths['elevation'],output)['reused'])
            from pathlib import Path
            Path(first['proposal_path']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'receipt changed'):run(recipe,fixture.paths['elevation'],output)
            fixture.paths['elevation'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):run(recipe,fixture.paths['elevation'],fixture.root/'new')
        finally:fixture.tearDown()

    def test_optional_stroke_isolation_preserves_open_subpath_reference(self):
        doc=pymupdf.open();page=doc.new_page(width=400,height=600)
        page.draw_line((10,10),(20,20))
        doc.update_stream(page.get_contents()[0],b'100 100 50 50 re 200 200 m 250 200 l S')
        try:
            self.assertEqual(extract_page(page,'a'*64,1)[0],[])
            rows,report=extract_page(page,'a'*64,1,isolate_open_stroked_subpaths=True)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['paint_references'][0]['subpath'],1)
            self.assertEqual(list(shape(rows[0]['geometry']).coords),[(200,200),(250,200)])
            self.assertEqual(report['rejections']['compound_closed_stroke_deferred'],1)
        finally:doc.close()

    def test_optional_isolation_does_not_let_short_subpath_discard_valid_sibling(self):
        doc=pymupdf.open();page=doc.new_page();page.draw_line((10,10),(20,20))
        doc.update_stream(page.get_contents()[0],b'100 100 m 100.1 100 l 200 200 m 250 200 l S')
        try:
            rows,report=extract_page(page,'a'*64,1,isolate_open_stroked_subpaths=True)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['paint_references'][0]['subpath'],1)
            self.assertEqual(report['rejections']['Short line/symbol candidate'],1)
            self.assertNotEqual(contract(validated_options({})),contract(validated_options({'isolate_open_stroked_subpaths':True})))
            with self.assertRaises(ValueError):validated_options({'isolate_open_stroked_subpaths':1})
        finally:doc.close()

    def test_uniform_render_does_not_stretch_rounded_height(self):
        doc=pymupdf.open();page=doc.new_page(width=1684,height=2384)
        try:
            for rotation in (0,90,180,270):
                page.set_rotation(rotation);scale=1800/page.rect.width
                point=pymupdf.Point(200,300);native=point*native_inverse(page)
                expected=point*page.rotation_matrix*pymupdf.Matrix(scale,scale)
                actual=native*pymupdf.Matrix(native_to_render_pixels(page,1800))
                self.assertAlmostEqual(actual.x,expected.x,places=3)
                self.assertAlmostEqual(actual.y,expected.y,places=3)
                self.assertEqual(page.rotation,rotation)
        finally:doc.close()

if __name__=='__main__':unittest.main()
