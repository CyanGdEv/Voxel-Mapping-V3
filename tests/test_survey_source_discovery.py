import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.survey_source_discovery import signals,catalogue_queue,run

class SurveySourceTests(unittest.TestCase):
    def test_cited_drawing_identity_and_ambiguous_revisions_stay_unverified(self):
        records=[{'url':'https://portal.test/a','title':'2936 Master Land Survey'},
                 {'url':'https://portal.test/b','title':'Drawing 2936 revision B'},
                 {'url':'https://portal.test/c','title':'Ecological survey'}]
        statuses={r['url']:{'status':'pending','sha':None} for r in records}
        observed=[{'document_sha256':'a'*64,'page':1,**signals('On Centre Survey Drawing 2936 MASTER LAND SURVEY. Coordinates are arbitrary.')}]
        queue=catalogue_queue(records,observed,statuses)
        self.assertEqual(len(queue['priority_urls']),2)
        self.assertEqual(queue['drawing_references'][0]['status'],'ambiguous_catalogue_candidates')
        self.assertFalse(queue['registration_verified']);self.assertEqual(queue['accepted_controls'],0)
        self.assertIn('arbitrary_coordinates',observed[0]['survey_context']['restriction_flags'])
    def test_missing_reference_never_guesses_a_url_and_forms_are_not_controls(self):
        record={'url':'https://portal.test/a','title':'Application Form'}
        observations=[{'document_sha256':'a'*64,'page':1,**signals('Easting: 407345 Northing: 343810\nSurvey Drawing 2936 MASTER LAND SURVEY')}]
        queue=catalogue_queue([record],observations,{record['url']:{'status':'downloaded','sha':'a'*64}})
        self.assertEqual(queue['priority_urls'],[])
        self.assertEqual(queue['unresolved_references'],1)
        self.assertEqual(queue['drawing_references'][0]['catalogue_urls'],[])
        self.assertEqual(queue['accepted_checkpoints'],0)
    def test_number_prefix_cannot_match_another_drawing(self):
        records=[{'url':'https://portal.test/a','title':'29360 Master Land Survey'}]
        obs=[{'document_sha256':'a'*64,'page':1,**signals('Survey Drawing 2936 MASTER LAND SURVEY')}]
        q=catalogue_queue(records,obs,{records[0]['url']:{'status':'pending','sha':None}})
        self.assertEqual(q['drawing_references'][0]['catalogue_urls'],[])
    def pdf(self):
        with pymupdf.open() as document:
            for text in ['Survey Drawing 2936 MASTER LAND SURVEY','Station Easting Northing\nEPSG:27700']:
                page=document.new_page();page.insert_text((20,40),text)
            return document.tobytes()
    def test_page_replay_catalogue_growth_and_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=Corpus(root/'corpus');data=self.pdf()
            try:
                corpus.ingest([{'url':'https://portal.test/plan','title':'Site plan'}],['portal.test'])
                corpus.acquire(fetch=lambda _:data)
                first=run(corpus,root/'first');self.assertEqual(first['pages'],2)
                self.assertEqual(first['unresolved_references'],1)
                with patch('voxel_mapper.survey_source_discovery.signals',wraps=signals) as inspected:
                    again=run(corpus,root/'again')
                    self.assertEqual(again['reused_pages'],2)
                    self.assertEqual(inspected.call_count,1) # catalogue title only
                self.assertEqual(first['page_observations'],again['page_observations'])
                corpus.ingest([{'url':'https://portal.test/survey','title':'2936 Master Land Survey'}],['portal.test'])
                grown=run(corpus,root/'grown');self.assertEqual(grown['reused_pages'],2)
                self.assertEqual(grown['unresolved_references'],0)
                self.assertEqual(grown['priority_urls'],['https://portal.test/survey'])
                bounded=run(corpus,root/'bounded',max_pages=1)
                self.assertEqual(bounded['pages'],1);self.assertGreater(bounded['deferred_documents'],0)
                (corpus.root/'files'/(hashlib.sha256(data).hexdigest()+'.pdf')).write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):run(corpus,root/'corrupt')
            finally:corpus.close()
    def test_acquisition_priorities_select_known_attachments_within_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus=Corpus(tmp);requested=[];data=self.pdf()
            try:
                records=[{'url':'https://portal.test/'+name} for name in ('a-report','z-survey')]
                corpus.ingest(records,['portal.test'])
                corpus.acquire(workers=1,limit=1,interval=0,priority_urls=[records[1]['url']],fetch=lambda url:(requested.append(url) or data))
                self.assertEqual(requested,[records[1]['url']])
                self.assertEqual(corpus.db.execute("SELECT status FROM downloads WHERE url=?",(records[0]['url'],)).fetchone()[0],'pending')
                for priorities in (['https://unknown.test/survey'],[records[0]['url']]*2,[True]):
                    with self.assertRaises(ValueError):corpus.acquire(offline=True,priority_urls=priorities)
            finally:corpus.close()
