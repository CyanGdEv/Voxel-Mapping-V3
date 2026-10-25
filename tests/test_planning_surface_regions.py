"""Regional scans retain original geometry and one shared bounded paint scan."""
from concurrent.futures import CancelledError
import copy
import hashlib
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box,shape

from voxel_mapper import ordinary_surfaces,planning_outline_semantics
from voxel_mapper import planning_surface_footprints as surfaces


def source():
    doc=pymupdf.open();page=doc.new_page(width=1400,height=500)
    for rect,text,origin in (((60,100,180,220),'Footpath',(80,160)),
                             ((1120,100,1240,220),'Plaza',(1140,160))):
        page.draw_rect(rect);page.insert_text(origin,text,fontsize=9)
    for i in range(150):
        x=500+i%15*4;y=80+i//15*4
        page.draw_line((x,y),(x+2,y+1))
    sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
    inventory=report['source_outline_inventory']
    semantics=planning_outline_semantics.page_candidates(page,sha,1,inventory)
    return doc,page,sha,1,inventory,semantics


class SurfaceRegionTests(unittest.TestCase):
    def fixture(self):
        doc,*args=source();self.addCleanup(doc.close);return doc,args

    def test_distant_labels_skip_intervening_clutter_with_same_total_candidate_budget(self):
        doc,args=self.fixture();page,sha,number,inventory,semantics=args
        before=doc.tobytes(no_new_id=True)
        _,old,_,_=ordinary_surfaces.closed_source_faces(page,sha,1,extraction_options={
            'region_native_points':[0,150,1350,490],'min_line_length_points':.25,'max_candidates':20})
        self.assertEqual(old['status'],'partial_candidate_budget')
        with patch.object(ordinary_surfaces,'_source_page_cache',wraps=ordinary_surfaces._source_page_cache) as cache:
            result=surfaces.page_candidates(*args,options={'max_native_candidates':20})
        self.assertEqual(cache.call_count,1)
        self.assertTrue(result['analysis_complete'],result.get('reason'))
        self.assertEqual(len(result['candidates']),2)
        self.assertEqual(len(result['extraction']['regions']),2)
        self.assertLess(result['extraction']['candidates'],20)
        self.assertEqual(doc.tobytes(no_new_id=True),before)
        actual=[shape(r['geometry_pdf_native']) for r in result['candidates']]
        self.assertTrue(any(g.equals(box(60,280,180,400)) for g in actual))
        self.assertTrue(any(g.equals(box(1120,280,1240,400)) for g in actual))

    def test_region_scan_and_combined_native_limits_withhold_every_candidate(self):
        _,args=self.fixture()
        for options in ({'max_regions':1},{'max_scan_work_paths':1},
                        {'max_native_candidates':1},{'max_native_points':5}):
            with self.subTest(options=options):
                result=surfaces.page_candidates(*args,options=options)
                self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])

    def test_later_region_failure_never_publishes_the_first_successful_region(self):
        _,args=self.fixture();original=ordinary_surfaces.closed_source_faces;calls=[]
        def fail_later(*a,**kw):
            calls.append(1)
            if len(calls)==2:raise ValueError('second region failed')
            return original(*a,**kw)
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=fail_later):
            result=surfaces.page_candidates(*args)
        self.assertEqual(len(calls),2);self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['candidates'],[])

    def test_cache_matches_uncached_geometry_and_rejects_other_or_changed_pages(self):
        doc,args=self.fixture();page,sha,number,_,_=args
        cache=ordinary_surfaces._source_page_cache(page)
        options={'region_native_points':[0,150,350,490],'min_line_length_points':.25}
        cached=ordinary_surfaces.closed_source_faces(page,sha,1,extraction_options=options,_cache=cache)
        self.assertEqual(cached,ordinary_surfaces.closed_source_faces(page,sha,1,extraction_options=options))
        page.draw_rect((80,120,160,190),color=None,fill=(1,1,1))
        with self.assertRaisesRegex(ValueError,'changed'):
            ordinary_surfaces.closed_source_faces(page,sha,1,_cache=cache)
        other=doc.new_page()
        with self.assertRaisesRegex(ValueError,'Same original'):
            ordinary_surfaces.closed_source_faces(other,sha,2,_cache=cache)

    def test_overlapping_windows_deduplicate_complete_boundaries(self):
        from tests.test_planning_surface_footprints import fixture
        doc,*args=fixture(short=False);self.addCleanup(doc.close)
        result=surfaces.page_candidates(args[0],args[1],1,*args[2:])
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(len(result['candidates']),2)
        ids=[r['candidate_id'] for r in result['fine_inventory_records']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_cancellation_between_regions_propagates(self):
        _,args=self.fixture();cancelled=[False];original=ordinary_surfaces.closed_source_faces
        def stop_after_first(*a,**kw):
            result=original(*a,**kw);cancelled[0]=True;return result
        with patch.object(ordinary_surfaces,'closed_source_faces',side_effect=stop_after_first):
            with self.assertRaises(CancelledError):
                surfaces.page_candidates(*args,cancelled=lambda:cancelled[0])


if __name__=='__main__':unittest.main()
