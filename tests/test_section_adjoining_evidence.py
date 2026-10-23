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

from voxel_mapper import section_adjoining_ridges as kernel
from voxel_mapper import section_adjoining_evidence as evidence
from voxel_mapper import section_roof_projection


class AdjoiningRidgeTests(unittest.TestCase):
    def data(self):
        c={'id':'plan','source_corners_pdf_native':[[-50,-50],[50,-50],[50,50],[-50,50]],
           'source_apex_pdf_native':[0,0],'source_perimeter_ids_per_edge':[['cap'],['right'],['far'],['left']]}
        u=np.array([.2,math.sqrt(.96)]);xs=200+np.array(c['source_corners_pdf_native'])@u
        group={'id':'group','status':'original_three_spoke_whole_base_candidate',
               'source_apex_pdf_unrotated':[200,80],'nominal_metres_per_pdf_point':.1,
               'source_roof_spokes':[{'source_base_vertex_pdf_unrotated':[float(xs[i]),130]} for i in (0,1,2)]}
        ridge={'source_component_id':'ridge','source_endpoints_pdf_native':[[0,-150],[0,-50]]}
        line={'id':'line','source_group_ids':['group'],'source_endpoints_pdf_unrotated':[[200-150*u[1],140],[200-50*u[1],140]]}
        poses=section_roof_projection.projections(group,c,.1,'cap',lambda:None)
        return c,group,ridge,line,poses

    def checks(self,data=None):
        c,g,r,l,poses=data or self.data()
        return [kernel.compare(g,p,c,r,.1,[l],lambda:None) for p in poses]

    def test_both_whole_endpoints_break_six_symmetries_without_changing_parent(self):
        data=self.data();before=copy.deepcopy(data);rows=self.checks(data)
        self.assertEqual(sum(any(c['endpoints_compatible'] for c in r['comparisons']) for r in rows),2)
        self.assertEqual(data,before)
        self.assertTrue(all(r['candidate_shared_cap_visible'] for r in rows if r['comparisons'][0]['endpoints_compatible']))

    def test_left_right_order_preserves_original_ridge_endpoint_identity(self):
        c,g,r,l,poses=self.data();r['source_endpoints_pdf_native'].reverse()
        rows=[kernel.compare(g,p,c,r,.1,[l],lambda:None) for p in poses]
        supported=[r for r in rows if r['comparisons'][0]['endpoints_compatible']]
        self.assertEqual(len(supported),2)
        self.assertTrue(all(r['comparisons'][0]['left_right_original_ridge_endpoint_indices']==[1,0] for r in supported))

    def test_same_length_at_wrong_position_is_not_translated_into_place(self):
        data=self.data()
        for p in data[3]['source_endpoints_pdf_unrotated']:p[0]+=30
        self.assertFalse(any(c['endpoints_compatible'] for r in self.checks(data) for c in r['comparisons']))

    def test_partial_longer_line_cannot_be_clipped_into_a_match(self):
        data=self.data();data[3]['source_endpoints_pdf_unrotated'][0][0]-=15
        self.assertFalse(any(c['endpoints_compatible'] for r in self.checks(data) for c in r['comparisons']))

    def test_wrong_scale_is_not_fitted_to_ridge_length(self):
        c,g,r,l,poses=self.data()
        rows=[kernel.compare(g,p,c,r,.2,[l],lambda:None) for p in poses]
        self.assertFalse(any(c['endpoints_compatible'] for r in rows for c in r['comparisons']))

    def test_fixed_endpoint_tolerance_is_inclusive_and_not_residual_ranked(self):
        data=self.data()
        for p in data[3]['source_endpoints_pdf_unrotated']:p[0]+=.5
        self.assertEqual(sum(c['endpoints_compatible'] for r in self.checks(data) for c in r['comparisons']),2)
        for p in data[3]['source_endpoints_pdf_unrotated']:p[0]+=.0001
        self.assertEqual(sum(c['endpoints_compatible'] for r in self.checks(data) for c in r['comparisons']),0)

    def test_parent_held_camera_cannot_gain_support(self):
        data=self.data()
        for pose in data[4]:pose['status']='section_projection_held'
        self.assertFalse(any(c['endpoints_compatible'] for r in self.checks(data) for c in r['comparisons']))

    def test_rotated_native_frame_preserves_endpoint_support(self):
        data=self.data();c,g,r,l,poses=data
        rotate=lambda p:[-p[1],p[0]]
        c['source_corners_pdf_native']=list(map(rotate,c['source_corners_pdf_native']))
        r['source_endpoints_pdf_native']=list(map(rotate,r['source_endpoints_pdf_native']))
        poses=section_roof_projection.projections(g,c,.1,'cap',lambda:None)
        self.assertEqual(sum(c['endpoints_compatible'] for row in self.checks((c,g,r,l,poses)) for c in row['comparisons']),2)

    def test_missing_pixel_support_holds_all_geometric_matches(self):
        data=self.data();rows=self.checks(data)
        summary=kernel.summarize([data[1]],rows,[{'line_id':'line','all_samples_supported':False}])[0]
        self.assertEqual(summary['conditionally_supported_projection_count'],0)
        self.assertIsNone(summary['conditional_shared_cap_visible'])

    def test_support_keeps_reflection_and_physical_identity_hold(self):
        data=self.data();r=kernel.summarize([data[1]],self.checks(data),[{'line_id':'line','all_samples_supported':True}])[0]
        self.assertEqual(r['conditionally_supported_projection_count'],2);self.assertTrue(r['conditional_shared_cap_visible'])
        self.assertFalse(r['parent_orientations_deleted']);self.assertFalse(r['best_residual_candidate_selected'])
        self.assertFalse(r['physical_face_assignment_verified']);self.assertFalse(r['wall_closure_authorized'])

    def test_other_group_strokes_never_support_this_camera(self):
        data=self.data();data[3]['source_group_ids']=['other']
        self.assertTrue(all(not row['comparisons'] for row in self.checks(data)))

    def test_no_whole_line_does_not_invent_boundary(self):
        c,g,r,l,poses=self.data();rows=[kernel.compare(g,p,c,r,.1,[],lambda:None) for p in poses]
        summary=kernel.summarize([g],rows,[])[0]
        self.assertEqual(summary['status'],'adjoining_ridge_source_support_held')

    def test_nonfinite_and_nonunit_camera_inputs_are_rejected(self):
        for mode in ('points','camera','plan_scale','section_scale'):
            c,g,r,l,poses=self.data();unit=.1
            if mode=='points':r['source_endpoints_pdf_native'][0][0]=float('nan')
            elif mode=='camera':poses[0]['unit_projection_horizontal_vector']=[2,0]
            elif mode=='plan_scale':unit=0
            else:g['nominal_metres_per_pdf_point']=float('inf')
            with self.assertRaises(ValueError):kernel.compare(g,poses[0],c,r,unit,[l],lambda:None)

    def test_source_only_windows_keep_whole_lines_and_exclude_crossing_items(self):
        _,group,*_=self.data()
        with pymupdf.open() as doc:
            p=doc.new_page(width=600,height=400)
            p.draw_line((40,140),(140,140),color=(.65,.42,.21));p.draw_line((20,140),(450,140))
            p.draw_line((40,140),(140,141));p.draw_line((40,240),(140,240));p.draw_line((40,150),(140,150),dashes='[3 2] 0')
            rows=kernel.horizontal_strokes(p,'a'*64,[group],lambda:None)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_endpoints_pdf_unrotated'],[[40,140],[140,140]])
        self.assertFalse(rows[0]['source_line_clipped_or_extended'])

    def fixture(self,root):
        def write(name,data):
            p=root/name;p.write_text(json.dumps(data));return p
        reference=write('reference.json',{'source_topologies':[]})
        pyramid=write('pyramid.json',{'contract':{'source_reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest()},'plan_graphs':[],'source_junctions':[]})
        projection={'status':'section_projection_diagnostics_only','contract':{'max_projection_checks':100000},'source_groups':[],'projection_candidates':[]}
        projection_path=write('projection.json',projection);section=write('section.json',{'pages':[]});other=write('other.json',{})
        return (projection_path,section,pyramid,reference,other,root,other,other,root/'output'),projection

    def test_build_fresh_replay_and_cache_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,projection=self.fixture(Path(tmp))
            with patch.object(evidence.parent,'build',side_effect=lambda *a,**k:{**copy.deepcopy(projection),'directory':'synthetic-replay'}):
                r=evidence.build(*args);self.assertEqual(r,evidence.build(*args))
                self.assertTrue(r['parent_projection_fresh_replay_identical']);self.assertEqual(r['world_geometry_additions'],0)
                (Path(r['directory'])/'section-adjoining-evidence.json').write_text('{}')
                with self.assertRaises(ValueError):evidence.build(*args)

    def test_modified_lineage_and_parent_replay_are_rejected(self):
        for mode in ('lineage','replay'):
            with tempfile.TemporaryDirectory() as tmp:
                args,projection=self.fixture(Path(tmp))
                if mode=='lineage':args[3].write_text('{}')
                with patch.object(evidence.parent,'build',return_value={'directory':'changed'}),self.assertRaises(ValueError):evidence.build(*args)

    def test_early_and_late_exhaustion_withhold_all_partial_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,projection=self.fixture(Path(tmp))
            with patch.object(evidence.parent,'build') as replay:
                r=evidence.build(*args,max_checks=1);self.assertEqual(replay.call_count,0)
            self.assertEqual(r['status'],'section_adjoining_budget_withheld')
            with patch.object(evidence.parent,'build',side_effect=lambda *a,**k:{**copy.deepcopy(projection),'directory':'synthetic-replay'}),patch.object(kernel,'summarize',side_effect=OverflowError('late')):
                r=evidence.build(*args)
            self.assertEqual(r['status'],'section_adjoining_budget_withheld')
            self.assertTrue(all(r[key]==[] for key in ('plan_ridges','original_plan_witnesses','source_horizontal_lines','source_line_pixel_checks','projection_ridge_checks','conditional_face_constraints')))

    def test_input_changed_during_build_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,projection=self.fixture(Path(tmp))
            def change(*a,**k):args[0].write_text('{}');return {**projection,'directory':'synthetic-replay'}
            with patch.object(evidence.parent,'build',side_effect=change),self.assertRaises(ValueError):evidence.build(*args)

    def test_invalid_work_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,_=self.fixture(Path(tmp))
            for limit in (True,0,2000001):
                with self.assertRaises(ValueError):evidence.build(*args,max_checks=limit)
