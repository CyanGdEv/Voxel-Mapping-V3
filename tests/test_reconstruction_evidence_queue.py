import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from voxel_mapper.reconstruction_evidence_queue import build, run


class EvidenceQueueTests(unittest.TestCase):
    def page(self):
        return {'document_sha256': 'a'*64, 'page': 1,
            'wall_perimeter_coverage': {'document_sha256': 'a'*64, 'page': 1,
                'status': 'source_region_perimeter_coverage_only', 'region_traces': [
                    {'face_id': 'room', 'source_face_sha256': 'b'*64, 'hole_count': 1,
                        'coverage_fraction': .25, 'segments': [
                            {'ring_index': 0, 'segment_index': 0, 'ring_role': 'exterior_ring',
                                'status': 'whole_source_segment_paired'},
                            {'ring_index': 1, 'segment_index': 0, 'ring_role': 'protected_hole_ring',
                                'status': 'no_paired_wall_support'}]}]}}

    def test_requirements_preserve_proof_holes_and_dependencies(self):
        page=self.page(); before=copy.deepcopy(page)
        queue=build('mutiny-bay',[page])
        self.assertEqual(len(queue['tasks']),6)
        by_kind={t['kind']:t for t in queue['tasks']}
        exterior=by_kind['physical_exterior']
        self.assertEqual(exterior['source_hole_count'],1)
        self.assertEqual(len(exterior['unpaired_source_segments']),1)
        self.assertEqual(exterior['unpaired_source_segments'][0]['ring_role'],'protected_hole_ring')
        self.assertEqual(exterior['depends_on'],[by_kind['view_scope']['id']])
        self.assertEqual(by_kind['relative_dimensions']['depends_on'],[by_kind['plan_elevation_correspondence']['id']])
        self.assertEqual(page,before)
        self.assertFalse(queue['geometry_export_authorized'])
        self.assertTrue(all(not t['geometry_export_authorized'] for t in queue['tasks']))

    def test_order_determinism_and_unique_source_identity(self):
        first=self.page();second=copy.deepcopy(first);second['page']=2;second['wall_perimeter_coverage']['page']=2
        self.assertEqual(build('mutiny-bay',[first,second]),build('mutiny-bay',[second,first]))
        with self.assertRaises(ValueError):build('mutiny-bay',[first,first])
        changed=copy.deepcopy(first);changed['wall_perimeter_coverage']['page']=4
        with self.assertRaises(ValueError):build('mutiny-bay',[changed])
        repeated=self.page()
        repeated['wall_perimeter_coverage']['region_traces']*=2
        with self.assertRaises(ValueError):build('mutiny-bay',[repeated])

    def test_new_evidence_changes_proof_without_renaming_requirement(self):
        page=self.page();old=build('mutiny-bay',[page])
        page['wall_perimeter_coverage']['region_traces'][0]['coverage_fraction']=.5
        new=build('mutiny-bay',[page])
        self.assertEqual([t['id'] for t in old['tasks']],[t['id'] for t in new['tasks']])
        self.assertNotEqual(old['source_pages'],new['source_pages'])
        old_exterior=next(t for t in old['tasks'] if t['kind']=='physical_exterior')
        new_exterior=next(t for t in new['tasks'] if t['kind']=='physical_exterior')
        self.assertNotEqual(old_exterior['proof'],new_exterior['proof'])
        self.assertFalse(new_exterior['geometry_export_authorized'])

    def test_budget_removes_all_partial_tasks(self):
        q=build('mutiny-bay',[self.page()],max_tasks=3)
        self.assertEqual(q['status'],'evidence_budget_withheld');self.assertEqual(q['tasks'],[])
        self.assertEqual(q['counts'],{})
        with self.assertRaises(ValueError):build('mutiny-bay',[],max_tasks=True)

    def setup_stream(self, root):
        source=root/'architecture';source.mkdir()
        data=(json.dumps(self.page())+'\n').encode()
        (source/'architectural-pages.jsonl').write_bytes(data)
        (source/'architectural-report.json').write_text(json.dumps({'output_sha256':hashlib.sha256(data).hexdigest()}))
        return source

    def test_resume_reuses_worklist_and_rejects_output_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.setup_stream(root);output=root/'queue'
            first=run('mutiny-bay',source,output);second=run('mutiny-bay',source,output)
            self.assertEqual(first['run_tasks'],6);self.assertEqual(second['run_tasks'],0)
            self.assertEqual(second['reused_tasks'],6);self.assertEqual(first['output_sha256'],second['output_sha256'])
            (output/'missing-evidence.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'output changed'):run('mutiny-bay',source,output)

    def test_source_changes_reject_and_partial_output_cannot_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.setup_stream(root);output=root/'queue'
            run('mutiny-bay',source,output)
            (source/'architectural-pages.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'evidence output changed'):run('mutiny-bay',source,output)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.setup_stream(root);output=root/'queue';output.mkdir()
            with self.assertRaises(FileNotFoundError):run('mutiny-bay',source,output)
