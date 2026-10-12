import unittest
from unittest.mock import patch
import pymupdf
from shapely.geometry import box,shape
from voxel_mapper.osm_targeted_recovery import recover


class TargetedRecoveryTests(unittest.TestCase):
    def fixture(self):
        doc=pymupdf.open();page=doc.new_page(width=300,height=300)
        # Each original edge is below the ordinary 12-point line threshold.
        for a,b in zip([(100,100),(110,100),(110,110),(100,110)],[(110,100),(110,110),(100,110),(100,100)]):
            page.draw_line((a[0],300-a[1]),(b[0],300-b[1]))
        objects=[{'candidate_id':'failed','geometry':box(99,99,111,111)}]
        refs=[{'id':'ref','geometry':box(100,100,110,110)}]
        checks={'hypotheses':[{'held_out_checks':[{'candidate_id':'failed','reference_id':'ref','passed':False,
            'held_out_fit':{'matrix':[[1,0],[0,1]],'translation_m':[0,0]}}]}]}
        return doc,page,objects,refs,checks

    def test_short_complete_source_edges_recover_face_without_snapping(self):
        doc,page,objects,refs,checks=self.fixture()
        try:
            rows,report=recover(page,'a'*64,1,objects,refs,checks)
            faces=[r for r in rows if r.get('extraction_kind')=='linework_boundaries']
            self.assertEqual(len(faces),1);self.assertTrue(shape(faces[0]['geometry']).equals(box(100,100,110,110)))
            self.assertEqual(len(faces[0]['line_parent_references']),4)
            self.assertEqual(len({r['id'] for r in rows}),len(rows))
            self.assertEqual(report['geometry_types']['LineString'],4)
            self.assertFalse(report['registration_verified']);self.assertEqual(report['world_geometry_additions'],0)
        finally:doc.close()

    def test_window_crossing_primitive_is_withheld_not_clipped(self):
        doc,page,objects,refs,checks=self.fixture()
        try:
            page.draw_line((0,195),(300,195))
            rows,report=recover(page,'a'*64,1,objects,refs,checks)
            self.assertGreater(report['windows'][0]['extraction']['rejections']['complete_primitive_crosses_region_boundary'],0)
            self.assertFalse(any(shape(r['geometry']).length>100 for r in rows))
        finally:doc.close()

    def test_incomplete_extraction_cannot_feed_recovery(self):
        doc,page,objects,refs,checks=self.fixture()
        try:
            with patch('voxel_mapper.osm_targeted_recovery.extract_page',return_value=([],{'status':'partial_candidate_budget'})):
                rows,report=recover(page,'a'*64,1,objects,refs,checks)
            self.assertEqual(rows,[]);self.assertEqual(report['windows'][0]['status'],'extraction_budget_withheld')
        finally:doc.close()

    def test_overlapping_windows_preserve_each_source_contract_reference(self):
        doc,page,objects,refs,checks=self.fixture()
        try:
            objects.append({'candidate_id':'second','geometry':box(98,98,112,112)})
            checks['hypotheses'][0]['held_out_checks'].append({**checks['hypotheses'][0]['held_out_checks'][0],'candidate_id':'second'})
            rows,report=recover(page,'a'*64,1,objects,refs,checks)
            self.assertEqual(report['requested_windows'],2)
            self.assertTrue(all(len(r['targeted_window_references'])==2 for r in rows))
            self.assertTrue(all(len({w['extraction_contract'] for w in r['targeted_window_references']})==2 for r in rows))
            self.assertEqual(len({r['id'] for r in rows}),len(rows))
        finally:doc.close()

    def test_no_failed_checks_avoid_native_scan_and_invalid_budget_refused(self):
        doc,page,objects,refs,checks=self.fixture()
        try:
            checks['hypotheses'][0]['held_out_checks'][0]['passed']=True
            with patch.object(type(page),'get_cdrawings',side_effect=AssertionError('unnecessary scan')):
                rows,report=recover(page,'a'*64,1,objects,refs,checks)
            self.assertEqual(rows,[]);self.assertEqual(report['requested_windows'],0)
            with self.assertRaises(ValueError):recover(page,'a'*64,1,objects,refs,checks,max_windows=True)
        finally:doc.close()

if __name__=='__main__':unittest.main()
