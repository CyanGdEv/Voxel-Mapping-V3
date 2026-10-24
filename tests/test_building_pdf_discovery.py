import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.building_pdf_discovery import VERSION,prepare,discover_page
from voxel_mapper.building_spec import digest


class PDFDiscoveryTests(unittest.TestCase):
    def pdf(self,root,name='source.pdf',states=('existing',)):
        doc=pymupdf.open()
        for state in states:
            page=doc.new_page(width=500,height=600)
            # Four independent source edges must be recovered without a model.
            for a,b in zip([(30,30),(180,30),(180,150),(30,150)],[(180,30),(180,150),(30,150),(30,30)]):page.draw_line(a,b)
            page.insert_text((30,200),f"Ground Floor Plan 'as {state}' | 1:100",fontsize=10)
        data=doc.tobytes();doc.close();(root/name).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def config(self,sha,name='source.pdf'):
        return {'version':VERSION,'buildings':[{'building_id':'raw-building','sources':[{'path':name,'sha256':sha}]}]}

    def test_model_free_geometry_source_cycles_and_integrity_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.pdf(root);config=self.config(sha)
            report=prepare(config,lambda p:root/p,root/'feed')
            self.assertEqual(report['discovered_pages'],1);self.assertEqual(report['shared_specs_generated'],0)
            raw=(root/'feed/discovery-pages.jsonl').read_bytes();page=json.loads(raw)
            self.assertEqual(len(page['closed_source_faces']),1)
            self.assertEqual(page['assembly_state'],'existing')
            self.assertFalse(page['world_placement_eligible']);self.assertFalse(page['shared_spec_generated'])
            self.assertFalse(page['caption_layout']['view_scope_verified'])
            pointer=json.loads((root/'feed/discovery-index.json').read_text())['pages'][0]
            self.assertEqual(hashlib.sha256(raw[pointer['offset_bytes']:pointer['offset_bytes']+pointer['length_bytes']]).hexdigest(),pointer['record_sha256'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),report['pages_sha256'])
            self.assertIsNone(json.loads((root/'feed/source-queue.json').read_text())['records'][0]['outcome'])
            with self.assertRaises(ValueError):prepare(config,lambda p:root/p,root/'feed')
            prepare(config,lambda p:root/p,root/'second')
            self.assertEqual(raw,(root/'second/discovery-pages.jsonl').read_bytes())

    def test_invalid_source_isolated_and_no_partial_document_on_record_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.pdf(root,states=('existing','existing'));config=self.config(sha)
            config['options']={'max_records':5} # A two-page document cannot fit.
            report=prepare(config,lambda p:root/p,root/'limited')
            self.assertEqual(report['discovered_pages'],0)
            self.assertEqual((root/'limited/discovery-pages.jsonl').read_bytes(),b'')
            self.assertIn('record budget',report['buildings'][0]['documents'][0]['reason'])
            good=copy.deepcopy(config['buildings'][0]);good['building_id']='good'
            config.pop('options');config['buildings'][0]['sources'][0]['sha256']='f'*64;config['buildings'].append(good)
            report=prepare(config,lambda p:root/p,root/'isolated')
            self.assertEqual(report['discovered_pages'],2)
            self.assertEqual(report['buildings'][0]['status'],'incomplete_source_inventory')
            self.assertEqual(report['buildings'][1]['status'],'source_inventory_prepared')

    def test_mixed_states_preserved_and_page_limits_require_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.pdf(root,states=('existing','proposed'));config=self.config(sha)
            report=prepare(config,lambda p:root/p,root/'mixed')
            self.assertEqual(report['buildings'][0]['source_states'],['existing','proposed'])
            queue=json.loads((root/'mixed/source-queue.json').read_text())
            self.assertTrue(queue['records'][0]['mixed_source_states_withheld'])
            config['options']={'max_document_pages':1}
            report=prepare(config,lambda p:root/p,root/'limited')
            self.assertEqual(report['discovered_pages'],0)
            config['buildings'][0]['sources'][0]['pages']=[2]
            report=prepare(config,lambda p:root/p,root/'selected')
            self.assertEqual(report['buildings'][0]['source_states'],['proposed'])
            for pages in ([True],[1,1],[0]):
                bad=copy.deepcopy(config);bad['buildings'][0]['sources'][0]['pages']=pages
                with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')

    def test_output_byte_budget_withholds_whole_document_and_cli_matches(self):
        from voxel_mapper.building_pipeline import main
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.pdf(root);config=self.config(sha)
            config['options']={'max_document_output_bytes':1}
            report=prepare(config,lambda p:root/p,root/'limited')
            self.assertEqual(report['output_bytes'],0)
            self.assertEqual(report['discovered_pages'],0)
            self.assertIn('output byte budget',report['buildings'][0]['documents'][0]['reason'])
            config.pop('options');(root/'config.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()):main(['discover-pdf','--config',str(root/'config.json'),'--output',str(root/'cli')])
            self.assertEqual(json.loads((root/'cli/report.json').read_text())['discovered_pages'],1)
            bad=copy.deepcopy(config);bad['options']=None
            with self.assertRaises(ValueError):prepare(bad,lambda p:root/p,root/'bad')

    def test_partial_extraction_cannot_supply_geometry_or_scope(self):
        doc=pymupdf.open();page=doc.new_page()
        try:
            with patch('voxel_mapper.building_pdf_discovery.extract_page',return_value=([{'forged':'partial'}],{'status':'partial_candidate_budget'})):
                row=discover_page(page,'a'*64,1)
            self.assertEqual(row['source_geometry'],[]);self.assertEqual(row['closed_source_faces'],[])
            self.assertEqual(row['status'],'complete_geometry_extraction_required')
        finally:doc.close()

    def test_geometry_budget_failure_retains_original_caption_inventory_only(self):
        doc=pymupdf.open();page=doc.new_page()
        page.insert_text((30,100),'Existing Front Elevation',fontsize=10)
        try:
            with patch('voxel_mapper.building_pdf_discovery.extract_page',return_value=(
                    [{'forged':'partial'}],{'status':'partial_candidate_budget'})):
                row=discover_page(page,'a'*64,1)
            self.assertEqual(row['status'],'complete_geometry_extraction_required')
            self.assertEqual(row['source_geometry'],[])
            self.assertEqual(row['closed_source_faces'],[])
            layout=row['caption_layout']
            self.assertEqual([v['text'] for v in layout['view_captions']],['Existing Front Elevation'])
            self.assertEqual(layout['component_membership'],[])
            self.assertEqual(layout['subgraph_membership'],[])
            self.assertFalse(row['world_placement_eligible'])
            self.assertFalse(layout['view_scope_verified'])
        finally:doc.close()

    def test_topology_failure_also_preserves_captions_without_partial_geometry(self):
        original=__import__('voxel_mapper.building_pdf_discovery',fromlist=['build']).build
        doc=pymupdf.open();page=doc.new_page();page.draw_rect((30,30,200,60))
        page.insert_text((30,100),'Existing Section A-A',fontsize=10)
        def fail_nonempty(parents):
            return {'status':'withheld','reason':'intersection_budget'} if parents else original([])
        try:
            with patch('voxel_mapper.building_pdf_discovery.build',side_effect=fail_nonempty):
                row=discover_page(page,'a'*64,1)
            self.assertEqual(row['status'],'complete_source_topology_required')
            self.assertEqual(row['source_geometry'],[])
            self.assertEqual(row['counts']['view_captions'],1)
            self.assertEqual(row['graph_review']['reason'],'intersection_budget')
            self.assertEqual(row['caption_layout']['component_membership'],[])
        finally:doc.close()
