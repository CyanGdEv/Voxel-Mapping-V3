"""Original-page paper alternatives and exact native caption fragments."""
import copy
import hashlib
import unittest

import pymupdf

from voxel_mapper import architectural_graph, architectural_view_layout as captions
from voxel_mapper import ordinary_surfaces, planning_outline_semantics as semantics
from voxel_mapper import planning_surface_footprints as surfaces
from voxel_mapper import planning_area_layout as area
from voxel_mapper import planning_area_scale as scales
from voxel_mapper import planning_component_measurements as measurements
from voxel_mapper.building_spec import digest


class PaperScaleTests(unittest.TestCase):
    def source(self, *, paper='A1', rows=('1/250 @ A1', '1/500 @ A3'),
               hidden=False, duplicate=False, split=False, clutter=False, rotation=0,
               size_ratio=1.027, cropped=False, split_scales=False, hidden_scale=False,
               scale_y=430, paper_note=None, title='Site Plan Proposed showing Woodland Path'):
        doc=pymupdf.open(); self.addCleanup(doc.close)
        width,height=(2384,1684) if paper=='A1' else (1191,842)
        page=doc.new_page(width=width,height=height)
        page.draw_rect((100,100,180,180));page.insert_text((110,130),'Building',fontsize=8)
        page.draw_rect((190,100,260,180));page.insert_text((200,130),'Path',fontsize=8)
        if split:
            x=70
            for i,text in enumerate(('Site',' Plan',' Proposed',' ','showing',' Woodland',' Path')):
                size=10*(size_ratio if i==0 else 1)
                page.insert_text((x,400),text,fontsize=size)
                x+=pymupdf.get_text_length(text,fontsize=size)
        else:page.insert_text((70,400),title,fontsize=10)
        if clutter:
            page.insert_text((150,400.2),'AT 006731',fontsize=3,fontname='cour')
        for i,text in enumerate(rows):
            if split_scales:
                x=90
                for part in (text.split('@')[0], '@', text.split('@')[1], ' '):
                    page.insert_text((x,scale_y+i*13),part,fontsize=10)
                    x+=pymupdf.get_text_length(part,fontsize=10)
            else:page.insert_text((90,scale_y+i*13),text,fontsize=10)
        if hidden_scale:page.draw_rect((122,scale_y-10,147,scale_y+3),color=None,fill=(1,1,1))
        if paper_note:page.insert_text((500,600),paper_note,fontsize=10)
        if hidden:page.draw_rect((68,388,315,405),color=None,fill=(1,1,1))
        if duplicate:page.insert_text((70,500),'Proposed Ground Floor Plan | 1:100',fontsize=10)
        if cropped:page.set_cropbox(pymupdf.Rect(0,0,width-5,height))
        page.set_rotation(rotation)
        sha=hashlib.sha256(doc.tobytes()).hexdigest()
        graph=architectural_graph.build([]);graph.update(document_sha256=sha,page=1)
        layout=captions.review(page,sha,1,graph)
        mm=measurements.page_evidence(page,sha,1,layout,None)
        return page,sha,layout,mm

    def run_area(self, **kwargs):
        page,sha,layout,mm=self.source(**kwargs)
        _,_,report=ordinary_surfaces.page_candidates(page,sha,1)
        inventory=report['source_outline_inventory'];assoc=semantics.page_candidates(page,sha,1,inventory)
        pack=surfaces.page_candidates(page,sha,1,inventory,assoc)
        result=area.page_layout(page,sha,1,layout,inventory,assoc,None,pack)
        area.validate_layout(result)
        return result

    def test_paper_alternatives_select_original_page_and_keep_source_scale_rows(self):
        for paper,denominator in (('A1',250),('A3',500)):
            with self.subTest(paper=paper):
                result=self.run_area(paper=paper)
                self.assertTrue(result['analysis_complete'])
                self.assertEqual(result['shared_frame']['printed_scale_denominator'],denominator)
                self.assertEqual(len(result['candidates']),2)
                self.assertEqual(result['source_context']['scale_resolution']['selected_paper_size'],paper)
                self.assertEqual([r['paper_size'] for r in result['source_context']['caption_layout']['page_scale_claims']],['A1','A3'])
                self.assertFalse(result['physical_scale_verified'])
                self.assertFalse(result['world_placement_eligible'])
                self.assertEqual(result['world_geometry_additions'],0)
                self.assertTrue(all(r['height_m'] is None for r in result['candidates']))
                rows=sorted(result['candidates'],key=lambda r:r['nominal_bounds_m'][0])
                self.assertAlmostEqual(rows[1]['nominal_bounds_m'][0]-rows[0]['nominal_bounds_m'][0],90*denominator*.0254/72)

    def test_native_split_font_transforms_whitespace_and_other_font_overlap(self):
        _,_,layout,mm=self.source(split=True,clutter=True)
        self.assertEqual(len(layout['sheet_titles']),1)
        row=layout['sheet_titles'][0]
        self.assertEqual(row['glyph_screen']['status'],'raster_consistent_candidate')
        self.assertEqual(row['text'],'Site Plan Proposed showing Woodland Path')
        self.assertEqual(len(row['caption_fragments']),7)
        self.assertEqual(scales.resolve(row,layout,mm)['printed_scale_denominator'],250)
        _,_,bad,_=self.source(split=True,size_ratio=1.1)
        self.assertEqual(bad['sheet_titles'],[])

    def test_conflicting_duplicate_missing_hidden_scales_and_competing_views_withhold(self):
        for kwargs in ({'rows':('1/250 @ A1','1/999 @ A3')},
                       {'rows':('1/250 @ A1','1/500 @ A1')},
                       {'rows':('1/250 @ A2',)}, {'rows':('1/250',)},
                       {'rows':('1/250 @ A1','1/500 @ A3','1/100 @ A4')},
                       {'hidden':True},{'duplicate':True},{'cropped':True},
                       {'title':'Proposed Roof Plan'},{'title':'See Site Plan Proposed'}):
            with self.subTest(kwargs=kwargs):
                result=self.run_area(**kwargs)
                self.assertFalse(result['analysis_complete'])
                self.assertEqual(result['candidates'],[])
                self.assertIsNone(result['shared_frame'])

    def test_rotation_preserves_native_scale_and_source_geometry(self):
        a=self.run_area();b=self.run_area(rotation=90)
        self.assertEqual(a['shared_frame']['native_to_nominal_local_affine'],b['shared_frame']['native_to_nominal_local_affine'])
        self.assertEqual([r['geometry_nominal_local'] for r in a['candidates']],[r['geometry_nominal_local'] for r in b['candidates']])

    def test_paper_resolution_receipt_and_dimensions_cannot_be_overridden(self):
        result=self.run_area()
        for key in ('selected_paper_size','printed_scale_denominator','selected_scale_sha256'):
            bad=copy.deepcopy(result);bad['source_context']['scale_resolution'][key]='changed'
            bad['id']=digest({k:v for k,v in bad.items() if k!='id'})
            with self.assertRaises(ValueError):area.validate_layout(bad)
        _,_,layout,mm=self.source();mm['matching_paper_sizes']=['A3']
        with self.assertRaises(ValueError):scales.resolve(layout['sheet_titles'][0],layout,mm)

    def test_literal_scale_parser_rejects_prose_and_invalid_denominators(self):
        self.assertEqual(scales.printed_scale('1/250 @ A1'),{'printed_denominator':250,'paper_size':'A1'})
        for text in ('See 1/250 @ A1','1/0 @ A1','1/99999 @ A1','1/250 @ A6','1/250 @ A1 and 1/500 @ A3'):
            self.assertIsNone(scales.printed_scale(text),text)

    def test_fragmented_scale_whitespace_is_retained_and_hidden_paper_cannot_select(self):
        _,_,layout,mm=self.source(split_scales=True)
        self.assertEqual(len(layout['page_scale_claims']),2)
        self.assertTrue(all(len(row['caption_fragments'])==4 for row in layout['page_scale_claims']))
        self.assertEqual(scales.resolve(layout['sheet_titles'][0],layout,mm)['selected_paper_size'],'A1')
        result=self.run_area(split_scales=True,hidden_scale=True)
        self.assertFalse(result['analysis_complete'])
        self.assertEqual(result['candidates'],[])

    def test_page_paper_scale_cannot_be_inherited_by_a_floor_view_or_distant_title(self):
        for kwargs in ({'title':'Proposed Ground Floor Plan'}, {'scale_y':650}):
            result=self.run_area(**kwargs)
            self.assertFalse(result['analysis_complete'])
            self.assertIsNone(result['shared_frame'])

    def test_colon_paper_alternatives_are_not_conflicting_sheet_declarations(self):
        result=self.run_area(rows=('1:250 @ A1','1:500 @ A3'))
        self.assertTrue(result['analysis_complete'])
        self.assertEqual(result['shared_frame']['printed_scale_denominator'],250)
        for rows in (('1:250 @ A1','1:999 @ A3'),('1:250 @ A1','1:500 @ A1')):
            result=self.run_area(rows=rows)
            self.assertFalse(result['analysis_complete'])
        result=self.run_area(rows=('1:250 @ A1','1:500 @ A3'),paper_note='As indicated @ A2')
        self.assertFalse(result['analysis_complete'])


if __name__=='__main__':unittest.main()
