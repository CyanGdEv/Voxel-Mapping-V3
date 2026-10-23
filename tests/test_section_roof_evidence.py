import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from voxel_mapper import colored_source_glyphs as color
from voxel_mapper import glyph_visibility
from voxel_mapper import section_roof_evidence as evidence
from voxel_mapper import section_roof_leaders as leaders
from tests import test_glyph_visibility as font_fixtures


class SectionRoofEvidenceTests(unittest.TestCase):
    def color_source(self):
        doc,page,span=font_fixtures.GlyphTests().cff_source()
        contents=page.get_contents()[0];doc.update_stream(contents,b'.5 .32 .17 rg\n'+doc.xref_stream(contents))
        span=page.get_texttrace()[0];span={**span,'chars':[(97+i,*c[1:]) for i,c in enumerate(span['chars'])]}
        return doc,page,span

    def graph(self, *, long_cap=False, gap=0.):
        def line(i,a,b):return {'id':i,'source_endpoints_pdf_unrotated':[list(a),list(b)],'length_pdf_points':__import__('math').dist(a,b)}
        words=[{'id':'word','source_bbox_pdf_unrotated':[40,5,60,18],'status':'source_numeric_glyph_candidate'}]
        lines=[line('leader',(50,20),(50,70)),line('head-left',(46,66),(50,70)),line('head-right',(50,70),(54,66)),
               line('slope-left',(20,100),(50+gap,70)),line('slope-right',(50,70),(80,100)),
               line('cap',(10 if long_cap else 20,100),(90 if long_cap else 80,100))]
        return words,lines

    def fixture(self,root):
        folder=root/'pdfs';folder.mkdir()
        with pymupdf.open() as doc:
            page=doc.new_page(width=400,height=400);page.insert_text((10,20),'1/200 @ A1',fontsize=10)
            page.insert_text((135,100),'191.5',fontsize=10)
            for a,b in [((150,104),(150,170)),((146,166),(150,170)),((150,170),(154,166)),((100,200),(150,170)),((150,170),(200,200)),((100,200),(200,200))]:page.draw_line(a,b)
            raw=doc.tobytes()
        sha=hashlib.sha256(raw).hexdigest();(folder/(sha+'.pdf')).write_bytes(raw)
        catalogue=root/'catalogue.json';catalogue.write_text(json.dumps({'entries':[{'sha256':sha,'title':'Test proposed section','nominal_scale_denominator':200}]}))
        parent=root/'fascia.json';parent.write_text(json.dumps({'status':'conditional_source_gradient_fascia_only',
            'models':[{'id':'model','source_level_value_m_candidate':183.3,'mesh':{'vertices':[[0,0,6.083333333333333]]*4+[[0,0,8.2]]}}]}))
        return catalogue,folder,parent,root/'output'

    def test_original_cid_resources_color_and_rotation_preserved(self):
        doc,page,span=self.color_source()
        try:
            page.set_rotation(90);before=doc.tobytes(no_new_id=True);r=color.screen(page,span)
            self.assertEqual(r['status'],'raster_consistent_candidate',r);self.assertEqual(page.rotation,90)
            self.assertFalse(r['font_substitution_used']);self.assertEqual(doc.tobytes(no_new_id=True),before)
            self.assertEqual(r['original_font_candidates'][0]['original_cids'],[42,421])
            self.assertEqual(glyph_visibility.screen_span(page,span)['status'],'withheld')
        finally:doc.close()

    def test_colored_glyph_overpainting_with_white_black_or_same_color_is_held(self):
        for fill in ((1,1,1),(0,0,0),(.5,.32,.17)):
            doc,page,span=self.color_source()
            try:
                page.draw_rect(pymupdf.Rect(span['bbox']),color=None,fill=fill)
                self.assertEqual(color.screen(page,span)['status'],'withheld')
            finally:doc.close()

    def test_wrong_cid_color_or_rendering_never_becomes_supported(self):
        for mode in ('cid','color','opacity','rotation'):
            doc,page,span=self.color_source()
            try:
                forged=copy.deepcopy(span)
                if mode=='cid':c=forged['chars'][0];forged['chars']=[(c[0],17,*c[2:])]
                elif mode=='color':forged['color']=(.8,.1,.2)
                elif mode=='opacity':forged['opacity']=.5
                else:forged['dir']=(0.,1.)
                self.assertEqual(color.screen(page,forged)['status'],'withheld')
            finally:doc.close()

    def test_nonembedded_font_and_black_span_do_not_bypass_existing_recipe(self):
        with pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((40,60),'191.5',color=(.5,.3,.1))
            self.assertEqual(color.screen(page,page.get_texttrace()[0])['status'],'withheld')

    def test_original_closed_triangle_has_exact_cap_and_unmoved_apex(self):
        words,lines=self.graph();before=copy.deepcopy(lines);r=leaders.discover(words,lines,lambda:None)
        pair=r[0]['roof_pairs'][0];self.assertEqual(pair['status'],'closed_original_section_triangle_candidate')
        self.assertEqual(pair['source_apex_pdf_unrotated'],[50,70]);self.assertEqual(lines,before)
        self.assertEqual(pair['cap_source_ids'],['cap']);self.assertFalse(pair['geometry_export_authorized'])

    def test_longer_foreground_base_is_not_clipped_into_roof_cap(self):
        words,lines=self.graph(long_cap=True);pair=leaders.discover(words,lines,lambda:None)[0]['roof_pairs'][0]
        self.assertEqual(pair['cap_source_ids'],[]);self.assertEqual(pair['status'],'section_roof_boundary_or_visibility_held')

    def test_nearby_but_separate_slope_endpoint_is_not_snapped(self):
        words,lines=self.graph(gap=.1);pair=leaders.discover(words,lines,lambda:None)[0]['roof_pairs'][0]
        self.assertEqual(pair['status'],'section_roof_boundary_or_visibility_held')
        self.assertGreater(pair['source_apex_endpoint_gaps_pdf_points'][0],0)

    def test_missing_head_or_failed_word_screen_keeps_boundary_held(self):
        for mode in ('head','visibility'):
            words,lines=self.graph()
            if mode=='head':lines=[l for l in lines if l['id']!='head-left']
            else:words[0]['status']='numeric_source_glyphs_held'
            r=leaders.discover(words,lines,lambda:None)[0]['roof_pairs'][0]
            self.assertEqual(r['status'],'section_roof_boundary_or_visibility_held')

    def test_multiple_source_roof_slopes_are_retained_as_alternatives(self):
        words,lines=self.graph();extra=copy.deepcopy(lines[3]);extra.update(id='inner',source_endpoints_pdf_unrotated=[[35,100],[50,70]]);lines.append(extra)
        pairs=leaders.discover(words,lines,lambda:None)[0]['roof_pairs']
        self.assertEqual(len(pairs),2);self.assertEqual(sum(p['status']=='closed_original_section_triangle_candidate' for p in pairs),1)

    def test_line_ink_receipts_fail_when_source_stroke_is_overpainted(self):
        with pymupdf.open() as doc:
            page=doc.new_page();page.draw_line((20,30),(100,30),color=(.5,.3,.1),width=1)
            line={'id':'line','source_endpoints_pdf_unrotated':[[20,30],[100,30]],'color_rgb':[.5,.3,.1]}
            self.assertTrue(leaders.line_pixels(page,line)['all_samples_supported'])
            page.draw_rect((40,25,80,35),color=None,fill=(1,1,1))
            self.assertFalse(leaders.line_pixels(page,line)['all_samples_supported'])

    def test_complete_replay_keeps_parent_bytes_and_no_wall_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));before=args[2].read_bytes();r=evidence.build(*args)
            self.assertEqual(r,evidence.build(*args));self.assertEqual(args[2].read_bytes(),before)
            self.assertEqual(r['counts']['closed_section_roof_pairs'],1)
            self.assertEqual(r['counts']['agreeing_height_comparisons'],1)
            self.assertFalse(r['wall_closure_authorized']);self.assertEqual(r['world_geometry_additions'],0)

    def test_early_and_late_work_exhaustion_clear_all_partial_results(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args,max_checks=1)
            self.assertEqual(r['status'],'section_roof_evidence_budget_withheld')
            with patch.object(evidence,'comparisons',side_effect=OverflowError('late')):r=evidence.build(*args)
            self.assertEqual(r['pages'],[]);self.assertEqual(r['height_comparisons'],[])

    def test_changed_pdf_or_saved_output_is_rejected(self):
        for mode in ('pdf','cache'):
            with tempfile.TemporaryDirectory() as temp:
                args=self.fixture(Path(temp))
                if mode=='pdf':next(args[1].glob('*.pdf')).write_bytes(b'changed')
                else:r=evidence.build(*args);(Path(r['directory'])/'section-roof-evidence.json').write_text('{}')
                with self.assertRaises(ValueError):evidence.build(*args)

    def test_input_changed_during_comparison_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));original=evidence.comparisons
            def changed(*values):
                r=original(*values);args[2].write_text('{}');return r
            with patch.object(evidence,'comparisons',side_effect=changed),self.assertRaises(ValueError):evidence.build(*args)

    def test_bad_work_limit_and_nonliteral_source_label_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp))
            for limit in (True,0,2000001):
                with self.assertRaises(ValueError):evidence.build(*args,max_checks=limit)
            with self.assertRaises(ValueError):evidence.build(*args,level_text='191.5 extra')

    def test_split_numeric_word_keeps_both_original_trace_fragments(self):
        with pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((40,60),'191',fontsize=10)
            x=40+pymupdf.get_text_length('191',fontsize=10)
            page.insert_text((x,60),'.5',fontsize=10.16)
            words,screens=leaders.numeric_words(page,'191.5',lambda:None)
            self.assertEqual(len(words),1);self.assertEqual(len(words[0]['trace_indices']),2)
            self.assertEqual(words[0]['status'],'source_numeric_glyph_candidate')

    def test_disagreeing_model_heights_remain_held(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.fixture(Path(temp));r=evidence.build(*args)
            model=json.loads(args[2].read_text())['models'][0];model['mesh']['vertices'][4][2]+=1
            checks=evidence.comparisons(r['pages'],[model],lambda:None)
            self.assertEqual(checks[0]['status'],'section_height_comparison_held')
            self.assertFalse(checks[0]['wall_closure_authorized'])
