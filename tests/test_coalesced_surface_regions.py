"""Shared primitive extraction and separate complete region recovery."""
from concurrent.futures import CancelledError
import hashlib
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box,shape

from voxel_mapper import drawing_geometry,ordinary_surfaces,planning_outline_semantics
from voxel_mapper import planning_surface_footprints as surfaces


def source(count=40):
    doc=pymupdf.open();page=doc.new_page(width=1500,height=1000)
    for i in range(count):
        x=60+i%8*90;y=80+i//8*60
        page.draw_rect((x,y,x+76,y+46));page.insert_text((x+12,y+27),'Path',fontsize=6)
    sha=hashlib.sha256(doc.tobytes()).hexdigest()
    _,_,report=ordinary_surfaces.page_candidates(page,sha,1);inventory=report['source_outline_inventory']
    assoc=planning_outline_semantics.page_candidates(page,sha,1,inventory)
    return doc,page,sha,1,inventory,assoc


class CoalescedSurfaceTests(unittest.TestCase):
    def fixture(self,count=40):
        doc,*args=source(count);self.addCleanup(doc.close);return doc,args

    def test_more_than_32_labels_recover_with_one_region_and_unique_native_budget(self):
        doc,args=self.fixture();before=doc.tobytes(no_new_id=True)
        with patch.object(ordinary_surfaces,'extract_page',wraps=drawing_geometry.extract_page) as extract:
            result=surfaces.page_candidates(*args,options={'max_regions':1,'max_native_candidates':40})
        self.assertTrue(result['analysis_complete'],result.get('reason'))
        self.assertEqual(len(result['candidates']),40)
        e=result['extraction'];self.assertEqual(extract.call_count,1)
        self.assertEqual(e['source_path_passes'],1);self.assertEqual(e['candidates'],40)
        self.assertEqual(e['coalescing']['original_window_count'],40)
        self.assertEqual(len(e['regions']),1)
        self.assertEqual(e['regions'][0]['source_window_indices'],list(range(40)))
        self.assertLessEqual(e['coalescing']['coalesced_summed_area_pdf_points_squared'],e['coalescing']['original_summed_area_pdf_points_squared'])
        for i in range(40):
            x=60+i%8*90;y=80+i//8*60
            self.assertTrue(any(shape(r['geometry_pdf_native']).equals(box(x,1000-y-46,x+76,1000-y)) for r in result['candidates']))
        self.assertEqual(doc.tobytes(no_new_id=True),before)
        self.assertEqual(result['world_geometry_additions'],0)

    def test_merge_work_native_point_and_candidate_budgets_withhold_all_output(self):
        _,args=self.fixture()
        for limits in ({'max_region_merge_checks':1},{'max_native_candidates':39},{'max_native_points':50}):
            with self.subTest(limits=limits):
                result=surfaces.page_candidates(*args,options=limits)
                self.assertFalse(result['analysis_complete']);self.assertEqual(result['candidates'],[])

    def test_schedule_is_deterministic_covers_every_original_scope_and_cancels(self):
        windows=[(0,0,100,100),(20,0,120,100),(500,0,600,100)]
        a,receipt=surfaces._coalesce_windows(windows,65536,lambda:None)
        self.assertEqual(a,surfaces._coalesce_windows(windows,65536,lambda:None)[0])
        self.assertEqual(sorted(i for r in a for i in r['source_window_indices']),[0,1,2])
        for r in a:
            for i in r['source_window_indices']:self.assertTrue(box(*r['region_native_points']).covers(box(*windows[i])))
        self.assertEqual(receipt['coalesced_region_count'],2)
        def stop():raise CancelledError('stop')
        with self.assertRaises(CancelledError):surfaces._coalesce_windows(windows,65536,stop)

    def test_shared_union_keeps_original_paint_ordinals_and_partial_groups_out(self):
        doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=800,height=400)
        p.draw_line((350,300),(450,300)) # Outside both scopes, but ordinal zero stays reserved.
        p.draw_rect((60,100,150,180));p.draw_rect((600,100,690,180))
        p.draw_polyline([(80,200),(80,250),(650,250)]) # Whole paint group crosses both scopes.
        windows=[[30,100,200,330],[550,100,730,330]]
        rows,report=drawing_geometry.extract_page(p,'a'*64,1,region_native_windows=windows,min_line_length_points=.25)
        self.assertEqual(report['status'],'unplaced_geometry_candidates')
        self.assertEqual(len(rows),2)
        self.assertEqual(sorted(r['paint_references'][0]['ordinal'] for r in rows),[1,2])
        self.assertEqual(sorted(r['paint_references'][0]['source_region_indices'] for r in rows),[[0],[1]])
        with self.assertRaises(ValueError):drawing_geometry.extract_page(p,'a'*64,1,region_native_windows=windows,region_native_points=windows[0])
        withheld,report=drawing_geometry.extract_pipeline_page(p,'a'*64,1,region_native_windows=windows,max_scan_paths=1)
        self.assertEqual(withheld,[]);self.assertEqual(report['status'],'path_budget_withheld')

    def test_global_later_paint_outside_union_still_withholds_covered_boundary(self):
        doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=700,height=500)
        p.draw_rect((100,100,220,200));p.insert_text((120,150),'Path',fontsize=8)
        p.draw_rect((95,95,650,115),fill=(1,1,1),color=None)
        sha=hashlib.sha256(doc.tobytes()).hexdigest();_,_,report=ordinary_surfaces.page_candidates(p,sha,1)
        inv=report['source_outline_inventory'];a=planning_outline_semantics.page_candidates(p,sha,1,inv)
        result=surfaces.page_candidates(p,sha,1,inv,a)
        self.assertTrue(result['analysis_complete']);self.assertEqual(result['visible_surface_labels'],1)
        self.assertEqual(result['candidates'],[])
        self.assertGreater(result['covered_boundaries_withheld'],0)

    def test_already_ineligible_curves_and_nonsolid_open_lines_do_not_consume_face_quota(self):
        doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=500,height=500)
        for i in range(20):
            p.draw_circle((60+i*12,70),4)
            p.draw_line((60+i*12,110),(65+i*12,115),dashes='[2 2] 0')
        p.draw_rect((100,200,200,300))
        opts={'region_native_windows':[[20,20,450,480]],'max_candidates':1,'min_line_length_points':.25}
        _,old=drawing_geometry.extract_page(p,'a'*64,1,**opts)
        self.assertEqual(old['status'],'partial_candidate_budget')
        rows,report=drawing_geometry.extract_page(p,'a'*64,1,source_face_primitives_only=True,**opts)
        self.assertEqual(report['status'],'unplaced_geometry_candidates')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['paint_references'][0]['ordinal'],40)
        self.assertEqual(report['rejections']['source_face_curved_paint_ineligible'],20)
        self.assertEqual(report['rejections']['source_face_nonsolid_open_paint_ineligible'],20)

    def test_faces_cannot_close_a_loop_across_distinct_recovery_scopes(self):
        doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=600,height=400)
        p.draw_polyline([(300,100),(60,100),(60,300),(300,300)])
        p.draw_polyline([(300,100),(540,100),(540,300),(300,300)])
        windows=[[30,60,330,330],[270,60,570,330]]
        cache=ordinary_surfaces._source_page_cache(p)
        parents,report=drawing_geometry.extract_page(p,'a'*64,1,region_native_windows=windows,min_line_length_points=.25)
        combined=ordinary_surfaces.closed_source_faces(p,'a'*64,1,_cache=cache,_parents=(parents,report))[0]
        self.assertEqual(len(combined),1) # Mixing the two scopes would close this exact loop.
        for index in (0,1):
            scoped=[r for r in parents if index in r['paint_references'][0]['source_region_indices']]
            self.assertEqual(len(scoped),1)
            faces=ordinary_surfaces.closed_source_faces(p,'a'*64,1,_cache=cache,_parents=(scoped,report))[0]
            self.assertEqual(faces,[])

    def test_nonsolid_alias_keeps_the_original_ambiguity_guard(self):
        for alias in ('dashed','curved'):
            with self.subTest(alias=alias):
                doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=500,height=500)
                points=[(100,100),(200,100),(200,200),(100,200),(100,100)]
                for a,b in zip(points,points[1:]):p.draw_line(a,b)
                if alias=='dashed':p.draw_line(points[0],points[1],dashes='[2 2] 0')
                else:p.draw_bezier(points[0],(130,100),(170,100),points[1])
                windows=[[40,200,260,460]]
                parents,report=drawing_geometry.extract_page(p,'a'*64,1,region_native_windows=windows,min_line_length_points=.25,source_face_primitives_only=True)
                blocked=[r for r in parents if r.get('source_face_ineligible_regions')==[0]]
                self.assertEqual(len(blocked),1)
                scoped=[r for r in parents if 0 not in r.get('source_face_ineligible_regions',[])]
                cache=ordinary_surfaces._source_page_cache(p)
                self.assertEqual(ordinary_surfaces.closed_source_faces(p,'a'*64,1,_cache=cache,_parents=(scoped,report))[0],[])

    def test_union_keeps_clipping_scope_even_when_clip_bounds_are_outside_windows(self):
        doc=pymupdf.open();self.addCleanup(doc.close);p=doc.new_page(width=400,height=400)
        content=doc.get_new_xref();doc.update_object(content,'<<>>')
        doc.update_stream(content,b'q 0 0 40 40 re W n 100 100 60 60 re S Q 230 100 60 60 re S')
        doc.xref_set_key(p.xref,'Contents',f'{content} 0 R')
        rows,report=drawing_geometry.extract_page(p,'a'*64,1,region_native_windows=[[80,80,180,180],[210,80,310,180]])
        self.assertEqual(report['status'],'unplaced_geometry_candidates')
        self.assertEqual(len(rows),1)
        self.assertTrue(shape(rows[0]['geometry']).equals(box(230,100,290,160)))
        self.assertGreater(report['rejections']['Paint group crosses clipping boundary'],0)


if __name__=='__main__':unittest.main()
