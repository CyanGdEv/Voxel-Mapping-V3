import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from PIL import Image
from shapely.geometry import shape

from voxel_mapper.architectural_graph import build
from voxel_mapper.architectural_view_layout import review,view_claim
from voxel_mapper.building_raster_views import placements
from voxel_mapper.drawing_geometry import extract_page,run as extract
from voxel_mapper.drawing_view_candidates import candidates,run,options
from voxel_mapper.planning_bulk import Corpus


class DrawingViewTests(unittest.TestCase):
    def source(self):
        document=pymupdf.open();page=document.new_page(width=620,height=600)
        labels=["Ground Floor Plan 'as existing' | 1:100","South Elevation 'as existing' | 1:50",
                "Roof Plan 'as existing' | 1:100","Section A-A 'as existing' | 1:50"]
        for (x,y),label in zip([(30,180),(350,180),(30,440),(350,440)],labels):
            page.draw_rect((x,y-150,x+190,y-40));page.insert_text((x,y),label,fontsize=8)
        image=BytesIO();Image.new('RGB',(30,20),'blue').save(image,format='PNG')
        page.insert_image((50,60,150,120),stream=image.getvalue())
        return document,page

    def inputs(self,page):
        sha='a'*64;parents,_=extract_page(page,sha,1,min_line_length_points=.25,max_candidates=10000)
        graph=build(parents);layout=review(page,sha,1,graph)
        sources=[{**s,'kind':'native_vector'} for s in parents]+[{**s,'kind':'raster_placement'} for s in placements(page,sha,1)['placements']]
        return layout,sources

    def test_ordinary_captions_keep_only_their_own_state_and_scale(self):
        for text,kind,state in [('Site Plan as Existing','sheet_title','existing'),
                ('Site Plan Proposed showing Woodland Path','sheet_title','proposed'),
                ('Proposed Block Plan | 1:200','sheet_title','proposed'),
                ('Ground Floor Plan as Existing','plan','existing'),
                ('North-East Elevation as Proposed','elevation','proposed')]:
            with self.subTest(text=text):
                claim=view_claim(text);self.assertEqual(claim['view_kind'],kind);self.assertEqual(claim['printed_state'],state)
        for text in ['see site plan as existing','Existing Site Plan as Proposed','Proposed Roof Plan as Existing',
                     'Site Plan | 1:99999','Section A-B','the north-east elevation requires repair']:
            self.assertIsNone(view_claim(text),text)
        self.assertEqual(view_claim('Existing Elevations')['kind'],'sheet_title')

    def test_four_views_preserve_whole_objects_and_nominal_metric_frames(self):
        document,page=self.source()
        try:
            layout,sources=self.inputs(page);original=copy.deepcopy(sources)
            result=candidates(page,'a'*64,1,layout,sources)
            self.assertEqual(len(result['views']),4)
            self.assertEqual({v['printed_claim']['view_kind'] for v in result['views']},{'plan','elevation','section'})
            self.assertEqual(result['counts']['one_whole_source_candidate'],len(sources))
            by_id={s['id']:s for s in sources}
            for v in result['views']:
                self.assertFalse(v['view_scope_verified']);self.assertFalse(v['world_placement_eligible'])
                self.assertIsNotNone(v['native_to_nominal_local_affine'])
                for source in v['whole_sources']:
                    self.assertEqual(source['geometry_pdf_native'],by_id[source['id']]['geometry'])
                    native=shape(source['geometry_pdf_native']);local=shape(source['geometry_nominal_local'])
                    self.assertAlmostEqual(local.length,native.length*v['nominal_metres_per_pdf_point'])
            self.assertEqual(sources,original)
            page.set_rotation(90)
            rotated=candidates(page,'a'*64,1,layout,sources)
            self.assertEqual(result,rotated);self.assertEqual(page.rotation,90)
        finally:document.close()

    def fragmented(self,texts):
        document=pymupdf.open();page=document.new_page(width=600,height=400);page.draw_rect((30,30,450,200))
        x=30
        for i,text in enumerate(texts):
            size=10+i*.02;page.insert_text((x,260),text,fontname='helv',fontsize=size)
            x+=pymupdf.get_text_length(text,fontname='helv',fontsize=size)
        return document,page

    def test_split_cad_caption_screens_each_fragment_without_state_inheritance(self):
        document,page=self.fragmented(['Site',' Plan',' as',' Existing'])
        try:
            layout,_=self.inputs(page);self.assertEqual(len(layout['sheet_titles']),1)
            self.assertEqual(layout['view_captions'],[])
            caption=layout['sheet_titles'][0]
            self.assertEqual(caption['printed_claim']['printed_state'],'existing')
            self.assertEqual(len(caption['caption_fragments']),4)
            self.assertEqual(caption['glyph_screen']['status'],'raster_consistent_candidate')
            self.assertTrue(all(f['trace_indices'] for f in caption['caption_fragments']))
            self.assertFalse(caption['physical_identity_verified'])
        finally:document.close()

    def test_conflicting_or_prose_fragment_context_cannot_publish_a_partial_caption(self):
        for fragments in [['Existing Site Plan',' as Proposed'],['See',' Site Plan']]:
            document,page=self.fragmented(fragments)
            try:
                layout,_=self.inputs(page)
                self.assertEqual(layout['view_captions']+layout['sheet_titles'],[])
                self.assertTrue(layout['native_fragment_line_contexts'])
            finally:document.close()

    def test_hidden_fragment_withholds_combined_caption(self):
        document,page=self.fragmented(['Site',' Plan',' as',' Existing'])
        try:
            page.draw_rect((91,248,140,264),fill=(1,1,1),color=(1,1,1),overlay=True)
            layout,_=self.inputs(page);self.assertEqual(len(layout['sheet_titles']),1)
            self.assertEqual(layout['sheet_titles'][0]['glyph_screen']['status'],'withheld')
        finally:document.close()

    def test_fragment_budget_does_not_fall_back_to_unchecked_partial_claims(self):
        document,page=self.source()
        try:
            with patch('voxel_mapper.caption_fragments.collect',return_value=([],'caption_fragment_budget_withheld',[])):
                layout,sources=self.inputs(page)
            self.assertTrue(all(v['glyph_screen']['status']=='withheld' for v in layout['view_captions']))
            self.assertEqual(candidates(page,'a'*64,1,layout,sources)['views'],[])
        finally:document.close()

    def test_cross_row_source_is_never_clipped_into_a_view(self):
        document,page=self.source()
        try:
            page.draw_line((295,40),(295,420));layout,sources=self.inputs(page)
            result=candidates(page,'a'*64,1,layout,sources)
            crossing=[m for m in result['source_membership'] if m['status']=='crossing_or_competing_candidates']
            self.assertTrue(crossing)
            copied={s['id'] for v in result['views'] for s in v['whole_sources']}
            self.assertFalse(copied&{m['source_id'] for m in crossing})
        finally:document.close()

    def test_full_page_raster_background_does_not_hide_visible_layout_gaps(self):
        document,page=self.source()
        try:
            image=BytesIO();Image.new('RGB',(620,600),'white').save(image,format='PNG')
            page.insert_image(page.rect,stream=image.getvalue(),overlay=False)
            layout,sources=self.inputs(page);result=candidates(page,'a'*64,1,layout,sources)
            self.assertEqual(len(result['views']),4)
            full=next(s for s in sources if s['kind']=='raster_placement' and shape(s['geometry']).area>300000)
            membership=next(r for r in result['source_membership'] if r['source_id']==full['id'])
            self.assertEqual(membership['status'],'crossing_or_competing_candidates')
            self.assertFalse(any(s['id']==full['id'] for v in result['views'] for s in v['whole_sources']))
            self.assertTrue(result['layout_raster_evidence'])
        finally:document.close()

    def test_hidden_duplicate_and_competing_scale_claims_stay_explicit(self):
        document,page=self.source()
        try:
            layout,sources=self.inputs(page);caption=layout['view_captions'][0]
            changed=copy.deepcopy(layout);changed['view_captions'][0]['glyph_screen']['status']='withheld'
            hidden=candidates(page,'a'*64,1,changed,sources)
            self.assertNotIn(caption['id'],[v['caption_id'] for v in hidden['views']])
            changed=copy.deepcopy(layout);duplicate=copy.deepcopy(caption);duplicate['id']='duplicate';changed['view_captions'].append(duplicate)
            repeated=candidates(page,'a'*64,1,changed,sources)
            self.assertIn(caption['id'],[r['caption_id'] for r in repeated['withheld_captions']])
            changed=copy.deepcopy(layout);changed['view_captions'][0]['adjacent_scale_candidates']=[{'printed_denominator':200}]
            conflicting=candidates(page,'a'*64,1,changed,sources)
            view=next(v for v in conflicting['views'] if v['caption_id']==caption['id'])
            self.assertIsNone(view['native_to_nominal_local_affine'])
            self.assertTrue(all(s['geometry_nominal_local'] is None for s in view['whole_sources']))
        finally:document.close()

    def test_budget_clears_partial_results_and_wrong_source_rejects(self):
        document,page=self.source()
        try:
            layout,sources=self.inputs(page);r=candidates(page,'a'*64,1,layout,sources,max_checks=1)
            self.assertEqual(r['status'],'view_budget_withheld');self.assertEqual(r['views'],[])
            self.assertEqual(r['source_membership'],[])
            with self.assertRaises(ValueError):candidates(page,'b'*64,1,layout,sources)
            for configuration in [{'max_checks':True},{'render_width':199},{'unknown':1}]:
                with self.assertRaises(ValueError):options(configuration)
        finally:document.close()

    def prepare(self,root):
        document,_=self.source();data=document.tobytes();document.close();sha=hashlib.sha256(data).hexdigest()
        corpus=Corpus(root/'corpus');corpus.ingest([{'url':'https://portal.test/plan','sha256':sha,'title':'Mixed drawing'}],['portal.test'])
        corpus._retain(data,sha);corpus.acquire(offline=True);extract(corpus,root/'geometry')
        return corpus,sha

    def test_rendered_pack_reuses_and_rejects_changed_artifact_or_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,sha=self.prepare(root)
            try:
                first=run(corpus,root/'geometry',root/'packs',settings={'render_width':400})
                self.assertEqual(first['views'],4);self.assertEqual(first['nominal_scaled_views'],4)
                replay=run(corpus,root/'geometry',root/'packs',settings={'render_width':400})
                self.assertEqual(replay['run_pages'],0);self.assertEqual(replay['reused_pages'],1)
                directory=Path(first['directory']);png=next(directory.glob('views/*/view.png'));original=png.read_bytes();png.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'output changed'):run(corpus,root/'geometry',root/'packs',settings={'render_width':400})
                png.write_bytes(original);(corpus.root/'files'/(sha+'.pdf')).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'Original drawing changed'):run(corpus,root/'geometry',root/'packs',settings={'render_width':400})
            finally:corpus.close()

    def test_pack_budget_applies_even_when_no_views_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus,_=self.prepare(root)
            try:
                def no_views(*args):
                    layout=review(*args);layout['view_captions']=[];return layout
                with patch('voxel_mapper.drawing_view_candidates.caption_review',side_effect=no_views):
                    with patch('voxel_mapper.drawing_view_candidates.MAX_PACK_BYTES',100):
                        with self.assertRaisesRegex(ValueError,'pack output budget'):
                            run(corpus,root/'geometry',root/'packs')
                self.assertEqual(list((root/'packs').glob('*/view-report.json')),[])
            finally:corpus.close()

    def test_area_job_exposes_view_pack_and_reuses_without_per_view_bounds(self):
        from voxel_mapper.area_reconstruction import run as area_run,run_all
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);document,_=self.source();data=document.tobytes();document.close();sha=hashlib.sha256(data).hexdigest()
            (root/'sources').mkdir();(root/'sources'/(sha+'.pdf')).write_bytes(data)
            (root/'catalogue.json').write_text(json.dumps({'entries':[{'url':'https://portal.test/plan','sha256':sha,'applicationReference':'A'}]}))
            job={'work_directory':'work','catalogue':'catalogue.json','official_hosts':['portal.test'],'offline':True,
                 'source_directories':['sources'],'drawing_views':{'enabled':True,'render_width':400},
                 'areas':[{'id':'test','name':'Fixture views','application_references':['A'],'required_families':['local_building']}]}
            path=root/'job.json';path.write_text(json.dumps(job))
            first=area_run(path)['areas']['test'];self.assertEqual(first['drawing_views']['views'],4)
            self.assertEqual(first['world_geometry_additions'],0)
            self.assertEqual(area_run(path)['areas']['test']['drawing_views']['run_pages'],0)
            self.assertIn('drawing_views',run_all(path,stage='extract')['results'][0])
