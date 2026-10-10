import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import zipfile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from voxel_mapper.council import (SEARCH,DOCS,search_form,parse_results,parse_document_list,recent_references,
                                  application_context,application_order,inspect_pdf,read_pdf,acquire_council)
from voxel_mapper.pipeline import run_auto
import test_terrain_osm as fixtures


def pdf_fixture():
    writer=PdfWriter();page=writer.add_blank_page(width=600,height=800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 50 700 Td (Scale 1:2500 REV: P3 Revision Date Project) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);return output.getvalue()


def document_html(reference='RU.22/0374'):
    model={'PageHeader':'Documents for reference '+reference,'Rows':[
        {'Guid':'9A93AF471F944D08A400F616081A5264','Doc_Type':'Plan','Doc_Ref2':'Location Plan','Date_Received':'03/08/2022 00:00:00'},
        {'Guid':'A'*32,'Doc_Type':'General Correspondence','Doc_Ref2':'Letter'}]}
    return '<script>var model = '+json.dumps(model)+'; var data = JSON.stringify(model.Rows);</script>'


def reply(text='',url=SEARCH):
    response=Mock();response.text=text;response.url=url;return response


class CouncilTests(unittest.TestCase):
    def setUp(self):
        provider = patch('voxel_mapper.pipeline.acquire_buildings',return_value=(
            {'type':'FeatureCollection','features':[]},
            {'provider':'overture-buildings','status':'unavailable','failures':['Offline fixture']}))
        provider.start(); self.addCleanup(provider.stop)

    def test_form_preserves_state_and_selected_controls(self):
        data=search_form('<input name="__VIEWSTATE" value="state"><input name="txtSiteAddress"><input type="radio" name="date" value="all" checked><input type="radio" name="date" value="month"><select name="type"><option value="a">A</option><option selected value="b">B</option></select>','Park')
        self.assertEqual(data['__VIEWSTATE'],'state')
        self.assertEqual(data['date'],'all')
        self.assertEqual(data['type'],'b')
        self.assertEqual(data['txtSiteAddress'],'Park')
        with self.assertRaises(ValueError):search_form('<h1>Login</h1>','Park')

    def test_results_pagination_and_unrecognised_page(self):
        refs,next_url=parse_results('<a href="details">RU.22/0374</a><a href="details">RU.22/0374</a><a href="page2">Next</a>')
        self.assertEqual(refs,['RU.22/0374'])
        self.assertTrue(next_url.endswith('/page2'))
        with self.assertRaises(ValueError):parse_results('<h1>Access denied</h1>')
        self.assertEqual(parse_results('No applications found')[0],[])
        refs,next_url=parse_results('<a href="details">RU.22/0374</a><a href="page2"><img alt="Next Page"></a>',
                                   base_url='https://planning.runnymede.gov.uk/Northgate/PlanningExplorer/Generic/StdResults.aspx')
        self.assertEqual(next_url,'https://planning.runnymede.gov.uk/Northgate/PlanningExplorer/Generic/page2')
        with self.assertRaisesRegex(ValueError,'pagination'):
            parse_results('<a href="details">RU.22/0374</a><a href="javascript:next()">Next</a>')
        self.assertEqual(recent_references(['RU.76/0581','RU.26/0086','RU.22/0374','RU.26/0369','RU.26/0086'],2026),
                         ['RU.26/0369','RU.26/0086','RU.22/0374','RU.76/0581'])

    def test_document_identity_reference_and_filter(self):
        docs=parse_document_list(document_html(),'RU.22/0374')
        self.assertEqual(len(docs),1)
        self.assertEqual(docs[0]['id'],'9A93AF471F944D08A400F616081A5264')
        self.assertEqual(docs[0]['reuse_status'],'consultation_only')
        with self.assertRaises(ValueError):parse_document_list(document_html(),'RU.24/1234')
        with self.assertRaises(ValueError):parse_document_list('Access denied','RU.22/0374')
        model={'PageHeader':'Documents for reference RU.22/0374','Rows':[
            {'Guid':str(i)*32,'Doc_Type':'Supporting Documentation','Doc_Ref2':title}
            for i,title in enumerate(['Materials Schedule','Flood Risk Assessment','Topographic Survey','Unrelated Letter'],1)]}
        extra=parse_document_list('<script>var model = '+json.dumps(model)+'</script>','RU.22/0374')
        self.assertEqual([d['evidence_category'] for d in extra],['materials','water_and_levels','surveys'])

    def test_parent_permissions_and_materials_survive_recent_application_limit(self):
        html = '''<table><tr><td><a href="details">RU.26/0073</a></td>
          <td title="Site Address">Park</td><td title="Development Description">
          Discharge Condition 6 (materials) of planning permission RU.24/1476</td></tr>
          <tr><td><a href="details">RU.26/0086</a></td>
          <td title="Development Description">Habitat plan of RU.26/0369 varying RU.24/1476</td></tr>
          <tr><td><a href="unrelated">Other record</a></td><td>Unlabelled RU.22/0374</td></tr></table>'''
        context = application_context(html)
        self.assertEqual(len(context), 2)
        self.assertEqual(application_order(['RU.26/0086', 'RU.26/0073'], context),
                         ['RU.26/0369', 'RU.24/1476', 'RU.26/0073', 'RU.26/0086'])
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.council.requests.Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.get.side_effect = [reply('<input name="txtSiteAddress">'),
                                      reply(document_html('RU.26/0369'), DOCS),
                                      reply(document_html('RU.24/1476'), DOCS)]
            session.post.return_value = reply(html)
            result = acquire_council([{'reference':'E60000275'}], [], 'Park', Path(d),
                                    max_applications=2, max_pdf_inspections=0)
            self.assertEqual(result['applications'], ['RU.26/0369', 'RU.24/1476'])
            self.assertEqual(result['uninspected_application_references'], ['RU.26/0073', 'RU.26/0086'])
            self.assertTrue(result['applications_truncated'])
            self.assertEqual(result['geometry_replacements'], 0)

    def test_context_rejects_ambiguous_rows_and_bounds_parser_work(self):
        html = '''<tr><td><a href="one">RU.26/0073</a><a href="two">RU.26/0086</a></td>
          <td title="Development Description">Permission RU.24/1476</td></tr>'''
        self.assertEqual(application_context(html), [])
        with self.assertRaisesRegex(ValueError, 'row budget'):
            application_context(html, max_rows=0)

    def test_historical_named_building_application_precedes_recent_candidates(self):
        html='''<tr><td><a href="x">RU.89/0123</a></td>
        <td title="Development Description">Alterations to the Dome under RU.88/0456</td></tr>
        <tr><td><a href="y">RU.26/0001</a></td>
        <td title="Development Description">Dormer alterations</td></tr>'''
        contexts=application_context(html,target_names=['Dome'])
        self.assertEqual(contexts[0]['target_name_matches'],['Dome'])
        self.assertEqual(contexts[1]['target_name_matches'],[])
        self.assertEqual(application_order(['RU.26/0001','RU.89/0123'],contexts),
                         ['RU.88/0456','RU.89/0123','RU.26/0001'])

    def test_pdf_scale_revision_are_candidates_and_not_alignment(self):
        result=inspect_pdf(pdf_fixture())
        self.assertEqual(result['pages'][0]['scale_denominator_candidates'],[2500])
        self.assertEqual(result['pages'][0]['revision_label_candidates'],['P3'])
        self.assertFalse(result['pages'][0]['has_viewport_metadata'])
        self.assertEqual(result['alignment_status'],'unverified')
        self.assertEqual(result['pages'][0]['semantic_evidence']['status'],'text_candidates_only')
        with self.assertRaises(ValueError):inspect_pdf(b'<html>Access denied</html>')
        writer=PdfWriter();writer.add_blank_page(100,100);writer.encrypt('password');out=io.BytesIO();writer.write(out)
        with self.assertRaisesRegex(ValueError,'Encrypted'):inspect_pdf(out.getvalue())

    def test_stream_budget_and_host_guard_close_response(self):
        session=Mock();response=reply(url=DOCS+'/Document/ViewDocument?id=x');response.iter_content.return_value=[b'%PDF-',b'123456'];session.get.return_value=response
        with self.assertRaisesRegex(ValueError,'budget'):read_pdf(session,response.url,max_bytes=8)
        response.close.assert_called_once()
        with self.assertRaisesRegex(ValueError,'host'):read_pdf(session,'https://example.org/file.pdf')

    def test_blocked_search_can_use_automatic_record_references(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.council.requests.Session') as factory:
            session=factory.return_value.__enter__.return_value
            initial=reply('<input name="txtSiteAddress">');listing=reply(document_html(),DOCS)
            payload=reply(url=DOCS+'/Document/ViewDocument?id=x');payload.iter_content.return_value=[pdf_fixture()]
            session.get.side_effect=[initial,listing,payload]
            blocked=reply();blocked.raise_for_status.side_effect=requests.HTTPError('403 Forbidden');session.post.return_value=blocked
            result=acquire_council([{'reference':'E60000275'}],[{'reference':'RU.22/0374'}],'Park',Path(d))
            self.assertEqual(session.post.call_args.kwargs['headers'],{'Referer':SEARCH})
            self.assertEqual(result['application_search'],'blocked_or_unavailable')
            self.assertEqual(result['documents'][0]['inspection']['status'],'inspected_consultation_only')
            self.assertEqual(result['geometry_replacements'],0)
            self.assertEqual([p.name for p in Path(d).iterdir()],['council-drawings.json'])

    def test_unsupported_authority_does_not_contact_portal(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.council.requests.Session') as factory:
            result=acquire_council([{'reference':'other'}],[],'Park',Path(d))
            self.assertEqual(result['status'],'not_supported');factory.assert_not_called()

    def test_native_grid_fit_is_distinguished_from_geographic_alignment(self):
        inspection={'pages':[{'registration':{'status':'metadata_missing'},
                    'scanned_page_inspection':{'border_grid_inspection':{'grid_mark_registration':
                    {'status':'internally_consistent_grid_marks_unverified'}}}}]}
        for location,expected in [('not_checked','candidate_drawing_grid_fit_unverified'),
                                  ('candidate_grid_intersects_requested_area','candidate_drawing_grid_fit_unverified'),
                                  ('grid_outside_requested_area','drawing_grid_outside_requested_area')]:
            inspection['pages'][0]['scanned_page_inspection']['border_grid_inspection']['grid_location_check']={'status':location}
            with (self.subTest(location=location), tempfile.TemporaryDirectory() as d,
                    patch('voxel_mapper.council.requests.Session') as factory,
                    patch('voxel_mapper.council.read_pdf',return_value=b'%PDF-'),
                    patch('voxel_mapper.council.inspect_pdf',return_value=inspection)):
                session=factory.return_value.__enter__.return_value
                session.get.return_value=reply(document_html(),DOCS)
                result=acquire_council([{'reference':'E60000275'}],[{'reference':'RU.22/0374'}],None,Path(d),max_pdf_inspections=1)
            self.assertEqual(result['documents'][0]['alignment_status'],expected)
            self.assertEqual(result['geometry_replacements'],0)

    def test_document_and_inspection_budgets_are_reported(self):
        with tempfile.TemporaryDirectory() as d, patch('voxel_mapper.council.requests.Session') as factory:
            session=factory.return_value.__enter__.return_value
            session.get.return_value=reply(document_html('RU.24/1234'),DOCS)
            result=acquire_council([{'reference':'E60000275'}],[{'reference':'RU.22/0374 RU.24/1234'}],None,Path(d),max_applications=1,max_pdf_inspections=0)
            self.assertTrue(result['applications_truncated'])
            self.assertEqual(result['inspection_budget_omitted'],1)
            self.assertEqual(result['documents'][0]['alignment_status'],'not_inspected')

    def test_pipeline_automatically_selects_site_and_packages_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config,collection=fixtures.TerrainTests().fixture(root)
            source={'id':'dem','url':'https://example.org','license':'CC0','resolution_m':1}
            planning={'provider':'planning-data-england','status':'checked','datasets':[],
                      'documents':{'status':'catalogue_empty'},'records':[
                          {'dataset':'local-planning-authority','entity':1,'reference':'E60000275',
                           'point':'POINT(0.0005 0.0005)','name':'Runnymede'}]}
            council={'provider':'runnymede-planning','status':'checked','application_search':'completed_address_candidates',
                     'documents':[{'url':DOCS+'/Document/ViewDocument?id=x','alignment_status':'unverified'}],
                     'failures':[],'geometry_replacements':0,'reuse_status':'consultation_only'}
            with patch('voxel_mapper.pipeline.resolve_location',return_value=(config['bbox'],{'display_name':'Park, Street, UK'})), patch('voxel_mapper.pipeline.acquire_terrain',return_value=(config['terrain'],source,[])), patch('voxel_mapper.pipeline.acquire_surface',return_value=(None,None,[])), patch('voxel_mapper.pipeline.fetch_osm',return_value=(collection,{'elements':[]},[])), patch('voxel_mapper.pipeline.discover_planning',return_value=planning), patch('voxel_mapper.pipeline.acquire_council',return_value=council) as acquire:
                report=run_auto(root/'out',location='Park')
            self.assertEqual(acquire.call_args.args[2],'Park')
            self.assertEqual(acquire.call_args.args[0][0]['reference'],'E60000275')
            with zipfile.ZipFile(root/'out/park.mcworld') as archive:
                packaged=json.loads(archive.read('voxel-quality-report.json'))
                self.assertEqual(packaged['council_drawings']['geometry_replacements'],0)
                self.assertEqual(packaged['capabilities']['planning_drawing_geometry'],'no_usable_geometry_provider')
                self.assertEqual(packaged['planning_geometry_decisions'],[])
                self.assertFalse(any(n.endswith('.pdf') for n in archive.namelist()))
