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

from voxel_mapper import section_roof_projection as projection
from voxel_mapper import section_projection_evidence as evidence
from voxel_mapper.pyramidal_roof_topology import discover
from voxel_mapper.reconstruction_evidence_queue import digest


class SectionProjectionTests(unittest.TestCase):
    def candidate(self,rectangle=False):
        return {'id':'plan','source_corners_pdf_native':[[-50,-50],[50,-50],[50,150 if rectangle else 50],[-50,150 if rectangle else 50]],
                'source_apex_pdf_native':[0,50 if rectangle else 0],
                'source_perimeter_ids_per_edge':[['cap'],['right'],['far'],['left']]}

    def group(self):
        # Unit camera derived independently from two known orthogonal components.
        u=np.array([.2,math.sqrt(.96)]);corners=np.array(self.candidate()['source_corners_pdf_native']);xs=200+corners@u
        return {'id':'source','status':'original_three_spoke_whole_base_candidate','source_apex_pdf_unrotated':[200,80],
                'nominal_metres_per_pdf_point':.1,'source_roof_spokes':[
                    {'source_base_vertex_pdf_unrotated':[float(xs[i]),130],'whole_source_spoke_ids':['s'+str(i)]} for i in (0,3,2)]}

    def page(self):
        group=self.group();apex=group['source_apex_pdf_unrotated'];points=[s['source_base_vertex_pdf_unrotated'] for s in group['source_roof_spokes']]
        def line(id,a,b):return {'id':id,'source_endpoints_pdf_unrotated':[a,b]}
        lines=[line('shaft',[200,20],apex),line('head1',[196,76],apex),line('head2',apex,[204,76]),line('base',points[0],points[2])]
        lines += [line('s'+str(i),apex,p) for i,p in enumerate(points)]
        def pair(id,a,b,closed):return {'id':id,'status':'closed_original_section_triangle_candidate' if closed else 'section_roof_boundary_or_visibility_held',
            'source_apex_pdf_unrotated':apex,'source_slope_far_endpoints':[points[a],points[b]],'slope_source_ids':['s'+str(a),'s'+str(b)],'cap_source_ids':['base'] if closed else []}
        return {'document_sha256':'a'*64,'page':1,'nominal_metres_per_pdf_point_candidate':.1,'source_lines':lines,
                'line_pixel_checks':[{'line_id':r['id'],'all_samples_supported':True} for r in lines],
                'leaders':[{'id':'leader','leader_source_id':'shaft','source_arrow_head_pairs':[['head1','head2']],
                            'roof_pairs':[pair('outer',0,2,True),pair('inner',1,2,False)]}]}

    def fixture(self,root):
        folder=root/'sources';folder.mkdir();pdf=root/'plan.pdf'
        corners=[[100,100],[200,100],[200,200],[100,200]];apex=[150,150];lines=[]
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400)
            for a,b in [(corners[i],corners[(i+1)%4]) for i in range(4)]+[(apex,p) for p in corners]:
                page.draw_line((a[0],400-a[1]),(b[0],400-b[1]));lines.append({'source_component_id':digest([a,b]),'source_endpoints_pdf_native':[a,b]})
            pdf.write_bytes(doc.tobytes())
        sha=hashlib.sha256(pdf.read_bytes()).hexdigest();graph=discover({'view_id':'v','document_sha256':sha,'page':1,'nominal_metres_per_pdf_point':.1,'lines':lines},lambda:None)
        c=graph['candidates'][0];cap=c['source_perimeter_ids_per_edge'][0][0]
        pyramid=root/'pyramid.json';pyramid.write_text(json.dumps({'status':'conditional_pyramidal_roof_evidence_only','plan_graphs':[graph],
            'source_junctions':[{'pyramid_candidate_id':c['id'],'shared_original_cap_source_id':cap}]}))
        fascia=root/'fascia.json';fascia.write_text(json.dumps({'contract':{'source_pyramid_sha256':hashlib.sha256(pyramid.read_bytes()).hexdigest()}}))
        with pymupdf.open() as doc:doc.new_page(width=400,height=400);raw=doc.tobytes()
        source_sha=hashlib.sha256(raw).hexdigest();(folder/(source_sha+'.pdf')).write_bytes(raw)
        record=self.page();record['document_sha256']=source_sha
        section={'status':'section_roof_source_diagnostics_only','pages':[record],'contract':{'source_fascia_sha256':hashlib.sha256(fascia.read_bytes()).hexdigest(),'max_checks':2000000,'level_text':'191.5'}}
        section_path=root/'section.json';section_path.write_text(json.dumps(section));catalogue=root/'catalogue.json';catalogue.write_text('{}')
        return (section_path,pyramid,catalogue,folder,fascia,pdf,root/'output'),section

    def replay(self,section):return patch.object(evidence.section_roof_evidence,'build',side_effect=lambda *a,**k:{**copy.deepcopy(section),'directory':'synthetic-parent-replay'})

    def test_three_spokes_keep_the_whole_base_and_previous_outline_hold(self):
        page=self.page();before=copy.deepcopy(page);groups=projection.spoke_groups(page,lambda:None)
        self.assertEqual(groups[0]['status'],'original_three_spoke_whole_base_candidate');self.assertEqual(len(groups[0]['source_roof_spokes']),3)
        self.assertFalse(groups[0]['original_closed_base_split']);self.assertEqual(page,before)

    def test_missing_closed_base_keeps_group_held(self):
        page=self.page();page['leaders'][0]['roof_pairs'][0]['status']='section_roof_boundary_or_visibility_held'
        self.assertEqual(projection.spoke_groups(page,lambda:None)[0]['status'],'section_three_spoke_group_held')

    def test_missing_inner_spoke_does_not_create_a_corner(self):
        page=self.page();page['leaders'][0]['roof_pairs'].pop()
        self.assertEqual(projection.spoke_groups(page,lambda:None)[0]['status'],'section_three_spoke_group_held')

    def test_extra_base_intersections_remain_ambiguous(self):
        page=self.page();p=copy.deepcopy(page['leaders'][0]['roof_pairs'][1]);p['slope_source_ids']=['extra','s2'];page['leaders'][0]['roof_pairs'].append(p)
        page['source_lines'].append({'id':'extra','source_endpoints_pdf_unrotated':[[200,80],[190,130]]});page['line_pixel_checks'].append({'line_id':'extra','all_samples_supported':True})
        self.assertEqual(projection.spoke_groups(page,lambda:None)[0]['status'],'section_three_spoke_group_held')

    def test_missing_pixel_support_never_becomes_projection_support(self):
        page=self.page();page['line_pixel_checks'][-1]['all_samples_supported']=False
        self.assertEqual(projection.spoke_groups(page,lambda:None)[0]['status'],'section_three_spoke_group_held')

    def test_all_eight_symmetries_are_retained_without_residual_ranking(self):
        group=self.group();candidate=self.candidate();before=copy.deepcopy((group,candidate));rows=projection.projections(group,candidate,.1,'cap',lambda:None)
        self.assertEqual(len(rows),8);self.assertTrue(all(r['status']=='conditional_source_projection_supported' for r in rows))
        self.assertEqual((group,candidate),before);self.assertEqual(len({tuple(r['source_left_middle_right_plan_corner_indices']) for r in rows}),8)

    def test_four_shared_cap_visible_and_four_hidden_hypotheses_are_preserved(self):
        rows=projection.projections(self.group(),self.candidate(),.1,'cap',lambda:None)
        self.assertEqual(sum(r['shared_cap_candidate_visible'] for r in rows),4)
        self.assertTrue(all(len(r['candidate_visible_original_edge_indices'])==2 for r in rows))
        self.assertTrue(all(not r['physical_face_assignment_verified'] and not r['wall_closure_authorized'] for r in rows))

    def test_unit_camera_predictions_preserve_original_apex_anchor(self):
        group=self.group();rows=projection.projections(group,self.candidate(),.1,'cap',lambda:None)
        for r in rows:
            self.assertAlmostEqual(np.linalg.norm(r['unit_projection_horizontal_vector']),1)
            self.assertEqual(r['source_apex_anchor_pdf_unrotated'],group['source_apex_pdf_unrotated'])
            self.assertLess(r['maximum_source_station_residual_pdf_points'],1e-10)

    def test_wrong_source_scale_is_not_fitted_away(self):
        group=self.group();group['nominal_metres_per_pdf_point']=.2
        rows=projection.projections(group,self.candidate(),.1,'cap',lambda:None)
        self.assertEqual(len(rows),8);self.assertTrue(all(r['status']=='section_projection_held' for r in rows))

    def test_rotating_original_plan_changes_camera_but_not_support(self):
        c=self.candidate();c['source_corners_pdf_native']=[[-p[1],p[0]] for p in c['source_corners_pdf_native']]
        rows=projection.projections(self.group(),c,.1,'cap',lambda:None)
        self.assertTrue(all(r['status']=='conditional_source_projection_supported' for r in rows))

    def test_clockwise_plan_winding_keeps_outward_face_visibility(self):
        c=self.candidate();c['source_corners_pdf_native']=list(reversed(c['source_corners_pdf_native']))
        rows=projection.projections(self.group(),c,.1,'cap',lambda:None)
        self.assertTrue(all(r['status']=='conditional_source_projection_supported' for r in rows));self.assertTrue(all(len(r['candidate_visible_original_edge_indices'])==2 for r in rows))

    def test_rectangular_plan_keeps_both_supported_and_failed_orders(self):
        rows=projection.projections(self.group(),self.candidate(rectangle=True),.1,'cap',lambda:None)
        self.assertEqual(len(rows),8);self.assertTrue(any(r['status']=='section_projection_held' for r in rows))

    def test_bad_geometry_scale_and_missing_cap_role_are_rejected(self):
        for mode in ('scale','cap','geometry'):
            c=self.candidate();unit=.1;cap='cap'
            if mode=='scale':unit=float('nan')
            elif mode=='cap':cap='missing'
            else:c['source_corners_pdf_native'][1][0]+=3
            with self.assertRaises(ValueError):projection.projections(self.group(),c,unit,cap,lambda:None)

    def test_ambiguity_gate_never_selects_a_lowest_residual_pose(self):
        group=self.group();rows=projection.projections(group,self.candidate(),.1,'cap',lambda:None);summary=projection.ambiguity([group],rows)[0]
        self.assertEqual(summary['supported_projection_count'],8);self.assertEqual(summary['shared_cap_visible_candidates'],4)
        self.assertFalse(summary['best_residual_candidate_selected']);self.assertFalse(summary['wall_closure_authorized'])

    def test_complete_build_replays_parent_and_original_plan_with_clean_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,section=self.fixture(Path(tmp));before=args[0].read_bytes()
            with self.replay(section):r=evidence.build(*args);again=evidence.build(*args)
            self.assertEqual(r,again);self.assertEqual(args[0].read_bytes(),before)
            self.assertEqual(r['counts']['original_plan_line_witnesses'],8);self.assertEqual(r['counts']['projection_candidates'],8)
            self.assertEqual(r['world_geometry_additions'],0)

    def test_changed_parent_lineage_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,section=self.fixture(Path(tmp));args[4].write_text('{}')
            with self.assertRaises(ValueError):evidence.build(*args)

    def test_changed_original_plan_or_saved_cache_is_rejected(self):
        for mode in ('plan','cache'):
            with tempfile.TemporaryDirectory() as tmp:
                args,section=self.fixture(Path(tmp))
                with self.replay(section):
                    if mode=='plan':args[5].write_bytes(b'changed')
                    else:r=evidence.build(*args);(Path(r['directory'])/'section-projection-evidence.json').write_text('{}')
                    with self.assertRaises((ValueError,pymupdf.FileDataError)):evidence.build(*args)

    def test_work_exhaustion_before_parent_and_after_geometry_clears_partial_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,section=self.fixture(Path(tmp))
            with self.replay(section) as parent:
                r=evidence.build(*args,max_checks=1);self.assertEqual(parent.call_count,0)
            self.assertEqual(r['status'],'section_projection_budget_withheld')
            with self.replay(section),patch.object(evidence.section_roof_projection,'ambiguity',side_effect=OverflowError('late')):r=evidence.build(*args)
            self.assertEqual(r['source_groups'],[]);self.assertEqual(r['projection_candidates'],[]);self.assertEqual(r['plan_source_witnesses'],[])

    def test_source_changed_during_projection_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,section=self.fixture(Path(tmp));original=projection.projections
            def changed(*values):r=original(*values);args[0].write_text('{}');return r
            with self.replay(section),patch.object(projection,'projections',side_effect=changed),self.assertRaises(ValueError):evidence.build(*args)

    def test_invalid_work_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,section=self.fixture(Path(tmp))
            for limit in (True,0,100001):
                with self.assertRaises(ValueError):evidence.build(*args,max_checks=limit)
