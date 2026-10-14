import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from shapely.geometry import box,mapping,Polygon
from voxel_mapper.plan_elevation_correspondence import marker_frames,compare,prepare,VERSION
from tests import test_building_plan_audit as fixtures


class CorrespondenceTests(unittest.TestCase):
    def evidence(self):
        key=['2967',26,1]
        candidate={'id':'plan','geometry_pdf_native':mapping(box(0,0,100,100)),'boundary_gap_ids':['gap']}
        marker={'target_view_key_candidate':key,'center_pdf_native':[110,50],'corner_center_pdf_native':[105,50]}
        region={'id':'wall','view_key_candidate':list(key),'display_geometry':mapping(box(0,0,100,80)),
            'nominal_metres_per_pdf_point_candidate':.1,'component_class_candidate':'wall_face','material_number':2,
            'unrotated_mupdf_to_pdf_native_matrix':[1,0,0,-1,0,100],
            'unrotated_mupdf_to_display_matrix':[1,0,0,1,0,0]}
        openings=[{'view_key_candidate':list(key),'scan':{'status':'jamb_head_correspondence_candidates_only',
            'candidates':[{'id':'opening','geometry':mapping(box(40,50,60,70))}]}}]
        gaps=[{'id':'gap','projected_gap_endpoints':[[100,60],[100,40]]}]
        return candidate,[marker],[region],openings,gaps

    def run_evidence(self,values,**kwargs):
        return compare(*values,pymupdf.Matrix(1,0,0,-1,0,100),.1,None,**kwargs)

    def test_specific_view_width_and_opening_position_matches_preserve_both_orientations(self):
        values=self.evidence();before=copy.deepcopy(values);r=self.run_evidence(values)
        view=r['views'][0];self.assertEqual(view['region_width_comparisons'][0]['plan_minus_region_width_m'],0)
        self.assertEqual(len(view['opening_position_matches']),2)
        self.assertEqual({m['elevation_x_reversed'] for m in view['opening_position_matches']},{True,False})
        self.assertFalse(r['selected_physical_footprint']);self.assertEqual(values,before)

    def test_width_alone_wrong_view_or_missing_scan_cannot_match_an_opening(self):
        values=self.evidence();values[3][0]['scan']['candidates'][0]['geometry']=mapping(box(70,50,90,70))
        self.assertEqual(self.run_evidence(values)['views'][0]['opening_position_matches'],[])
        values=self.evidence();values[2][0]['view_key_candidate'][-1]=2
        self.assertEqual(self.run_evidence(values)['views'][0]['region_width_comparisons'],[])
        values=self.evidence();values[3][0]['scan']={'status':'scan_budget_withheld','candidates':[]}
        view=self.run_evidence(values)['views'][0]
        self.assertEqual(view['opening_scan_status'],'scan_budget_withheld');self.assertEqual(view['opening_position_matches'],[])

    def test_all_facing_ray_hits_retained_instead_of_nearest_wall_choice(self):
        polygon=Polygon([(0,0),(100,0),(100,100),(80,100),(80,20),(20,20),(20,100),(0,100)])
        marker=self.evidence()[1][0];r=marker_frames(polygon,marker,.1)
        self.assertEqual(len(r['frames']),2)
        inside={**marker,'center_pdf_native':[90,50]}
        self.assertEqual(marker_frames(polygon,inside,.1)['status'],'withheld_marker_inside_enclosure')

    def test_voids_remain_unclassified_and_work_budget_discards_partial_views(self):
        values=self.evidence();values[0]['geometry_pdf_native']=mapping(Polygon([(0,0),(100,0),(100,100),(0,100)],
            holes=[[(20,20),(30,20),(30,30),(20,30)]]))
        r=self.run_evidence(values);self.assertEqual(r['voids'][0]['role'],'unclassified_drafting_void')
        r=self.run_evidence(values,options={'max_checks':1})
        self.assertEqual(r['status'],'correspondence_budget_withheld');self.assertEqual(r['views'],[])

    def test_inner_paint_edge_attribution_is_source_topology_not_wall_acceptance(self):
        values=self.evidence();paint={'id':'paint','geometry':mapping(box(100.05,0,102.05,100)),
            'fill_color':[.5,.5,.5],'clip_references':[]}
        before=copy.deepcopy(paint)
        r=compare(*values,pymupdf.Matrix(1,0,0,-1,0,100),.1,None,paint_fills=[paint])
        witness=r['views'][0]['source_paint_boundary_witnesses'][0]
        self.assertEqual(witness['ray_hit_sidedness'][0]['attribution'],'inner_edge_of_source_paint')
        self.assertFalse(witness['ray_hit_sidedness'][0]['exact_boundary_coincidence'])
        self.assertFalse(witness['physical_wall_role_verified']);self.assertEqual(paint,before)

    def fake_facade(self,plan,*,mutate=False):
        def stage(config,resolve,output):
            root=Path(output)/'building-0000';(root/'faces').mkdir(parents=True)
            region=self.evidence()[2][0];region['id']='source-region'
            (root/'regions.json').write_text(json.dumps({'regions':[region]}))
            (root/'opening-candidates.json').write_text(json.dumps({'views':[]}))
            marker={'status':'unverified_native_view_reference_candidate','target_view_key_candidate':['2967',26,1],
                'circle_bbox_page_points':[390,580,410,600],'corner_fill_bbox_page_points':[380,580,390,600],
                'circle_path_index':0,'corner_fill_path_index':1}
            row={'document_sha256':plan['sha256'],'page':1,'plan_references':{'references':[marker]}}
            (root/'faces/drawing-view-pages.jsonl').write_text(json.dumps(row)+'\n')
            if mutate:Path(resolve(plan['path'])).write_bytes(b'changed')
            return {'buildings':[{'status':'awaiting_facade_interpretation'}]}
        return stage

    def test_cli_staging_source_binding_and_replay(self):
        from voxel_mapper.building_pipeline import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audit=fixtures.PlanAuditTests().sources(root)
            config={'version':VERSION,'footprint':{'version':'source-footprint-hypotheses-v1','plan_audit':audit},
                'facades':{'buildings':[{'building_id':'shop','sources':[audit['plan']]}]}}
            (root/'config.json').write_text(json.dumps(config))
            with patch('voxel_mapper.plan_elevation_correspondence.building_facade_feed.prepare',side_effect=self.fake_facade(audit['plan'])):
                with redirect_stdout(StringIO()):main(['compare-plan-views','--config',str(root/'config.json'),'--output',str(root/'out')])
                again=prepare(config,lambda p:root/p,root/'again')
            report=json.loads((root/'out/report.json').read_text());self.assertEqual(report,again)
            self.assertEqual(report['candidate_reports'],1);self.assertEqual(report['complete_building_specs_generated'],0)
            self.assertIsNone(json.loads((root/'out/review-queue.json').read_text())['outcome'])
            with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'out')
            with patch('voxel_mapper.plan_elevation_correspondence.building_facade_feed.prepare',side_effect=self.fake_facade(audit['plan'],mutate=True)):
                with self.assertRaises((ValueError,RuntimeError)):prepare(config,lambda p:root/p,root/'mutated')
            self.assertFalse((root/'mutated').exists())


if __name__=='__main__':unittest.main()
