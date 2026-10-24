from concurrent.futures import CancelledError
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import planning_area_pilot as planning
from voxel_mapper import web_evidence as web, web_research
from voxel_mapper import web_planning_pilot as bridge
from test_web_evidence import PUBLIC, Response, Session, resolver


def pdf(pages):
    with pymupdf.open() as document:
        for text in pages:
            page=document.new_page(width=600,height=500)
            page.draw_rect((30,30,190,140));page.insert_text((50,80),'Footpath',fontsize=10)
            page.insert_text((30,190),text,fontsize=10)
        return document.tobytes()


def fixture(cache,*,pages=None,link_title='Proposed Floor Plan'):
    data=pdf(pages or ['Proposed Ground Floor Plan | 1:100','Existing Front Elevation'])
    index=('<html><main>APP/1 <a href="/drawing">'+link_title+'</a></main></html>').encode()
    for value,body in ((PUBLIC,index),(PUBLIC+'drawing',data)):
        web.fetch(value,cache,['example.org'],session=Session([Response(body)]),resolver=resolver)
    return {'version':bridge.VERSION,'area_id':'synthetic-web-area','application_reference':'APP/1',
        'research':{'version':web_research.VERSION,'urls':[PUBLIC],
            'allowed_hosts':['example.org'],'offline':True}},data


class WebPlanningPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache'
        self.config,self.data=fixture(self.cache)

    def run_job(self,**kwargs):
        return bridge.run(self.config,self.root/'output',self.cache,**kwargs)

    def test_discovered_originals_automatically_enter_page_specific_analysis(self):
        original=planning.ordinary_surfaces.page_candidates
        with patch.object(planning.ordinary_surfaces,'page_candidates',wraps=original) as surface:
            report=self.run_job()
        self.assertEqual(surface.call_count,1)
        self.assertEqual(report['summary']['completed_pages'],2)
        self.assertEqual(report['summary']['visible_view_captions'],2)
        self.assertEqual(report['summary']['surface_candidates'],1)
        handoff=report['handoffs'][0]
        self.assertEqual(handoff['page_roles'],{'1':'floor-plan','2':'elevation'})
        self.assertEqual(handoff['drawing_state'],'unknown')
        self.assertTrue(handoff['parent_link_claims'][0]['application_reference_observed'])
        self.assertFalse(handoff['application_membership_verified'])
        self.assertEqual((self.root/'output'/handoff['original_file']).read_bytes(),self.data)
        manifest=json.loads((self.root/'output/planning-manifest.json').read_text())
        self.assertEqual(manifest['documents'][0]['drawing_state'],'unknown')
        analysis=json.loads((self.root/'output/analysis/report.json').read_text())
        self.assertEqual([r['summary']['analysis_role'] for r in analysis['pages']],['floor-plan','elevation'])
        self.assertEqual(report['training_labels_generated'],0);self.assertFalse(report['world_placement_eligible'])
        self.assertIsNone(report['geometric_accuracy'])
        for name,pin in report['output_sha256'].items():
            self.assertEqual(hashlib.sha256((self.root/'output'/name).read_bytes()).hexdigest(),pin)
        self.assertIn('analysis/review.html',(self.root/'output/review.html').read_text())

    def test_mixed_roles_and_states_on_one_page_remain_unclassified(self):
        self.config,self.data=fixture(self.cache,pages=['Proposed Ground Floor Plan\nExisting Front Elevation'])
        with patch.object(planning.ordinary_surfaces,'page_candidates',side_effect=AssertionError('Mixed role page')):
            report=self.run_job()
        self.assertEqual(report['summary']['unclassified_pages'],1)
        self.assertEqual(report['summary']['drawing_state_conflicts'],1)
        self.assertEqual(report['summary']['surface_candidates'],0)
        self.assertIn('page_drawing_role_unresolved',report['page_blocker_counts'])

    def test_roof_plan_cannot_become_ground_paving_from_link_title(self):
        self.config,self.data=fixture(self.cache,pages=['Proposed Roof Plan'],link_title='Proposed Floor Plan')
        with patch.object(planning.ordinary_surfaces,'page_candidates',side_effect=AssertionError('Roof is not ground paving')):
            report=self.run_job()
        self.assertEqual(report['handoffs'][0]['page_roles'],{'1':'roof-plan'})
        self.assertEqual(report['summary']['surface_candidates'],0)

    def test_unknown_caption_stays_unclassified(self):
        self.config,self.data=fixture(self.cache,pages=['Unrecognised drawing'])
        with patch.object(planning.ordinary_surfaces,'page_candidates',side_effect=AssertionError('No horizontal caption')):
            report=self.run_job()
        self.assertEqual(report['handoffs'][0]['pages'][0]['status'],'no_supported_role_caption')
        self.assertEqual(report['summary']['completed_pages'],1)

    def test_no_native_text_pdf_retains_ocr_gap_without_invented_drawing_role(self):
        with pymupdf.open() as doc:
            doc.new_page();data=doc.tobytes()
        web.fetch(PUBLIC+'drawing',self.cache,['example.org'],session=Session([Response(data)]),resolver=resolver)
        report=self.run_job()
        self.assertTrue(report['handoffs'][0]['ocr_required'])
        self.assertIn('scanned_pdf_requires_ocr',report['blockers'])
        self.assertEqual(report['handoffs'][0]['page_roles'],{'1':'unclassified'})

    def test_all_pages_or_explicit_document_gap_without_silent_truncation(self):
        self.config['analysis_options']={'max_document_pages':1}
        report=self.run_job()
        self.assertEqual(report['summary']['completed_pages'],0)
        self.assertIsNone(report['planning_report'])
        self.assertEqual(report['handoffs'][0]['status'],'drawing_withheld')
        self.assertIn('no pages silently selected',report['handoffs'][0]['reason'])

    def test_ordinary_html_and_missing_pdf_produce_useful_source_gaps(self):
        self.config['research']['urls']=[PUBLIC+'absent']
        report=self.run_job()
        self.assertEqual(report['summary']['retrieved_sources'],0)
        self.assertEqual(report['summary']['completed_pages'],0)
        self.assertIn('no_original_pdf_available_for_analysis',report['blockers'])
        self.assertTrue((self.root/'output/review.html').is_file())

    def test_changed_cached_body_is_withheld_before_copy_or_analysis(self):
        def research(*args,**kwargs):
            result=web_research.run(*args,**kwargs)
            source=web.cached(PUBLIC+'drawing',self.cache,['example.org'])
            web._body_path(self.cache,source).write_bytes(b'corrupt')
            return result
        report=self.run_job(research=research)
        self.assertEqual(len(report['handoff_gaps']),1)
        self.assertEqual(report['summary']['completed_pages'],0)
        self.assertEqual(list((self.root/'output/originals').iterdir()),[])

    def test_changed_original_during_analysis_cannot_publish_completed_bridge(self):
        def analyze(config,resolve,output,**kwargs):
            result=planning.run(config,resolve,output,**kwargs)
            resolve(config['documents'][0]['file']).write_bytes(b'changed')
            return result
        with self.assertRaisesRegex(ValueError,'changed during automatic analysis'):
            self.run_job(analyze=analyze)
        self.assertFalse((self.root/'output/report.json').exists())

    def test_duplicate_bytes_from_distinct_urls_are_analysed_once(self):
        web.fetch(PUBLIC+'duplicate',self.cache,['example.org'],session=Session([Response(self.data)]),resolver=resolver)
        self.config['research']['urls'].append(PUBLIC+'duplicate')
        report=self.run_job()
        self.assertEqual(report['summary']['pdf_sources'],2)
        self.assertEqual(report['summary']['unique_originals_handed_to_analysis'],1)
        self.assertEqual(report['summary']['completed_pages'],2)

    def test_combined_output_budget_and_cancellation_publish_no_completion(self):
        self.config['analysis_options']={'max_output_bytes':100}
        with self.assertRaises(planning.PilotBudgetExceeded): self.run_job()
        self.assertFalse((self.root/'output/report.json').exists())
        with self.assertRaises(CancelledError):
            bridge.run(self.config,self.root/'cancelled',self.cache,cancelled=lambda:True)
        self.assertFalse((self.root/'cancelled').exists())

    def test_invalid_configs_and_page_roles_fail_before_output(self):
        for mutation in ({'application_reference':''},{'development_exposure':'unseen'},
                         {'analysis_options':{'max_pages':1000}},{'unexpected':True}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):bridge.validate({**self.config,**mutation})
        base={'version':planning.VERSION,'area_id':'test','application_references':['APP/1'],
            'documents':[{'file':'a.pdf','sha256':'a'*64,'title':'test','role':'unclassified',
                'drawing_state':'unknown','application_reference':'APP/1','pages':[1]}]}
        for roles in ({'0':'floor-plan'},{'2':'floor-plan'},{'1':[]},{'1':'unsupported'},{True:'floor-plan'}):
            bad=copy.deepcopy(base);bad['documents'][0]['page_roles']=roles
            with self.subTest(roles=roles),self.assertRaises(ValueError):planning.validate(bad)
