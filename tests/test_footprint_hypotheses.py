import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box,mapping,shape,Polygon
from voxel_mapper.footprint_hypotheses import propose,prepare,preview_surface,VERSION
from tests import test_building_plan_audit as fixture_module


class FootprintHypothesisTests(unittest.TestCase):
    def test_numerical_preview_slivers_are_bounded_and_source_holes_remain(self):
        polygon=Polygon([(0,0),(1e-12,1e-12),(100,0),(100,100),(0,100)],
            holes=[[(40,40),(50,40),(50,50),(40,50)]])
        before=polygon.wkb;geometry,review=preview_surface(polygon,.035)
        mesh=geometry['mesh'];area=sum(Polygon([(mesh['vertices'][i][0],mesh['vertices'][i][1]) for i in t]).area
            for t in mesh['triangles'])
        self.assertAlmostEqual(area+review['omitted_area_m2'],polygon.area*.035**2,places=10)
        self.assertLessEqual(review['omitted_area_m2'],review['maximum_omitted_area_m2'])
        self.assertEqual(polygon.wkb,before);self.assertFalse(review['source_polygon_modified'])

    def inputs(self):
        common={'document_sha256':'a'*64,'page':1,'coordinate_frame':'unrotated_mupdf_points_y_down'}
        fills=[{**common,'id':'left','geometry':mapping(box(10,10,15,100)),'fill_color':[.5,.5,.5]},
            {**common,'id':'right','geometry':mapping(box(100,10,105,100)),'fill_color':[.5,.5,.5]}]
        edges=[{**common,'id':'bottom','points':[[15,100],[100,100]]}]
        gap={'id':'top','parent_fill_candidate_ids':['left','right'],
            'source_endcaps':[{'fill_candidate_id':'left','source_endpoints':[[10,10],[15,10]]},
                             {'fill_candidate_id':'right','source_endpoints':[[100,10],[105,10]]}],
            'gap_corridor_geometry':mapping(box(10,10,105,10+5))}
        # Caps lie at each strip's top-facing end, preserving all four corners.
        gap['source_endcaps']=[{'fill_candidate_id':'left','source_endpoints':[[15,10],[15,15]]},
            {'fill_candidate_id':'right','source_endpoints':[[100,10],[100,15]]}]
        gap['gap_corridor_geometry']=mapping(box(15,10,100,15))
        return edges,fills,[gap]

    def test_explicit_corridor_closes_a_source_supported_hypothesis_without_moving_geometry(self):
        edges,fills,gaps=self.inputs();before=copy.deepcopy((edges,fills,gaps))
        r=propose(edges,fills,gaps,[50,50],[0,0,120,120])
        self.assertEqual(r['status'],'mixed_source_enclosure_hypotheses_only')
        self.assertFalse(r['baseline_candidate_ids']);self.assertTrue(r['candidates'])
        self.assertTrue(all(c['boundary_gap_ids']==['top'] for c in r['candidates']))
        self.assertEqual(r['gap_effects'][0]['single_gap_effect'],'creates_named_enclosure')
        self.assertEqual((edges,fills,gaps),before);self.assertIsNone(r['selected_physical_footprint_id'])
        self.assertTrue(all(c['physical_opening_count'] is None for c in r['candidates']))

    def test_source_only_fill_and_stroke_enclosure_and_holes_are_not_repaired(self):
        edges,fills,gaps=self.inputs();edges.append({**edges[0],'id':'top-source','points':[[15,15],[100,15]]})
        fills.append({**fills[0],'id':'void','geometry':mapping(box(40,40,50,50))})
        r=propose(edges,fills,[],[60,60],[0,0,120,120])
        self.assertEqual(len(r['baseline_candidate_ids']),1)
        candidate=r['candidates'][0];self.assertEqual(candidate['interior_ring_candidates'],1)
        self.assertEqual(candidate['boundary_gap_ids'],[])
        self.assertEqual(candidate['status'],'source_only_mixed_enclosure_candidate')
        self.assertEqual(shape(candidate['geometry']).area,7125)

    def test_competing_subdivisions_retained_and_budgets_discard_everything(self):
        edges,fills,gaps=self.inputs();edges.append({**edges[0],'id':'top-source','points':[[15,10],[100,10]]})
        r=propose(edges,fills,gaps,[50,50],[0,0,120,120])
        self.assertEqual(r['gap_effects'][0]['single_gap_effect'],'changes_existing_named_enclosure')
        self.assertGreater(len(r['candidates']),1)
        for options in ({'max_trials':1},{'max_checks':1},{'max_segments':1},{'max_provenance_links':1}):
            r=propose(edges,fills,gaps,[50,50],[0,0,120,120],options=options)
            self.assertEqual(r['status'],'hypothesis_budget_withheld');self.assertEqual(r['candidates'],[])
        broken=copy.deepcopy(gaps);broken[0]['gap_corridor_geometry']=mapping(box(15,11,100,15))
        with self.assertRaises(ValueError):propose(edges,fills,broken,[50,50],[0,0,120,120])

    def test_cli_recomputes_originals_and_publishes_source_only_preview_without_labels(self):
        from voxel_mapper.building_pipeline import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audit=fixture_module.PlanAuditTests().sources(root);config={'version':VERSION,'plan_audit':audit}
            (root/'config.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()):main(['propose-footprint','--config',str(root/'config.json'),'--output',str(root/'out')])
            report=json.loads((root/'out/report.json').read_text())
            self.assertEqual(len(report['baseline_previews']),1)
            self.assertEqual(report['complete_building_specs_generated'],0)
            self.assertEqual((root/'out/baseline-preview-0000/model.glb').read_bytes()[:4],b'glTF')
            self.assertIsNone(json.loads((root/'out/review-queue.json').read_text())['outcome'])
            again=prepare(config,lambda p:root/p,root/'again');self.assertEqual(report,again)
            with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'out')
            import hashlib,pymupdf
            with pymupdf.open(root/'reference.pdf') as doc:
                doc[0].insert_text((40,320),'1 : 200',fontsize=10);data=doc.tobytes()
            (root/'reference.pdf').write_bytes(data)
            config['plan_audit']['reference_sheet']['sha256']=hashlib.sha256(data).hexdigest()
            prepare(config,lambda p:root/p,root/'conflicting-scale')
            hypotheses=json.loads((root/'conflicting-scale/hypotheses.json').read_text())
            self.assertTrue(all(c['dimension_review']['inverse_layout_extent_candidates_m'] is None
                for c in hypotheses['candidates']))

    def test_changed_original_never_publishes_staged_hypotheses(self):
        import voxel_mapper.footprint_hypotheses as module
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audit=fixture_module.PlanAuditTests().sources(root);config={'version':VERSION,'plan_audit':audit}
            original=module.propose
            def mutate(*args,**kwargs):
                result=original(*args,**kwargs);(root/'plan.pdf').write_bytes(b'changed');return result
            with patch('voxel_mapper.footprint_hypotheses.propose',side_effect=mutate):
                with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'out')
            self.assertFalse((root/'out').exists())


if __name__=='__main__':unittest.main()
