import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageDraw
import pymupdf

from voxel_mapper import automatic_gable_roof as roof
from voxel_mapper import automatic_facade_preview,automatic_facade_profile
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from tests import test_automatic_facade_profile as profile_tests


def read(path):return json.loads(Path(path).read_text())


class GableRoofTests(unittest.TestCase):
    def panel(self):
        return {'id':'profile','nominal_metres_per_source_pixel':.1,'printed_level_pixel':200.,'variants':[
            {'threshold':t,'status':'source_profile_masks_only','source_upper_span_pixels':[0,100],
             'roof_source_regions':[{'label':i,'bounds_pixels':[i*8,30,i*8+3,80]} for i in range(10)],
             'roof_surface':{'source_rectangles_pixels':[[0,29,100,81]]}} for t in (220,235)]}

    def plan(self):
        return {'view_id':'roof','nominal_metres_per_pdf_point':.1,'source_components':[
            {'id':'line'+str(i),'geometry':{'type':'LineString','coordinates':[[0.,float(y)],[100.,float(y)]]},
             'curve_approximation':{'cubic_segments':0},'rendering_status':'supported_straight_unclipped_polyline'} for i,y in enumerate((0,40,80))]}

    def gray(self):
        image=Image.new('L',(500,320),255);ImageDraw.Draw(image).line([(50,240),(250,120),(450,240)],fill=0,width=2)
        return np.asarray(image).copy()

    def fixture(self,root):
        original=profile_tests.FacadeProfileTests.gray
        def slats(instance):
            gray=original(instance)
            for x in range(50,155,5):gray[31:80,x]=0
            return gray
        with patch.object(profile_tests.FacadeProfileTests,'gray',slats):prior,c,v,corpus,_=profile_tests.FacadeProfileTests().fixture(root)
        report=read(c/'component-report.json');source=read(v/'view-candidates.json');page=source['pages'][0]
        roof_view=next(x for x in page['views'] if x['id']=='roof');page['views'].remove(roof_view)
        with pymupdf.open() as doc:
            rp=doc.new_page(width=300,height=240)
            for y in (10.,50.,90.):rp.draw_line((45.,240-y),(156.,240-y))
            data=doc.tobytes()
        sha=hashlib.sha256(data).hexdigest();(corpus/'files'/(sha+'.pdf')).write_bytes(data)
        source['pages'].append({'document_sha256':sha,'page':1,'views':[roof_view]})
        invs={r['view_id']:read(c/r['file']) for r in report['results']}
        for key,inv in invs.items():
            inv['printed_claim'].update(view_kind='elevation' if key=='elevation' else 'plan')
            inv['source_components']=[];inv['document_sha256']=sha if key=='roof' else page['document_sha256'];inv['page']=1
        invs['elevation']['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix']=[1.,0.,0.,-1.,0.,240.]
        invs['roof']['printed_claim']['plan_level_or_form']='roof'
        invs['roof']['source_components']=[{'id':'roof-line-'+str(i),
            'geometry':{'type':'LineString','coordinates':[[45.,y],[156.,y]]},
            'curve_approximation':{'cubic_segments':0},'rendering_status':'supported_straight_unclipped_polyline'} for i,y in enumerate((10.,50.,90.))]
        reviews={key:read(c/report[key]['file']) for key in ('building_facade_links','elevation_level_context','facade_alignment','sheet_scale_evidence','wall_return_corners','door_symbol_evidence','artwork_scale_controls')}
        reviews['building_facade_links']['frames'][0]['frame_review']={'frames':[{'id':'source-frame','diagnostic_axis':[1.,0.]}]}
        ipins={key:digest(inv) for key,inv in invs.items()}
        for value in reviews.values():value['source_inventory_sha256']=ipins
        reviews['elevation_level_context']['source_building_links_sha256']=digest(reviews['building_facade_links'])
        reviews['elevation_level_context']['views'][0]['relative_reference']['status']='unverified_source_relative_shop_level'
        artwork=reviews['artwork_scale_controls'];artwork['pages'][0]['source_page_views_sha256']=digest(page)
        artwork['pages'].append(copy.deepcopy(artwork['pages'][0]));artwork['pages'][1].update(document_sha256=sha,source_page_views_sha256=digest(source['pages'][1]))
        artwork['pairs'][0]['reference_page_key']=[sha,1]
        for r in report['results']:atomic_json(c/r['file'],invs[r['view_id']])
        for key,value in reviews.items():atomic_json(c/report[key]['file'],value)
        report['output_sha256']={name:file_hash(c/name) for name in report['output_sha256']}
        atomic_json(v/'view-candidates.json',source);vr=read(v/'view-report.json');vr['contract']['source_sha256'].append(sha);vr['output_sha256']['view-candidates.json']=file_hash(v/'view-candidates.json');atomic_json(v/'view-report.json',vr)
        report['contract'].update(view_report_sha256=file_hash(v/'view-report.json'),view_candidates_sha256=file_hash(v/'view-candidates.json'));atomic_json(c/'component-report.json',report)
        previous=automatic_facade_preview.build(c,v,corpus,root/'new-preview');previous=Path(previous['directory'])
        profile=automatic_facade_profile.build(previous,c,v,corpus,root/'new-profile')
        return Path(profile['directory']),previous,c,v,corpus,root/'gable'

    def test_tall_panel_cohort_is_source_defined_and_ambiguous_cohorts_are_held(self):
        panel=self.panel();before=copy.deepcopy(panel);rows=roof.panel_heights(panel,lambda:None)
        self.assertEqual(panel,before);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['nominal_eave_height_m'],12.);self.assertAlmostEqual(rows[0]['nominal_ridge_height_m'],17.1)
        for variant in panel['variants']:
            for r in variant['roof_source_regions'][:5]:r['bounds_pixels'][1]=31
        self.assertTrue(all(r['status']=='dominant_tall_source_panel_cohort_required' for r in roof.panel_heights(panel,lambda:None)))

    def test_original_parallel_triples_keep_offsets_without_forcing_symmetry(self):
        inv=self.plan();inv['source_components'][1]['geometry']['coordinates']=[[0.,40.5],[100.,40.5]]
        original=copy.deepcopy(inv);r=roof.plan_triples(inv,[1.,0.],10.,lambda:None)
        self.assertEqual(inv,original);self.assertEqual(len(r['triples']),1);t=r['triples'][0]
        self.assertAlmostEqual(t['nominal_left_run_m'],4.05);self.assertAlmostEqual(t['nominal_right_run_m'],3.95)
        self.assertFalse(t['symmetry_forced']);self.assertTrue(all(not l['source_points_moved'] for l in r['lines']))

    def test_plan_length_alignment_curves_and_spacing_failures_are_retained_as_no_triple(self):
        for mode in ('length','alignment','spacing','curve'):
            inv=self.plan()
            if mode=='length':inv['source_components'][0]['geometry']['coordinates'][1][0]=70.
            if mode=='alignment':inv['source_components'][0]['geometry']['coordinates']=[[20.,0.],[120.,0.]]
            if mode=='spacing':inv['source_components'][1]['geometry']['coordinates']=[[0.,50.],[100.,50.]]
            if mode=='curve':inv['source_components'][1]['curve_approximation']['cubic_segments']=1
            self.assertEqual(roof.plan_triples(inv,[1.,0.],10.,lambda:None)['triples'],[],mode)
        with self.assertRaises(ValueError):roof.plan_triples(self.plan(),[2.,0.],10.,lambda:None)

    def test_original_raster_slopes_have_fixed_fit_checks_and_no_filled_gaps(self):
        gray=self.gray();before=gray.copy();mask=np.zeros_like(gray,dtype=bool);mask[:,80:90]=True
        scan=roof.slope_lines(gray,mask,220,lambda:None);self.assertGreaterEqual(len(scan['lines']),2)
        np.testing.assert_array_equal(gray,before)
        for line in scan['lines']:
            self.assertFalse(line['source_gaps_filled']);self.assertLessEqual(line['check_max_normal_residual_pixels'],3)
            for p in line['source_pixels']:
                self.assertFalse(mask[p['y'],p['x']]);self.assertEqual(p['gray'],int(gray[p['y'],p['x']]))
                self.assertEqual(p['role'],'fit' if p['x']%2==0 else 'check')
        self.assertTrue(any(line['unsupported_column_intervals'] for line in scan['lines']))

    def test_gable_ridge_is_an_inferred_intersection_not_a_source_vertex_or_depth(self):
        lines=[{'id':'L','slope':-.5,'intercept':185.,'source_x_interval':[20,150],'pitch_magnitude_degrees':26.565},
               {'id':'R','slope':.5,'intercept':35.,'source_x_interval':[150,280],'pitch_magnitude_degrees':26.565}]
        pairs=roof.gable_pairs(lines,.1,230.,lambda:None);self.assertEqual(len(pairs),1)
        self.assertEqual(pairs[0]['inferred_ridge_pixel'],[150.,110.]);self.assertEqual(pairs[0]['nominal_ridge_height_m'],12.)
        self.assertFalse(pairs[0]['ridge_is_original_source_vertex']);self.assertIsNone(pairs[0]['independent_depth_measurement_m'])

    def test_excluded_native_ink_has_original_receipts_and_does_not_edit_source(self):
        with pymupdf.open() as doc:
            page=doc.new_page(width=300,height=260);page.draw_line((20,40),(200,100));page.insert_text((50,200),'NOTE')
            inv={'source_components':[{'id':'native','geometry':{'type':'LineString','coordinates':[[20.,220.],[200.,160.]]}}]}
            mask,receipt=roof.exclusion_mask(inv,page,[1.,0.,0.,-1.,0.,260.],[300,260],lambda:None)
            self.assertTrue(mask[40,20]);self.assertFalse(receipt['source_image_changed'])
            self.assertTrue(any(r['kind']=='native_text_excluded_from_raster_proposals' for r in receipt['records']))
            self.assertEqual(receipt['source_mask_sha256'],hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest())

    def test_pitched_mesh_keeps_measured_unequal_runs_and_rejects_bad_dimensions(self):
        mesh=roof.roof_mesh(10.,4.05,3.95,3.,7.)
        self.assertAlmostEqual(mesh['vertices'][2][1],.05);self.assertEqual(len(mesh['triangles']),4)
        self.assertNotEqual(mesh['left_pitch_degrees'],mesh['right_pitch_degrees']);self.assertFalse(mesh['world_placement_eligible'])
        self.assertIsNone(mesh['wall_mesh']);self.assertEqual(mesh['openings_carved'],0)
        for args in [(0.,4.,4.,3.,7.),(10.,4.,4.,7.,3.),(10.,float('nan'),4.,3.,7.)]:
            with self.assertRaises(ValueError):roof.roof_mesh(*args)

    def test_source_pixel_and_plan_budgets_do_not_select_a_partial_best_candidate(self):
        inv=self.plan();inv['source_components']*=1366
        with self.assertRaises(OverflowError):roof.plan_triples(inv,[1.,0.],10.,lambda:None)
        gray=np.zeros((300,300),np.uint8)
        with patch.object(roof.ndimage,'sobel',side_effect=lambda values,axis:np.ones_like(values)):
            with self.assertRaisesRegex(OverflowError,'edge_pixel'):roof.slope_lines(gray,np.zeros_like(gray,dtype=bool),220,lambda:None)
        with self.assertRaises(ValueError):roof.slope_lines(np.ones((2,2),float),np.zeros((2,2),bool),220,lambda:None)

    def test_original_pdf_and_source_plan_end_to_end_replay_leave_acceptance_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=roof.build(*args)
            self.assertEqual(r['counts']['conditional_roof_models'],2);self.assertEqual(r['counts']['distinct_roof_meshes'],1)
            self.assertEqual(r['counts']['models_with_both_source_threshold_checks'],0)
            self.assertAlmostEqual(r['models'][0]['source_nominal_depth_m'],8.);self.assertEqual(r,roof.build(*args))
            self.assertFalse(r['world_placement_eligible']);self.assertEqual(r['accepted_physical_components'],0)

    def test_early_and_late_budget_holds_discard_all_partial_models_and_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=roof.build(*args,max_checks=1)
            self.assertEqual(r['status'],'gable_roof_budget_withheld');self.assertEqual(r['models'],[]);self.assertEqual(r['plan_reviews'],[])
            with patch.object(roof,'slope_lines',side_effect=OverflowError('late_slope_budget')):r=roof.build(*args)
            self.assertEqual(r['models'],[]);self.assertEqual(r['long_profile_reviews'],[]);self.assertEqual(r['gable_views'],[])
        for bad in (0,True,100001):
            with self.assertRaises(ValueError):roof.build('','','','','','',max_checks=bad)

    def test_source_profile_mask_json_or_pdf_change_is_rejected(self):
        for mode in ('mask','json','pdf'):
            with tempfile.TemporaryDirectory() as tmp:
                args=self.fixture(Path(tmp));profile,_,_,_,corpus,out=args
                if mode=='mask':next((profile/'masks').glob('*.png')).write_bytes(b'changed')
                if mode=='json':
                    p=profile/'facade-profile.json';value=read(p);value['profiles'][0]['nominal_metres_per_source_pixel']+=.1;atomic_json(p,value)
                if mode=='pdf':
                    # Choose a currently bound source; the fixture retains an earlier unused PDF too.
                    source=read(args[3]/'view-report.json')['contract']['source_sha256'][0]
                    p=corpus/'files'/(source+'.pdf');p.write_bytes(p.read_bytes()+b' ')
                with self.assertRaises(ValueError):roof.build(*args)
                self.assertFalse(out.exists())

    def test_independent_audit_checks_original_plan_lines_and_derived_mesh(self):
        from scripts.audit_automatic_gable_roof import audit
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=roof.build(*args)
            profile,preview,c,v,corpus,_=args
            checked=audit(r['directory'],profile,preview,c,v,corpus,Path(tmp)/'audit.json')
            self.assertEqual(checked['status'],'passed');self.assertEqual(checked['checked']['original_native_plan_line_receipts'],6)
            self.assertEqual(checked['checked']['pitched_roof_triangles'],8)

    def test_tampered_cached_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.fixture(Path(tmp));r=roof.build(*args);(Path(r['directory'])/'gable-roof-review.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Saved'):roof.build(*args)


if __name__=='__main__':unittest.main()
