import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.elevation_interpretation import caption,review_page
from voxel_mapper.architectural_interpretation import interpret_page
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page

SHA='b'*64
SCALE={'document_sha256':SHA,'page':1,'status':'one_visible_printed_scale','expected_metres_per_pdf_point':.1,'denominators':[100]}


class ElevationTests(unittest.TestCase):
    def fixture(self,title='SOUTH ELEVATION'):
        document=pymupdf.open();page=document.new_page(width=450,height=450)
        page.draw_rect((20,20,200,180));page.insert_text((60,80),'brick',fontsize=12)
        page.insert_text((40,230),title,fontsize=10)
        parents,_=extract_page(page,SHA,1)
        polygons=[r for r in recover_page(parents)[0] if r['geometry']['type']=='Polygon']
        return document,page,parents,polygons

    def test_exact_caption_grammar_retains_view_scale_and_state(self):
        r=caption("W e s t R a n g e C o u r t y a r d ( E a s t ) E l e v a t i o n ' a s e x i s t i n g ' | 1 : 5 0")
        self.assertEqual(r['printed_scale_denominator'],50);self.assertEqual(r['view_direction'],'east')
        self.assertEqual(r['printed_state'],'existing')
        self.assertEqual(caption('Existing Elevations Sheet 2of4')['printed_state'],'existing')
        self.assertEqual(caption("Courtyard Elevations 'as proposed'")['printed_state'],'proposed')
        for value in ['see south elevation','roof plan','new elevation drawing here','south elevation |1:0']:
            self.assertIsNone(caption(value))

    def test_elevation_material_region_preserves_source_and_cannot_become_plan_roof(self):
        document,page,parents,polygons=self.fixture()
        try:
            original=copy.deepcopy(polygons);report=interpret_page(page,SHA,1,parents,polygons,SCALE)
            self.assertEqual(report['status'],'elevation_material_candidates_only')
            self.assertEqual(report['bound_roof_labels'],0);self.assertEqual(report['wall_band_candidates'],[])
            e=report['elevation_interpretation'];self.assertEqual(e['counts']['material_regions'],1)
            self.assertEqual(e['material_region_associations'][0]['source_candidate'],polygons[0])
            self.assertFalse(e['height_application_verified']);self.assertFalse(e['scale_application_verified'])
            self.assertEqual(e['world_geometry_additions'],0);self.assertEqual(polygons,original)
        finally:document.close()

    def test_conflicting_title_and_view_scales_are_not_applied(self):
        document,page,parents,polygons=self.fixture("West Range Courtyard (East) Elevation 'as existing' |1:50")
        try:
            scale={**SCALE,'status':'withheld_missing_ambiguous_or_unverified_scale','denominators':[50,100],
                   'expected_metres_per_pdf_point':None}
            e=interpret_page(page,SHA,1,parents,polygons,scale)['elevation_interpretation']
            self.assertEqual(e['view_scale_denominators'],[50]);self.assertEqual(e['page_scale_review']['denominators'],[50,100])
            self.assertEqual(e['scale_scope_status'],'page_view_scale_conflict')
            self.assertFalse(e['scale_application_verified']);self.assertEqual(e['printed_state'],'existing')
            self.assertEqual(e['counts']['material_regions'],1)
            with self.assertRaisesRegex(ValueError,'Source-bound'):review_page(page,SHA,1,polygons,{**scale,'page':2})
        finally:document.close()

    def test_hidden_captions_ambiguous_enclosures_and_mixed_views_are_withheld(self):
        document,page,parents,polygons=self.fixture()
        try:
            other=copy.deepcopy(polygons[0]);other['id']='overlap'
            self.assertEqual(review_page(page,SHA,1,polygons+[other],SCALE)['counts']['material_regions'],0)
            with patch('voxel_mapper.elevation_interpretation.screen_architectural_span',return_value={'status':'withheld'}):
                e=review_page(page,SHA,1,polygons,SCALE)
                self.assertEqual(e['status'],'elevation_view_scope_withheld');self.assertEqual(e['counts']['material_regions'],0)
            page.insert_text((40,300),'Ground Floor Plan',fontsize=10)
            e=review_page(page,SHA,1,polygons,SCALE)
            self.assertEqual(e['status'],'elevation_view_scope_withheld');self.assertEqual(e['counts']['material_regions'],0)
        finally:document.close()

    def test_proposed_and_conflicting_states_are_retained_not_certified(self):
        document,page,parents,polygons=self.fixture("Courtyard Elevations 'as proposed'")
        try:
            e=review_page(page,SHA,1,polygons,SCALE)
            self.assertEqual(e['printed_state'],'proposed');self.assertFalse(e['physical_identity_verified'])
            page.insert_text((40,300),'Existing Elevations 1of4',fontsize=10)
            self.assertEqual(review_page(page,SHA,1,polygons,SCALE)['printed_state'],'unspecified_or_conflicting')
        finally:document.close()

    def test_corpus_stage_pipeline_resume_version_and_partial_source_guards(self):
        from voxel_mapper.planning_bulk import Corpus
        from voxel_mapper.drawing_geometry import run as extract
        from voxel_mapper.architectural_interpretation import run
        from voxel_mapper.park_pipeline import run as park
        document,page,_,_=self.fixture('Existing Elevations 1of4')
        page.draw_line((300,20),(360,20))
        page.insert_text((40,350),'Scale 1:100',fontsize=12);data=document.tobytes();document.close()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=Corpus(root/'corpus')
            try:
                corpus.ingest([{'url':'https://portal.test/elevation','title':'Existing Elevations'}],['portal.test'])
                corpus.acquire(fetch=lambda _:data);extract(corpus,root/'drawing-geometry')
                report=run(corpus,root/'drawing-geometry',root/'architecture')
                self.assertEqual(report['counts']['elevation_material_regions'],1)
                self.assertEqual(report,run(corpus,root/'drawing-geometry',root/'architecture'))
                path=root/'architecture/architectural-report.json';changed=json.loads(path.read_text());changed['elevation_version']='old'
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError,'inputs changed'):run(corpus,root/'drawing-geometry',root/'architecture')
                extract(corpus,root/'partial',max_candidates=1)
                self.assertEqual(run(corpus,root/'partial',root/'partial-architecture')['counts']['elevation_material_regions'],0)
                job=root/'job.json';job.write_text(json.dumps({'work_directory':'.','acquisition':{'offline':True},
                    'drawing_analysis':{'enabled':False},'drawing_geometry':{'enabled':True},'architectural_interpretation':{'enabled':True}}))
                # Use the pipeline's distinct sidecar directory, retaining its own pin.
                self.assertEqual(park(job,'acquire')['stages']['architectural_interpretation']['counts']['elevation_material_regions'],1)
                self.assertEqual(park(job,'acquire')['stages']['architectural_interpretation']['counts']['elevation_material_regions'],1)
            finally:corpus.close()


if __name__=='__main__':unittest.main()
