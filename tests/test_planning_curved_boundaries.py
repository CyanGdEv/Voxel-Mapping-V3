"""Original curve witnesses, approximation envelopes and non-promotion guards."""
from concurrent.futures import CancelledError
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import shape

from voxel_mapper import drawing_geometry, ordinary_surfaces, planning_area_pilot
from voxel_mapper import planning_outline_semantics
from voxel_mapper import planning_curved_boundaries as curves
from voxel_mapper.building_spec import digest


class CurvedBoundaryTests(unittest.TestCase):
    def source(self):
        doc=pymupdf.open();self.addCleanup(doc.close)
        return doc,doc.new_page(width=600,height=500)

    def inventory(self,doc,page,**kwargs):
        sha=hashlib.sha256(doc.tobytes(no_new_id=True)).hexdigest()
        return curves.page_inventory(page,sha,1,**kwargs)

    def test_closed_source_curve_keeps_original_controls_and_never_becomes_a_surface(self):
        doc,p=self.source();p.draw_circle((180,180),60);p.insert_text((160,180),'Path',fontsize=8)
        before=doc.tobytes(no_new_id=True);r=self.inventory(doc,p)
        self.assertTrue(r['analysis_complete']);self.assertEqual(len(r['records']),1)
        row=r['records'][0];w=row['source_paint_witnesses'][0]
        self.assertEqual(w['ordinal'],0);self.assertEqual(w['paint_type'],'s')
        self.assertEqual(len(w['operators_pdf_native']),4)
        self.assertTrue(all(o['operator']=='c' for o in w['operators_pdf_native']))
        self.assertEqual(w['operators_pdf_native'][0]['points'][0],[120,320])
        self.assertLessEqual(row['curve_approximation']['chord_error_bound_pdf_points'],.05)
        self.assertEqual(row['source_paint_witnesses_sha256'],digest(row['source_paint_witnesses']))
        self.assertEqual(row['source_record_sha256'],digest(row['candidate']))
        self.assertFalse(row['world_placement_eligible']);self.assertFalse(r['topology_against_exact_curves_verified'])
        self.assertEqual(r['world_geometry_additions'],0);self.assertEqual(r['training_labels_generated'],0)
        self.assertEqual(ordinary_surfaces.page_candidates(p,r['document_sha256'],1)[0],[])
        with self.assertRaises(ValueError):
            planning_outline_semantics.page_candidates(p,r['document_sha256'],1,r)
        self.assertEqual(doc.tobytes(no_new_id=True),before)

    def test_even_odd_hole_and_native_fill_rule_remain_in_the_same_record(self):
        doc,p=self.source();s=p.new_shape();s.draw_circle((200,200),80);s.draw_circle((200,200),25)
        s.finish(fill=(.6,.6,.6),color=None,even_odd=True);s.commit()
        r=self.inventory(doc,p);self.assertEqual(len(r['records']),1)
        row=r['records'][0];self.assertEqual(row['native_metrics']['hole_count'],1)
        self.assertEqual(len(shape(row['candidate']['geometry']).interiors),1)
        self.assertEqual(row['source_paint_witnesses'][0]['fill_rule'],'even_odd')
        self.assertEqual(len(row['source_paint_witnesses'][0]['operators_pdf_native']),8)

    def test_open_curve_cannot_be_closed_or_joined_to_nearby_linework(self):
        doc,p=self.source();p.draw_bezier((100,100),(100,200),(200,200),(200,100))
        p.draw_line((200,100),(100,100))
        r=self.inventory(doc,p);self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])
        self.assertEqual(r['extraction']['rejections']['open_or_multipart_curve_requires_interpretation'],1)

    def test_later_cover_uses_curve_error_envelope_and_nonopaque_white_fills_are_excluded(self):
        doc,p=self.source();p.draw_circle((180,180),60)
        p.draw_rect((118,175,122,185),fill=(1,1,1),color=None)
        p.draw_circle((400,180),60,fill=(1,1,1),color=None)
        p.draw_circle((400,350),40,stroke_opacity=.5)
        r=self.inventory(doc,p);self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])
        self.assertEqual(r['covered_boundaries_withheld'],1);self.assertEqual(r['white_fills_withheld'],1)
        self.assertEqual(r['extraction']['rejections']['nonopaque_paint'],1)

    def test_all_original_aliases_retained_without_replacing_ordinal_with_filtered_index(self):
        doc,p=self.source();p.draw_rect((30,30,60,60));p.draw_circle((180,180),60)
        p.draw_circle((180,180),60,color=(.8,0,0))
        r=self.inventory(doc,p);self.assertEqual(len(r['records']),1)
        self.assertEqual([w['ordinal'] for w in r['records'][0]['source_paint_witnesses']],[1,2])

    def test_candidate_point_operator_control_and_output_caps_withhold_all_records(self):
        doc,p=self.source();p.draw_circle((180,180),60);p.draw_circle((400,180),60)
        for options in ({'max_candidates':1},{'max_points':5},{'max_source_operators':4},
                        {'max_source_control_points':16},{'max_output_bytes':16384}):
            with self.subTest(options=options):
                r=self.inventory(doc,p,options=options)
                self.assertFalse(r['analysis_complete']);self.assertEqual(r['records'],[])
                self.assertLessEqual(len(json.dumps(r).encode()),options.get('max_output_bytes',8000000))

    def test_rotation_crop_and_repeat_preserve_original_native_geometry(self):
        doc,p=self.source();p.draw_circle((180,180),60)
        p.set_cropbox(pymupdf.Rect(30,30,570,470));p.set_rotation(90)
        before=doc.tobytes(no_new_id=True);a=self.inventory(doc,p);b=self.inventory(doc,p)
        self.assertEqual(a,b);self.assertEqual(p.rotation,90)
        self.assertEqual(a['records'][0]['source_paint_witnesses'][0]['operators_pdf_native'][0]['points'][0],[120,320])
        self.assertEqual(doc.tobytes(no_new_id=True),before)

    def test_per_primitive_quota_rejection_withholds_the_entire_review(self):
        doc,p=self.source();p.draw_circle((180,180),60)
        extract=drawing_geometry.extract_page
        def small_primitive_budget(*args,**kwargs):
            return extract(*args,**kwargs,max_points=2)
        with patch.object(drawing_geometry,'extract_page',side_effect=small_primitive_budget):
            r=self.inventory(doc,p)
        self.assertFalse(r['analysis_complete']);self.assertEqual(r['records'],[])
        self.assertEqual(r['reason'],'complete_closed_curve_primitive_budgets_required')

    def test_clipped_curve_cannot_supply_complete_boundary(self):
        doc,p=self.source();p.draw_circle((180,180),60)
        contents=p.read_contents();xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
        doc.update_stream(xref,b'q 150 250 100 150 re W n\n'+contents+b'\nQ')
        doc.xref_set_key(p.xref,'Contents',f'{xref} 0 R')
        r=self.inventory(doc,p);self.assertTrue(r['analysis_complete']);self.assertEqual(r['records'],[])

    def test_original_curve_sample_points_stay_within_recorded_error(self):
        points=[(0,0),(80,120),(-40,120),(60,0)]
        line,bound=drawing_geometry.flatten_cubic(points,.05)
        from shapely.geometry import LineString,Point
        approximation=LineString(line)
        for index in range(1001):
            t=index/1000;u=1-t
            p=tuple(u**3*points[0][k]+3*u*u*t*points[1][k]+3*u*t*t*points[2][k]+t**3*points[3][k] for k in (0,1))
            self.assertLessEqual(approximation.distance(Point(p)),bound+1e-9)

    def test_tiny_internal_gap_is_not_snapped_by_curve_inventory(self):
        path={'items':[('c',(20,20),(40,40),(80,40),(100,20)),
                       ('l',(100.000005,20),(20,20))]}
        parts,_=drawing_geometry.subpaths(path,pymupdf.Matrix(1,1),
            {'max_points':10000,'curve_tolerance_points':.05,'closed_curved_primitives_only':True})
        self.assertEqual(len(parts),2)
        self.assertNotEqual(parts[0][-1],parts[1][0])

    def test_cover_between_chord_and_original_curve_is_withheld(self):
        from shapely.geometry import Point,box
        doc,p=self.source();p.draw_circle((180,180),60)
        r=self.inventory(doc,p);row=r['records'][0];boundary=shape(row['candidate']['geometry']).boundary
        controls=row['source_paint_witnesses'][0]['operators_pdf_native'][0]['points']
        candidates=[]
        for index in range(1,100):
            t=index/100;u=1-t
            q=tuple(u**3*controls[0][k]+3*u*u*t*controls[1][k]+3*u*t*t*controls[2][k]+t**3*controls[3][k] for k in (0,1))
            candidates.append((boundary.distance(Point(q)),q))
        distance,(x,y)=max(candidates);self.assertGreater(distance,.001)
        radius=distance/4;patch=box(x-radius,y-radius,x+radius,y+radius)
        self.assertFalse(boundary.intersects(patch))
        p.draw_rect((x-radius,500-y-radius,x+radius,500-y+radius),color=None,fill=(1,1,1))
        r=self.inventory(doc,p);self.assertEqual(r['records'],[])
        self.assertEqual(r['covered_boundaries_withheld'],1)

    def test_invalid_limits_sources_and_cancellation_reject_without_partial_evidence(self):
        doc,p=self.source();p.draw_circle((180,180),60)
        for options in ({'max_candidates':501},{'max_points':True},{'max_output_bytes':2},{'extra':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.inventory(doc,p,options=options)
        with self.assertRaises(ValueError):curves.page_inventory(p,'not-a-hash',1)
        with self.assertRaises(ValueError):curves.page_inventory(p,'a'*64,2)
        with self.assertRaises(CancelledError):self.inventory(doc,p,cancelled=lambda:True)
        for options in ({'closed_curved_primitives_only':1},
                        {'closed_curved_primitives_only':True,'source_face_primitives_only':True}):
            with self.assertRaises(ValueError):drawing_geometry.validated_options(options)

    def test_pilot_retains_review_overlay_and_excludes_curve_from_nominal_layout(self):
        doc,p=self.source();p.draw_circle((180,180),60);p.insert_text((160,180),'Path',fontsize=8)
        p.draw_rect((330,100,450,200));p.insert_text((345,155),'Building',fontsize=8)
        p.insert_text((50,400),'Site Plan Proposed | 1:100',fontsize=10)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);data=doc.tobytes();(root/'source.pdf').write_bytes(data)
            sha=hashlib.sha256(data).hexdigest()
            config={'version':planning_area_pilot.VERSION,'area_id':'curved-review',
                'application_references':['TEST'],'documents':[{'file':'source.pdf','sha256':sha,
                'title':'Synthetic curved source','role':'site-plan','drawing_state':'proposed','application_reference':'TEST'}]}
            report=planning_area_pilot.run(config,lambda name:root/name,root/'out')
            self.assertEqual(report['summary']['completed_pages'],1)
            page=report['pages'][0];self.assertEqual(page['curved_boundary_overlay']['records'],1)
            evidence=json.loads((root/'out'/page['evidence_file']).read_text())
            self.assertEqual(len(evidence['curved_boundary_review']['records']),1)
            self.assertEqual(evidence['area_layout']['summary']['nominal_area_path_plaza_candidates'],0)
            self.assertIn('planning_curved_boundaries',' '.join(report['contract']['implementations']))
            self.assertIn('Inspect closed curved source boundaries',(root/'out/review.html').read_text())
            for name,pin in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'out'/name).read_bytes()).hexdigest(),pin)


if __name__=='__main__':unittest.main()
