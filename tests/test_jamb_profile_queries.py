import copy
import unittest

import numpy as np
import pymupdf

from tests import test_indexed_opening_correspondence as fixtures
from voxel_mapper.jamb_profile_queries import build,query
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.building_spec import digest


class PartialJambTests(unittest.TestCase):
    def evidence(self,extra_head=False):
        view,projection,frame,region=fixtures.IndexedCorrespondenceTests().evidence()
        gray=np.full((160,240),255,dtype='uint8')
        gray[30:125,40:43]=0;gray[30:105,170:173]=0;gray[30:33,40:173]=0
        gray[125:]=192  # The dark left jamb merges into the ground shade.
        if extra_head:gray[60:61,40:173]=0
        view['indexed_opening_scan']=scan(gray,representation='indexed')
        view['indexed_scan_sha256']=digest(view['indexed_opening_scan'])
        view['jamb_profile_evidence']=build(gray)
        view['jamb_profile_evidence_sha256']=digest(view['jamb_profile_evidence'])
        view['relative_level_reference']={'status':'unverified_source_relative_shop_level',
            'document_sha256':view['document_sha256'],'page':1,'view_key_candidate':view['view_key_candidate'],
            'nominal_metres_per_pdf_point_candidate':.1,'datum_y_display_points':125.,'reference_id':'source-level'}
        return gray,view,projection,frame,region

    def run_query(self,evidence,charge=lambda:None):
        _,view,projection,frame,region=evidence
        return query(view,projection,frame,region,pymupdf.Matrix(1,0,0,1,0,0),.1,.25,charge)

    def test_unequal_jamb_extents_and_ground_merge_preserve_all_missing_intervals(self):
        evidence=self.evidence();gray,view,_,_,_=evidence;before=gray.copy();packet=copy.deepcopy(view['jamb_profile_evidence'])
        self.assertEqual(view['indexed_opening_scan']['index']['consensus_families'],[])
        result=self.run_query(evidence)
        self.assertEqual(result['status'],'unverified_partial_level_reaching_jamb_profiles')
        self.assertTrue(result['matches'])
        match=next(m for m in result['matches'] if m['jamb_column_pair_pixels']==[43,170])
        self.assertEqual({p['nominal_lowest_support_above_printed_level_m'] for p in match['source_edge_profiles']},{0.,2.})
        self.assertTrue(any(p['unsupported_row_intervals'] for p in match['source_edge_profiles']))
        self.assertTrue(any(p['unsupported_interval_to_printed_level_pixels']==[105,125] for p in match['source_edge_profiles']))
        self.assertFalse(match['unsupported_intervals_filled']);self.assertFalse(match['physical_lower_endpoints_inferred'])
        self.assertFalse(match['physical_opening_verified']);self.assertFalse(match['continuous_jambs_verified'])
        self.assertTrue(np.array_equal(gray,before));self.assertEqual(view['jamb_profile_evidence'],packet)

    def test_all_competing_head_bands_remain_without_selecting_a_physical_head(self):
        result=self.run_query(self.evidence(extra_head=True))
        match=next(m for m in result['matches'] if m['jamb_column_pair_pixels']==[43,170])
        self.assertGreaterEqual(len(match['head_row_bands_pixels']),2)
        self.assertIn(60,[r['row'] for r in match['supported_head_rows']])
        self.assertFalse(match['physical_opening_verified'])

    def test_missing_level_source_conflict_and_mask_corruption_are_withheld(self):
        for fault in ('missing','source','mask','gray'):
            evidence=self.evidence();view=evidence[1]
            if fault=='missing':view.pop('relative_level_reference')
            elif fault=='source':view['relative_level_reference']['document_sha256']='c'*64
            elif fault=='mask':view['jamb_profile_evidence']['variants'][0]['edge_mask']['packed_sha256']='bad'
            else:view['jamb_profile_evidence']['source_gray_sha256']='bad'
            result=self.run_query(evidence)
            self.assertTrue(result['status'].startswith('withheld_'));self.assertEqual(result['matches'],[])

    def test_work_budget_propagates_and_invalid_raster_is_rejected(self):
        def exhausted():raise OverflowError
        with self.assertRaises(OverflowError):self.run_query(self.evidence(),exhausted)
        with self.assertRaises(ValueError):build(np.ones((5,5),dtype=float))


if __name__=='__main__':unittest.main()
