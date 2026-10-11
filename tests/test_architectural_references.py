import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.architectural_references import reference,review_page,link_pages
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page


class ReferenceTests(unittest.TestCase):
    def source(self,kind='plan',state='existing',code='0860 IC',sha='c'*64):
        document=pymupdf.open();page=document.new_page(width=450,height=450)
        page.draw_rect((20,20,200,180));page.insert_text((60,80),'archway 1',fontsize=12)
        title="Ground Floor Plan 'as "+state+"'" if kind=='plan' else "South Elevation 'as "+state+"'"
        page.insert_text((30,240),title,fontsize=12);page.insert_text((30,300),code,fontsize=12)
        page.insert_text((30,350),'Scale 1:100',fontsize=12)
        parents,_=extract_page(page,sha,1);polygons=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
        return document,page,polygons,review_page(page,sha,1,polygons)

    def test_only_exact_object_references_parse(self):
        self.assertEqual(reference('a r c h w a y 4'),'archway:4')
        self.assertEqual(reference('w.2.01'),'w:2:01');self.assertEqual(reference('d.1.03'),'d:1:03')
        for text in ['see archway 1','archway 0','archway','window 1','4','roof 1']:self.assertIsNone(reference(text))

    def test_visible_native_enclosure_is_retained_without_becoming_coordinate_control(self):
        document,page,polygons,report=self.source()
        try:
            self.assertEqual(report['project_code'],'0860:IC');self.assertEqual(report['view_kind'],'plan')
            self.assertEqual(report['printed_state'],'existing')
            row=report['reference_occurrences'][0]
            self.assertEqual(row['containing_candidate_ids'],[polygons[0]['id']])
            self.assertFalse(row['coordinate_control_verified']);self.assertFalse(report['height_application_verified'])
            with patch('voxel_mapper.architectural_references.screen_architectural_span',return_value={'status':'withheld'}):
                hidden=review_page(page,'c'*64,1,polygons)
                self.assertIsNone(hidden['project_code']);self.assertEqual(hidden['reference_occurrences'][0]['containing_candidate_ids'],[])
        finally:document.close()

    def test_matching_code_state_and_plan_elevation_roles_required(self):
        a=self.source();b=self.source('elevation',sha='d'*64)
        try:
            links=link_pages([a[3],b[3]])['links'];self.assertEqual(len(links),1)
            self.assertFalse(links[0]['coordinate_alignment_verified']);self.assertEqual(links[0]['world_geometry_additions'],0)
            indexed=copy.deepcopy(a[3]);indexed['reference_occurrences'][0].update(source_end_connection_indices=[0,1],complete_source_cycle_candidates=0)
            candidate=link_pages([indexed,b[3]])['links'][0]
            self.assertEqual(candidate['occurrences'][0]['source_end_connection_indices'],[0,1])
            self.assertEqual(candidate['occurrences'][0]['complete_source_cycle_candidates'],0)
            self.assertFalse(candidate['coordinate_alignment_verified'])
            changed=copy.deepcopy(b[3]);changed['project_code']='9999:AA'
            self.assertEqual(link_pages([a[3],changed])['links'],[])
            changed=copy.deepcopy(b[3]);changed['printed_state']='proposed'
            self.assertEqual(link_pages([a[3],changed])['links'],[])
            changed=copy.deepcopy(b[3]);changed['view_kind']='plan'
            self.assertEqual(link_pages([a[3],changed])['links'],[])
            with self.assertRaises(ValueError):link_pages([a[3],a[3]])
        finally:a[0].close();b[0].close()

    def test_repeated_hidden_occurrences_are_retained_and_budget_discards_all_links(self):
        a=self.source();b=self.source('elevation',sha='d'*64)
        try:
            repeated=copy.deepcopy(b[3]);hidden=copy.deepcopy(repeated['reference_occurrences'][0])
            hidden['glyph_screen']['status']='withheld';hidden['containing_candidate_ids']=[]
            repeated['reference_occurrences'].append(hidden)
            links=link_pages([a[3],repeated])['links']
            self.assertTrue(links[0]['repeated_occurrences_present']);self.assertEqual(len(links[0]['occurrences']),3)
            report=link_pages([a[3],repeated],max_occurrences=2)
            self.assertEqual(report['status'],'reference_budget_withheld');self.assertEqual(report['links'],[])
            with self.assertRaises(ValueError):link_pages([a[3]],max_occurrences=True)
        finally:a[0].close();b[0].close()

    def test_conflicting_project_codes_and_mixed_views_cannot_be_discarded(self):
        document,page,polygons,_=self.source()
        try:
            page.insert_text((260,300),'9999 AA',fontsize=12)
            self.assertIsNone(review_page(page,'c'*64,1,polygons)['project_code'])
            page.insert_text((30,400),"South Elevation 'as proposed'",fontsize=12)
            report=review_page(page,'c'*64,1,polygons)
            self.assertEqual(report['view_kind'],'unspecified_or_mixed');self.assertEqual(report['printed_state'],'unspecified_or_conflicting')
        finally:document.close()

    def test_corpus_links_resume_and_sidecar_tamper_are_checked(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.architectural_interpretation import run
        a=self.source();b=self.source('elevation',sha='d'*64)
        data={'https://portal.test/plan':a[0].tobytes(),'https://portal.test/elevation':b[0].tobytes()}
        a[0].close();b[0].close()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':url,'title':url.rsplit('/',1)[-1]} for url in data],['portal.test'])
                corpus.acquire(fetch=lambda url:data[url]);extract(corpus,root/'geometry')
                report=run(corpus,root/'geometry',root/'architecture')
                self.assertEqual(report['counts']['printed_reference_correspondences'],1)
                pages=[json.loads(line) for line in (root/'architecture/architectural-pages.jsonl').read_text().splitlines()]
                plan=next(p for p in pages if p['architectural_references']['view_kind']=='plan')
                layout=plan['view_layout_review']
                self.assertEqual(layout['status'],'caption_layout_hypotheses_only')
                self.assertFalse(layout['view_scope_verified'])
                self.assertEqual(layout['world_geometry_additions'],0)
                graph=plan['source_geometry_graph']
                self.assertEqual(graph['status'],'source_drawing_topology_only')
                self.assertGreater(graph['counts']['edges'],0)
                self.assertFalse(graph['view_scope_verified'])
                self.assertEqual(graph['world_geometry_additions'],0)
                ends=plan['architectural_references']['archway_end_connections']
                self.assertEqual(ends['world_geometry_additions'],0)
                self.assertEqual(ends['status'],'exact_source_end_connections_only')
                self.assertEqual(report,run(corpus,root/'geometry',root/'architecture'))
                links=root/'architecture/architectural-reference-links.json';links.write_text('tampered')
                with self.assertRaisesRegex(ValueError,'reference links changed'):run(corpus,root/'geometry',root/'architecture')
            finally:corpus.close()


if __name__=='__main__':unittest.main()
