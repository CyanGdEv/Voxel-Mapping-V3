import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf

from voxel_mapper import site_roof_correspondence as kernel
from voxel_mapper import site_roof_evidence as evidence


class SiteRoofTests(unittest.TestCase):
    def data(self):
        source={'id':'source','source_apex_pdf_native':[0,0],
            'source_corners_pdf_native':[[-50,-50],[50,-50],[50,50],[-50,50]]}
        target={'id':'target','source_apex_pdf_native':[250,250],
            'source_corners_pdf_native':[[200,200],[300,200],[300,300],[200,300]],
            'source_perimeter_ids_per_edge':[['edge'+str(i)] for i in range(4)],
            'source_spoke_ids_per_corner':[['spoke'+str(i)] for i in range(4)]}
        ridge={'source_component_id':'ridge','source_endpoints_pdf_native':[[0,-150],[0,-50]]}
        lines=[{'id':'site-ridge','source_endpoints_pdf_native':[[250,100],[250,200]]}]
        pixels=[{'line_id':sid,'all_samples_supported':True} for sid in ['site-ridge']+['edge'+str(i) for i in range(4)]+['spoke'+str(i) for i in range(4)]]
        return source,target,ridge,lines,pixels

    def rows(self,data=None,source_unit=.1,target_unit=.1):
        a,b,r,lines,_=data or self.data()
        return kernel.registrations(a,b,source_unit,target_unit,r,lines,lambda:None)

    def test_all_eight_mappings_and_both_handednesses_survive(self):
        rows=self.rows();self.assertEqual(len(rows),8)
        self.assertEqual(sum(r['reflection_candidate'] for r in rows),4)
        self.assertEqual(len({tuple(r['architectural_to_site_corner_indices']) for r in rows}),8)
        self.assertTrue(all(np.allclose(np.array(r['orthogonal_matrix']).T@np.array(r['orthogonal_matrix']),np.eye(2)) for r in rows))

    def test_adjoining_ridge_preserves_two_reflected_correspondences(self):
        data=self.data();support=kernel.support(self.rows(data),[data[1]],data[4]);good=[r for r in support if r['status']=='conditional_compound_roof_registration_supported']
        self.assertEqual(len(good),2);self.assertEqual(sum(r['reflection_candidate'] for r in good),1)
        self.assertTrue(all(not r['physical_component_identity_verified'] and not r['geographic_registration_verified'] and not r['world_export_authorized'] for r in good))

    def test_fixed_original_scales_cannot_be_fitted_to_wrong_size(self):
        data=self.data();rows=self.rows(data,source_unit=.2)
        self.assertTrue(all(r['maximum_corner_residual_nominal_m']>1 for r in rows))
        self.assertFalse(any(r['status']=='conditional_compound_roof_registration_supported' for r in kernel.support(rows,[data[1]],data[4])))

    def test_rotated_plan_keeps_compound_support(self):
        data=self.data();a,b,r,lines,pixels=data;angle=.7;matrix=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
        b['source_corners_pdf_native']=[(matrix@p).tolist() for p in b['source_corners_pdf_native']];b['source_apex_pdf_native']=(matrix@b['source_apex_pdf_native']).tolist()
        lines[0]['source_endpoints_pdf_native']=[(matrix@p).tolist() for p in lines[0]['source_endpoints_pdf_native']]
        self.assertEqual(sum(r['status']=='conditional_compound_roof_registration_supported' for r in kernel.support(self.rows(data),[b],pixels)),2)

    def test_clockwise_original_winding_does_not_erase_reflection(self):
        data=self.data();data[0]['source_corners_pdf_native'].reverse()
        support=kernel.support(self.rows(data),[data[1]],data[4]);good=[r for r in support if r['status']=='conditional_compound_roof_registration_supported']
        self.assertEqual(len(good),2);self.assertEqual(sum(r['reflection_candidate'] for r in good),1)

    def test_same_length_at_wrong_position_is_not_translated(self):
        data=self.data();data[3][0]['source_endpoints_pdf_native']=[[235,100],[235,200]]
        self.assertFalse(any(c['whole_ridge_endpoints_compatible'] for r in self.rows(data) for c in r['ridge_comparisons']))

    def test_longer_source_line_is_never_clipped_to_match(self):
        data=self.data();data[3][0]['source_endpoints_pdf_native'][0][1]-=20
        self.assertFalse(any(c['whole_ridge_endpoints_compatible'] for r in self.rows(data) for c in r['ridge_comparisons']))

    def test_both_original_endpoint_orders_are_retained(self):
        rows=self.rows();self.assertTrue(all(len(r['ridge_comparisons'])==2 for r in rows))
        self.assertTrue(all([c['original_site_endpoint_order'] for c in r['ridge_comparisons']]==[[0,1],[1,0]] for r in rows))

    def test_missing_roof_or_ridge_pixel_support_holds_registration(self):
        for missing in ('edge0','site-ridge'):
            data=self.data();pixels=[p for p in data[4] if p['line_id']!=missing]
            self.assertFalse(any(r['status']=='conditional_compound_roof_registration_supported' for r in kernel.support(self.rows(data),[data[1]],pixels)))

    def test_duplicate_paints_do_not_require_deleting_a_failed_witness(self):
        data=self.data();data[1]['source_perimeter_ids_per_edge'][0].append('duplicate')
        data[4].append({'line_id':'duplicate','all_samples_supported':False});before=copy.deepcopy(data)
        good=[r for r in kernel.support(self.rows(data),[data[1]],data[4]) if r['status']=='conditional_compound_roof_registration_supported']
        self.assertEqual(len(good),2);self.assertEqual(data,before)

    def test_quad_edges_preserve_native_corner_order_without_diagonals(self):
        q=((10,10),(20,10),(10,20),(20,20));rows=kernel.primitive_edges(('qu',q))
        self.assertEqual([r[1] for r in rows],[[[10,10],[20,10]],[[20,10],[20,20]],[[20,20],[10,20]],[[10,20],[10,10]]])
        self.assertTrue(all(math.dist(*r[1])==10 for r in rows))

    def test_rectangles_keep_four_explicit_edges_and_curves_are_not_fitted(self):
        rows=kernel.primitive_edges(('re',(10,10,20,20),1));self.assertEqual(len(rows),4)
        self.assertEqual(kernel.primitive_edges(('c',(0,0),(1,1),(2,2),(3,3))),[])
        self.assertEqual(len(kernel.primitive_edges(('l',(0,0),(1,1)))),1)

    def test_source_window_retains_duplicate_primitives_and_does_not_infer_a_closing_stroke(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=800,height=800)
            p.draw_quad(pymupdf.Quad((300,300),(400,300),(300,400),(400,400)))
            p.draw_line((350,350),(300,300));p.draw_line((350,350),(300,300));p.draw_line((300,300),(750,300))
            words=[{'id':'label','source_bbox_pdf_unrotated':[340,340,360,360],'status':'source_numeric_glyph_candidate'}]
            rows=kernel.original_lines(p,'a'*64,words,.1,lambda:None)
        self.assertEqual(len(rows),6);self.assertEqual(sum(l['original_primitive']=='qu' for l in rows),4)
        self.assertTrue(all(not l['implicit_closing_edge_invented'] and not l['source_line_clipped_or_extended'] for l in rows))

    def test_held_context_word_cannot_select_a_source_region(self):
        with pymupdf.open() as doc:
            p=doc.new_page(width=800,height=800);p.draw_line((300,300),(400,300))
            self.assertEqual(kernel.original_lines(p,'a'*64,[{'id':'held','source_bbox_pdf_unrotated':[300,300,400,320],'status':'numeric_source_glyphs_held'}],.1,lambda:None),[])

    def test_invalid_source_geometry_and_scale_are_rejected(self):
        for mode in ('scale','point','edge'):
            data=self.data();unit=.1
            if mode=='scale':unit=float('nan')
            elif mode=='point':data[2]['source_endpoints_pdf_native'][0][0]=float('inf')
            else:data[0]['source_corners_pdf_native'][0]=data[0]['source_corners_pdf_native'][1]
            with self.assertRaises(ValueError):self.rows(data,source_unit=unit)

    def fixture(self,root):
        def write(name,data):
            p=root/name;p.write_text(json.dumps(data));return p
        with pymupdf.open() as doc:
            p=doc.new_page(width=800,height=800);p.insert_text((100,100),'1/250');raw=doc.tobytes()
        sha=hashlib.sha256(raw).hexdigest();(root/(sha+'.pdf')).write_bytes(raw)
        site=write('site-catalogue.json',{'entries':[{'sha256':sha,'title':'site','context_word':'Station','nominal_scale_denominator':250}]})
        adjoining={'status':'section_adjoining_ridge_diagnostics_only','contract':{'max_checks':2000000},'plan_ridges':[],'conditional_face_constraints':[]}
        a=write('adjoining.json',adjoining);projection=write('projection.json',{'projection_candidates':[]});pyramid=write('pyramid.json',{'plan_graphs':[]});other=write('other.json',{})
        return (a,projection,other,pyramid,other,other,site,root,other,other,root/'output'),adjoining

    def replay(self,adjoining):
        return patch.object(evidence.parent,'build',side_effect=lambda *a,**k:{**copy.deepcopy(adjoining),'directory':'synthetic-parent-replay'})

    def test_build_replays_parent_and_rejects_changed_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,parent=self.fixture(Path(tmp))
            with self.replay(parent):
                r=evidence.build(*args);self.assertEqual(r,evidence.build(*args));self.assertTrue(r['parent_adjoining_fresh_replay_identical'])
                self.assertEqual(r['world_geometry_additions'],0)
                (Path(r['directory'])/'site-roof-evidence.json').write_text('{}')
                with self.assertRaises(ValueError):evidence.build(*args)

    def test_changed_source_and_parent_replay_are_rejected(self):
        for mode in ('source','parent'):
            with tempfile.TemporaryDirectory() as tmp:
                args,parent=self.fixture(Path(tmp))
                if mode=='source':next(Path(tmp).glob('*.pdf')).write_bytes(b'changed')
                with patch.object(evidence.parent,'build',return_value={'directory':'changed'}),self.assertRaises(ValueError):evidence.build(*args)

    def test_work_exhaustion_before_parent_and_after_page_output_clears_all_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,parent=self.fixture(Path(tmp))
            with patch.object(evidence.parent,'build') as replay:
                r=evidence.build(*args,max_checks=1);self.assertEqual(replay.call_count,0)
            self.assertEqual(r['status'],'site_roof_correspondence_budget_withheld')
            with self.replay(parent),patch.object(kernel,'support',side_effect=OverflowError('late')):r=evidence.build(*args)
            self.assertEqual(r['status'],'site_roof_correspondence_budget_withheld')
            self.assertTrue(all(r[f]==[] for f in ('source_pages','registrations','registration_support','section_site_camera_candidates')))

    def test_source_changed_during_processing_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,parent=self.fixture(Path(tmp))
            def changed(*a,**k):args[0].write_text('{}');return {**copy.deepcopy(parent),'directory':'synthetic'}
            with patch.object(evidence.parent,'build',side_effect=changed),self.assertRaises(ValueError):evidence.build(*args)

    def test_invalid_work_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,parent=self.fixture(Path(tmp))
            for limit in (True,0,200001):
                with self.assertRaises(ValueError):evidence.build(*args,max_checks=limit)
