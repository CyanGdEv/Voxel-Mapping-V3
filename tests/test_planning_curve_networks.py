"""Original open Bézier chains, exact joins, exclusions and bounded failure."""
import copy
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import pymupdf
from shapely.geometry import shape

from voxel_mapper import drawing_geometry,ordinary_surfaces,planning_outline_semantics
from voxel_mapper import planning_surface_footprints,planning_curve_networks as networks
from voxel_mapper.building_spec import digest


class CurveNetworkTests(unittest.TestCase):
    def source(self,*,gap=0,dashes=None,hidden=False,rotation=0,hole=False,crossing=False):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=600,height=500)
        p.draw_bezier((100,100),(150,50),(250,50),(300,100),dashes=dashes)
        for a,b in (((300,100),(300,250)),((300,250),(100,250)),((100,250),(100,100+gap))):p.draw_line(a,b)
        if hole:
            for a,b in (((180,170),(220,170)),((220,170),(220,210)),((220,210),(180,210)),((180,210),(180,170))):p.draw_line(a,b)
        if crossing:p.draw_line((80,180),(320,180))
        p.insert_text((140,145),'Path',fontsize=8)
        if hidden:p.draw_rect((295,170,305,190),color=None,fill=(1,1,1))
        p.set_rotation(rotation)
        return d,p

    def analyze(self,d,p,**kwargs):
        sha=hashlib.sha256(d.tobytes(no_new_id=True)).hexdigest()
        _,_,r=ordinary_surfaces.page_candidates(p,sha,1);inv=r['source_outline_inventory']
        assoc=planning_outline_semantics.page_candidates(p,sha,1,inv)
        surfaces=planning_surface_footprints.page_candidates(p,sha,1,inv,assoc)
        result=networks.page_review(p,sha,1,surfaces,**kwargs)
        return result,surfaces

    def test_four_separately_painted_edges_recover_curved_source_face_with_all_originals(self):
        d,p=self.source();before=d.tobytes(no_new_id=True);r,s=self.analyze(d,p)
        self.assertTrue(r['analysis_complete'],r.get('reason'));self.assertEqual(s['candidates'],[])
        self.assertEqual(len(r['records']),1);row=r['records'][0];c=row['candidate']
        self.assertEqual(len(c['source_edges']),4);self.assertEqual(len(c['source_paint_witnesses']),4)
        self.assertEqual(sum(x['curve_approximation']['cubic_segments'] for x in c['source_edges']),1)
        self.assertTrue(any(w['operators_pdf_native'][0]['operator']=='c' for w in c['source_paint_witnesses']))
        self.assertGreater(shape(c['geometry']).area,30000)
        self.assertEqual(row['label_context'][0]['label']['text'],'Path')
        self.assertTrue(row['label_context'][0]['clear_of_curve_approximation'])
        self.assertFalse(row['label_context'][0]['semantic_role_inferred'])
        self.assertEqual(row['source_record_sha256'],digest(c));self.assertEqual(c['source_paint_witnesses_sha256'],digest(c['source_paint_witnesses']))
        self.assertFalse(r['endpoint_snapping_performed']);self.assertFalse(r['curve_interior_intersection_noding_performed'])
        self.assertFalse(row['world_placement_eligible']);self.assertEqual(r['world_geometry_additions'],0)
        self.assertEqual(d.tobytes(no_new_id=True),before)
        with self.assertRaises(ValueError):planning_outline_semantics.page_candidates(p,r['document_sha256'],1,r)

    def test_tiny_and_large_gaps_remain_open(self):
        for gap in (.0001,1):
            with self.subTest(gap=gap):
                d,p=self.source(gap=gap);r,_=self.analyze(d,p)
                self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])
                self.assertGreater(r['counts']['dangling_endpoint_nodes'],0)

    def test_dashed_or_hidden_edge_cannot_authorize_a_boundary(self):
        for kwargs in ({'dashes':'[2 2] 0'},{'hidden':True}):
            with self.subTest(kwargs=kwargs):
                d,p=self.source(**kwargs);r,_=self.analyze(d,p)
                self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])

    def test_original_inner_ring_is_retained_as_a_hole(self):
        d,p=self.source(hole=True);r,_=self.analyze(d,p)
        self.assertEqual(len(r['records']),1)
        self.assertEqual(r['records'][0]['native_metrics']['hole_count'],1)
        self.assertEqual(len(shape(r['records'][0]['candidate']['geometry']).interiors),1)
        self.assertEqual(len(r['records'][0]['candidate']['source_edges']),8)

    def test_interior_crossing_does_not_create_interpolated_curve_nodes(self):
        d,p=self.source(crossing=True);r,_=self.analyze(d,p)
        self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])
        self.assertGreater(r['counts'].get('interior_crossing_or_overlap_pairs',0)+
                           r['counts'].get('omitted_original_stroke_conflict_faces_withheld',0),0)
        self.assertFalse(r['curve_interior_intersection_noding_performed'])

    def test_no_closure_can_be_invented_between_distinct_source_regions(self):
        d,p=self.source();r,s=self.analyze(d,p)
        s=copy.deepcopy(s);s['extraction']['regions']=[{'region_native_points':[80,240,220,460]},
                                                     {'region_native_points':[180,240,320,460]}]
        r=networks.page_review(p,r['document_sha256'],1,s)
        self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])

    def test_source_gap_inside_one_paint_group_is_not_snapped(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=600,height=500)
        x=d.get_new_xref();d.update_object(x,'<<>>')
        d.update_stream(x,b'100 400 m 150 450 250 450 300 400 c 300 250 l 100 250 l 100 399.999995 l S')
        d.xref_set_key(p.xref,'Contents',f'{x} 0 R');p.insert_text((140,145),'Path',fontsize=8)
        r,_=self.analyze(d,p);self.assertEqual(r['records'],[])

    def test_compound_paint_subpaths_do_not_inherit_other_parts_curve_counts(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=600,height=500)
        x=d.get_new_xref();d.update_object(x,'<<>>')
        d.update_stream(x,b'100 400 m 150 450 250 450 300 400 c 100 200 m 300 200 l S')
        d.xref_set_key(p.xref,'Contents',f'{x} 0 R')
        rows,report=drawing_geometry.extract_page(p,'a'*64,1,open_stroked_primitives_only=True,
            isolate_open_stroked_subpaths=True,curve_tolerance_points=.05)
        self.assertEqual(report['candidates'],2)
        self.assertEqual(sorted(r['curve_approximation']['cubic_segments'] for r in rows),[0,1])
        straight=next(r for r in rows if not r['curve_approximation']['cubic_segments'])
        self.assertEqual(straight['curve_approximation']['chord_error_bound_pdf_points'],0)

    def test_candidate_point_segment_pair_provenance_and_output_caps_withhold_all(self):
        d,p=self.source()
        for opts in ({'max_native_candidates':1},{'max_native_points':3},{'max_segments':1},
                     {'max_pair_checks':1},{'max_face_provenance':1},{'max_source_operators':1},
                     {'max_source_control_points':1},{'max_output_bytes':16384}):
            with self.subTest(opts=opts):
                r,_=self.analyze(d,p,options=opts)
                self.assertFalse(r['analysis_complete'],opts);self.assertEqual(r['records'],[])
                self.assertLessEqual(len(json.dumps(r).encode()),opts.get('max_output_bytes',8000000))

    def test_repeated_and_rotated_originals_preserve_native_chain_and_source_bytes(self):
        d,p=self.source(rotation=90);before=d.tobytes(no_new_id=True)
        a,s=self.analyze(d,p);b=networks.page_review(p,a['document_sha256'],1,s)
        self.assertEqual(a,b);self.assertEqual(p.rotation,90)
        self.assertEqual(len(a['records']),1)
        self.assertEqual(d.tobytes(no_new_id=True),before)

    def test_invalid_options_source_and_cancellation_are_explicit(self):
        d,p=self.source();r,s=self.analyze(d,p)
        for opts in ({'max_faces':501},{'max_segments':True},{'extra':2},{'max_output_bytes':100}):
            with self.assertRaises(ValueError):networks.page_review(p,r['document_sha256'],1,s,options=opts)
        with self.assertRaises(ValueError):networks.page_review(p,'b'*64,1,s)
        with self.assertRaises(CancelledError):networks.page_review(p,r['document_sha256'],1,s,cancelled=lambda:True)
        for opts in ({'open_stroked_primitives_only':True,'source_face_primitives_only':True},
                     {'open_stroked_primitives_only':1}):
            with self.assertRaises(ValueError):drawing_geometry.validated_options(opts)

    def test_failed_scope_analysis_cannot_be_replaced_by_a_successful_subset(self):
        d,p=self.source();r,s=self.analyze(d,p);s=copy.deepcopy(s);s['analysis_complete']=False
        r=networks.page_review(p,r['document_sha256'],1,s)
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['records'],[])

    def test_curve_endpoints_on_original_straight_interiors_form_real_source_joints(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=600,height=500)
        p.draw_bezier((100,100),(150,50),(250,50),(300,100))
        p.draw_line((100,80),(100,250));p.draw_line((300,80),(300,250));p.draw_line((100,250),(300,250))
        p.insert_text((140,145),'Path',fontsize=8)
        r,_=self.analyze(d,p);self.assertEqual(len(r['records']),1)
        self.assertTrue(r['original_straight_intersection_noding_enabled'])
        self.assertFalse(r['curve_interior_intersection_noding_performed'])
        self.assertEqual(shape(r['records'][0]['candidate']['geometry']).bounds,(100,250,300,437.5))

    def test_straight_part_of_mixed_paint_can_node_without_noding_its_curve(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=600,height=500)
        s=p.new_shape();s.draw_bezier((100,100),(150,50),(250,50),(300,100));s.draw_line((300,100),(300,280))
        s.finish(closePath=False);s.commit()
        p.draw_line((100,250),(300,250));p.draw_line((100,250),(100,100));p.insert_text((140,145),'Path',fontsize=8)
        r,_=self.analyze(d,p);self.assertEqual(len(r['records']),1)
        mixed=[e for e in r['records'][0]['candidate']['source_edges'] if e['source_operator_reference']['ordinal']==0]
        self.assertEqual({e['source_operator_index'] for e in mixed},{0,1})
        self.assertEqual(sorted(e['curve_approximation']['cubic_segments'] for e in mixed),[0,1])

    def test_interior_curve_crossing_is_not_replaced_by_a_chord_intersection(self):
        d,p=self.source();p.draw_line((100,80),(300,80));r,_=self.analyze(d,p)
        self.assertEqual(r['records'],[])
        self.assertGreater(r['counts']['interior_crossing_or_overlap_pairs'],0)

    def test_crossing_omitted_by_scope_still_blocks_the_face(self):
        d,p=self.source(crossing=True);r,_=self.analyze(d,p)
        self.assertEqual(r['records'],[])
        self.assertGreater(r['counts']['omitted_original_stroke_conflict_faces_withheld'],0)
        self.assertGreater(r['extraction']['rejections']['complete_primitive_crosses_region_boundary'],0)

    def test_omitted_global_source_strokes_are_charged_to_source_work_caps(self):
        d,p=self.source();p.draw_rect((30,30,550,450));r,_=self.analyze(d,p,options={'max_source_operators':4})
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['records'],[])
        self.assertEqual(r['reason'],'open_curve_source_operator_budget_exceeded')

    def test_cancellation_during_original_stroke_processing_never_returns_a_partial_success(self):
        d,p=self.source();r,s=self.analyze(d,p);calls=0
        def cancelled():
            nonlocal calls
            calls+=1
            return calls>12
        with self.assertRaises(CancelledError):networks.page_review(p,r['document_sha256'],1,s,cancelled=cancelled)

    def test_open_diagnostics_preserve_original_controls_and_draw_no_closing_edge(self):
        from voxel_mapper import planning_area_pilot as pilot
        d,p=self.source(gap=1);r,_=self.analyze(d,p)
        self.assertEqual(r['records'],[]);self.assertEqual(len(r['curve_chain_diagnostics']),1)
        diagnostic=r['curve_chain_diagnostics'][0]
        self.assertEqual(diagnostic['operator_pdf_native']['operator'],'c')
        self.assertEqual(diagnostic['unresolved_endpoints_within_source_scope'],[True,False])
        self.assertEqual(diagnostic['geometry_pdf_native']['coordinates'][0],tuple(diagnostic['operator_pdf_native']['points'][0]))
        self.assertFalse(diagnostic['world_placement_eligible'])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);preview=pilot._preview(p,root/'original.png',600)
            result=networks.write_overlay(r,preview,root/'network.svg');self.assertEqual(result['diagnostic_curves'],1)
            tree=ET.parse(root/'network.svg')
            paths=tree.findall('{http://www.w3.org/2000/svg}path')
            self.assertEqual(len(paths),1);self.assertFalse(paths[0].attrib['d'].endswith('Z'))
            self.assertEqual(len(tree.findall('{http://www.w3.org/2000/svg}circle')),1)

    def test_sampled_diagnostics_do_not_claim_a_complete_source_curve_inventory(self):
        d=pymupdf.open();self.addCleanup(d.close);p=d.new_page(width=1800,height=1000)
        for i in range(129):
            x=30+i%18*90;y=50+i//18*90
            p.draw_bezier((x,y),(x+10,y+20),(x+30,y+20),(x+40,y))
        sha=hashlib.sha256(d.tobytes(no_new_id=True)).hexdigest()
        surfaces={'version':planning_surface_footprints.VERSION,'document_sha256':sha,'page':1,
            'coordinate_frame':'pdf_native_points_y_up','analysis_complete':True,'labels':[],
            'extraction':{'regions':[{'region_native_points':[0,0,1800,1000]}]}}
        r=networks.page_review(p,sha,1,surfaces)
        self.assertTrue(r['analysis_complete']);self.assertEqual(r['diagnostic_candidates'],129)
        self.assertTrue(r['diagnostics_sampled']);self.assertEqual(len(r['curve_chain_diagnostics']),128)
        self.assertEqual(r['records'],[])

    def test_pilot_exposes_network_review_without_adding_a_curved_path_to_the_layout(self):
        from voxel_mapper import planning_area_pilot as pilot
        d,p=self.source();p.draw_rect((400,100,500,200));p.insert_text((420,150),'Building',fontsize=8)
        p.insert_text((50,450),'Site Plan Proposed | 1:100',fontsize=10)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);data=d.tobytes();(root/'source.pdf').write_bytes(data)
            sha=hashlib.sha256(data).hexdigest()
            config={'version':pilot.VERSION,'area_id':'curve-network-review','application_references':['TEST'],
                'documents':[{'file':'source.pdf','sha256':sha,'title':'Synthetic source',
                'role':'site-plan','drawing_state':'proposed','application_reference':'TEST'}]}
            report=pilot.run(config,lambda name:root/name,root/'out');self.assertEqual(report['summary']['completed_pages'],1)
            page=report['pages'][0];self.assertEqual(page['curve_network_overlay']['assembled_records'],1)
            evidence=json.loads((root/'out'/page['evidence_file']).read_text())
            self.assertEqual(len(evidence['curve_network_review']['records']),1)
            self.assertEqual(evidence['area_layout']['summary']['nominal_area_path_plaza_candidates'],0)
            self.assertEqual(evidence['area_layout']['summary']['nominal_area_building_candidates'],1)
            self.assertIn('voxel_mapper.planning_curve_networks',report['contract']['implementations'])
            self.assertIn('Inspect open curved source networks',(root/'out/review.html').read_text())
            for name,pin in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'out'/name).read_bytes()).hexdigest(),pin)


if __name__=='__main__':unittest.main()
