import copy
from concurrent.futures import CancelledError
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pymupdf

from voxel_mapper import planning_area_pilot as pilot


def fixture(root, *, pages=1, role='floor-plan', name='source.pdf'):
    with pymupdf.open() as doc:
        for _ in range(pages):
            page=doc.new_page(width=600,height=500)
            page.draw_rect((30,30,190,140))
            page.insert_text((50,80),'Footpath',fontsize=10)
            page.insert_text((30,190),'Proposed Ground Floor Plan | 1:100',fontsize=10)
            page.insert_text((30,450),'Existing Front Elevation',fontsize=10)
        data=doc.tobytes()
    (root/name).write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    return {'version':pilot.VERSION,'area_id':'source-pilot','application_references':['APP/1'],
        'development_exposure':'previously_inspected',
        'documents':[{'file':name,'sha256':sha,'title':'Proposed plan',
            'role':role,'drawing_state':'proposed','application_reference':'APP/1'}]}


class PlanningPilotTests(unittest.TestCase):
    def test_frozen_module_loader_can_pin_code_without_source_files(self):
        with patch.object(pilot,'__file__','/absent/frozen-module.py'):
            receipt=pilot._implementation(pilot)
        self.assertEqual(receipt['basis'],'runtime_module_code_object')
        self.assertRegex(receipt['sha256'],'^[0-9a-f]{64}$')

    def test_optional_pinned_download_reuses_verification_and_never_replaces_bad_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);data=(root/'source.pdf').read_bytes()
            (root/'source.pdf').unlink();config['download_missing']=True
            config['documents'][0]['url']='https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=1'
            def download(item,target,cancelled):
                target.write_bytes(data)
                return [{'status':'checksum_verified','sha256':item['sha256']}]
            with patch('voxel_mapper.desktop_area._download',side_effect=download) as mocked:
                report=pilot.run(config,lambda p:root/p,root/'output')
            self.assertEqual(mocked.call_count,1)
            self.assertEqual(report['summary']['completed_pages'],1)
            self.assertEqual(report['documents'][0]['acquisition_attempts'][0]['status'],'checksum_verified')
            (root/'source.pdf').write_bytes(b'bad source')
            with patch('voxel_mapper.desktop_area._download',side_effect=AssertionError('Must not overwrite')):
                report=pilot.run(config,lambda p:root/p,root/'wrong')
            self.assertEqual(report['documents'][0]['status'],'source_withheld')
            self.assertEqual((root/'source.pdf').read_bytes(),b'bad source')

    def test_original_sources_without_view_recipes_produce_hash_bound_review_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);before=(root/'source.pdf').read_bytes()
            report=pilot.run(config,lambda p:root/p,root/'output')
            self.assertEqual(report['summary']['completed_pages'],1)
            self.assertEqual(report['summary']['visible_view_captions'],2)
            self.assertEqual(report['summary']['surface_candidates'],1)
            self.assertEqual(report['pages'][0]['summary']['printed_view_states'],['existing','proposed'])
            self.assertEqual(report['documents'][0]['drawing_state'],'proposed')
            evidence=json.loads((root/'output'/report['pages'][0]['evidence_file']).read_text())
            self.assertEqual(evidence['surface_labels'][0]['text'],'Footpath')
            self.assertFalse(evidence['world_placement_eligible'])
            self.assertIsNone(report['summary']['geometric_accuracy'])
            self.assertIsNone(report['summary']['physical_component_coverage'])
            self.assertFalse(report['summary']['reconstruction_completed'])
            self.assertEqual(report['summary']['registered_path_networks'],0)
            self.assertEqual(report['training_labels_generated'],0)
            self.assertFalse(report['model_promoted'])
            self.assertEqual(report['benchmark']['unseen_source_generalisation'],'not_assessed')
            self.assertIn('accuracy remains unassessed',(root/'output/review.html').read_text().lower())
            for name,sha in report['output_sha256'].items():
                self.assertEqual(hashlib.sha256((root/'output'/name).read_bytes()).hexdigest(),sha)
            self.assertEqual((root/'source.pdf').read_bytes(),before)
            self.assertLessEqual(max(report['pages'][0]['preview']['size_pixels']),1202)
            with self.assertRaisesRegex(ValueError,'Fresh'):pilot.run(config,lambda p:root/p,root/'output')

    def test_missing_and_wrong_source_do_not_become_completed_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root)
            config['documents'][0]['sha256']='a'*64
            report=pilot.run(config,lambda p:root/p,root/'wrong')
            self.assertEqual(report['summary']['completed_pages'],0)
            self.assertEqual(report['documents'][0]['status'],'source_withheld')
            self.assertIn('checksum',report['source_blockers'][0]['reason'])
            report=pilot.run(config,lambda p:root/'absent.pdf',root/'missing')
            self.assertEqual(report['documents'][0]['status'],'source_unavailable')
            self.assertIsNone(report['summary']['geometric_accuracy'])

    def test_page_budgets_require_explicit_selection_and_never_silently_truncate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root,pages=2)
            config['options']={'max_pages':1}
            report=pilot.run(config,lambda p:root/p,root/'withheld')
            self.assertEqual(report['summary']['attempted_pages'],0)
            self.assertIn('page budget',report['documents'][0]['reason'])
            config['documents'][0]['pages']=[2]
            report=pilot.run(config,lambda p:root/p,root/'selected')
            self.assertEqual([p['page'] for p in report['pages']],[2])

    def test_extreme_page_count_is_rejected_before_enumerating_or_rendering_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root)
            document=MagicMock();document.__len__.return_value=100000000
            opened=MagicMock();opened.__enter__.return_value=document
            with patch.object(pilot.pymupdf,'open',return_value=opened):
                report=pilot.run(config,lambda p:root/p,root/'output')
            self.assertEqual(report['summary']['attempted_pages'],0)
            self.assertIn('page budget',report['documents'][0]['reason'])
            document.__getitem__.assert_not_called()

    def test_elevation_and_detail_labels_cannot_enter_surface_extraction(self):
        for role in ('elevation','section','detail','location-plan'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);config=fixture(root,role=role)
                with patch('voxel_mapper.planning_area_pilot.ordinary_surfaces.page_candidates',
                           side_effect=AssertionError('Not a horizontal surface drawing')):
                    report=pilot.run(config,lambda p:root/p,root/'output')
                self.assertEqual(report['summary']['surface_labels'],0)
                self.assertEqual(report['summary']['surface_candidates'],0)

    def test_page_extraction_failure_remains_explicit_and_has_no_reference_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root,pages=2)
            original=pilot._page
            def fail_first(page,sha,number,role):
                if number==1:raise ValueError('Test drawing budget exceeded')
                return original(page,sha,number,role)
            with patch.object(pilot,'_page',side_effect=fail_first):
                report=pilot.run(config,lambda p:root/p,root/'output')
            self.assertEqual(report['summary']['attempted_pages'],2)
            self.assertEqual(report['summary']['completed_pages'],1)
            self.assertEqual(report['documents'][0]['status'],'partial_original_pdf_inspection')
            self.assertEqual(report['page_blocker_counts']['page_extraction_failed'],1)
            self.assertIsNone(report['summary']['geometric_accuracy'])

    def test_changed_source_or_cancellation_cannot_publish_a_success_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);original=pilot._page
            def change_source(*args):
                result=original(*args)
                with (root/'source.pdf').open('ab') as stream:stream.write(b'changed')
                return result
            with patch.object(pilot,'_page',side_effect=change_source):
                with self.assertRaisesRegex(ValueError,'changed during'):
                    pilot.run(config,lambda p:root/p,root/'changed')
            self.assertFalse((root/'changed/report.json').exists())
            with self.assertRaises(CancelledError):
                pilot.run(config,lambda p:root/p,root/'cancelled',cancelled=lambda:True)
            self.assertFalse((root/'cancelled').exists())

    def test_output_budget_stops_growth_without_completed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root);config['options']={'max_output_bytes':1000}
            with self.assertRaises(pilot.PilotBudgetExceeded):
                pilot.run(config,lambda p:root/p,root/'output')
            self.assertFalse((root/'output/report.json').exists())

    def test_validation_rejects_invalid_manifest_and_unseen_claims_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=fixture(root)
            mutations=[lambda c:c.update(development_exposure='unseen'),
                lambda c:c.update(options={'max_pages':True}),
                lambda c:c['documents'][0].update(pages=[[1]]),
                lambda c:c['documents'][0].update(pages=[True]),
                lambda c:c['documents'][0].update(pages=[1,1]),
                lambda c:c['documents'][0].update(application_reference='APP/OTHER'),
                lambda c:c['documents'].append(copy.deepcopy(c['documents'][0]))]
            for mutate in mutations:
                bad=copy.deepcopy(config);mutate(bad)
                with self.assertRaises(ValueError):pilot.run(bad,lambda p:root/p,root/'invalid')
                self.assertFalse((root/'invalid').exists())

    def test_cli_uses_originals_directory_without_editing_each_drawing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sources=root/'originals';sources.mkdir();config=fixture(sources)
            config['source_directory']='originals';(root/'pilot.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()) as stream:
                pilot.main(['--config',str(root/'pilot.json'),'--output',str(root/'output')])
            self.assertEqual(json.loads(stream.getvalue())['completed_pages'],1)


if __name__=='__main__':unittest.main()
