import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import CancelledError

import pymupdf
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, ArrayObject, NumberObject, ByteStringObject
from shapely.geometry import shape, Point

from voxel_mapper.planning_hatch_regions import recover, pattern_signature, page_review, write_overlay


def pattern(data=b'0.5 g 0 0 8 8 re f', matrix=None, palette=None):
    p=DecodedStreamObject();p.set_data(data)
    for k,v in {'/Type':'/Pattern'}.items():p[NameObject(k)]=NameObject(v)
    for k,v in {'/PatternType':1,'/PaintType':1,'/TilingType':1,'/XStep':8,'/YStep':8}.items():p[NameObject(k)]=NumberObject(v)
    p[NameObject('/BBox')]=ArrayObject(map(NumberObject,[0,0,8,8]))
    p[NameObject('/Resources')]=DictionaryObject()
    if matrix:p[NameObject('/Matrix')]=ArrayObject(map(NumberObject,matrix))
    if palette is not None:p[NameObject('/PaletteWitness')]=ByteStringObject(palette)
    return p


def operations(content):
    from pypdf.generic import ContentStream
    source=DecodedStreamObject();source.set_data(content.encode())
    return ContentStream(source,None).operations


def source(document):
    page=document.new_page(width=800,height=400)
    page.insert_text((650,85),'New Paving with levels',fontsize=8)
    xref=document.get_new_xref()
    document.update_object(xref,'<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 8 8] /XStep 8 /YStep 8 /Resources << >> >>')
    document.update_stream(xref,b'0.5 g 0 0 8 8 re f')
    resources=int(document.xref_get_key(page.xref,'Resources')[1].split()[0])
    document.xref_set_key(resources,'Pattern',f'<< /P1 {xref} 0 R >>')
    paint=document.get_new_xref();document.update_object(paint,'<< >>')
    document.update_stream(paint,b'q /Pattern cs /P1 scn 580 300 60 30 re f 20 100 m 20 200 300 200 300 100 c 300 50 l 20 50 l h f Q')
    original=page.get_contents();document.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [paint]+original)+']')
    return page


class HatchTests(unittest.TestCase):
    def run_content(self, content, **kwargs):
        return recover(operations(content),{'/Pattern':{'/P1':pattern()}},[0,0,800,400],**kwargs)

    def test_pattern_identity_resolves_palette_bytes_and_linear_transform(self):
        a=pattern_signature(pattern(palette=b'red'))
        self.assertEqual(a['appearance_sha256'],pattern_signature(pattern(matrix=[1,0,0,1,80,2],palette=b'red'))['appearance_sha256'])
        self.assertNotEqual(a['appearance_sha256'],pattern_signature(pattern(palette=b'blue'))['appearance_sha256'])
        self.assertNotEqual(a['appearance_sha256'],pattern_signature(pattern(matrix=[2,0,0,1,0,0],palette=b'red'))['appearance_sha256'])
        self.assertNotEqual(a['appearance_sha256'],pattern_signature(pattern(data=b'other',palette=b'red'))['appearance_sha256'])

    def test_pattern_resource_budgets(self):
        with self.assertRaisesRegex(ValueError,'budget'):pattern_signature(pattern(),1)

    def test_curved_geometry_keeps_original_controls(self):
        rows,_=self.run_content('/Pattern cs /P1 scn 20 100 m 20 200 300 200 300 100 c 300 50 l 20 50 l h f')
        self.assertEqual(rows[0]['curved_operators'],1)
        self.assertEqual(rows[0]['source_operators'][1]['points'],[[20.,100.],[20.,200.],[300.,200.],[300.,100.]])
        self.assertGreater(shape(rows[0]['geometry']).area,14000)
        self.assertTrue(shape(rows[0]['geometry']).contains(Point(150,160)))

    def test_control_distance_is_to_segment_not_infinite_line(self):
        rows,_=self.run_content('/Pattern cs /P1 scn 10 10 m -200 10 300 10 20 10 c 20 30 l 10 30 l h f')
        self.assertFalse(rows)  # collinear overshoot self-overlaps: no repaired ring

    def test_even_odd_holes_and_nested_clip_restoration(self):
        rows,_=self.run_content('q 0 0 100 100 re W n q 0 0 50 100 re W n /Pattern cs /P1 scn 0 0 100 100 re 10 10 20 20 re f* Q Q /Pattern cs /P1 scn 200 0 20 20 re f')
        self.assertEqual([shape(x['geometry']).area for x in rows],[4600,400])
        self.assertFalse(shape(rows[0]['geometry']).contains(Point(20,20)))
        self.assertEqual([len(r['clip_operation_indices']) for r in rows],[2,0])

    def test_transform_and_shorthand_preserved(self):
        rows,_=self.run_content('q 2 0 0 3 10 20 cm /Pattern cs /P1 scn 0 0 m 5 10 10 0 v 10 -5 l 0 -5 l h f Q')
        c=rows[0]['source_operators'][1]
        self.assertEqual(c['original_operator'],'v')
        self.assertEqual(c['points'],[[10.,20.],[10.,20.],[20.,50.],[30.,20.]])

    def test_pattern_colourspace_and_scope_do_not_leak(self):
        rows,_=self.run_content('q /Pattern cs /P1 scn 0 0 30 30 re f Q 40 0 30 30 re f /DeviceRGB cs /P1 scn 80 0 30 30 re f')
        self.assertEqual(len(rows),1)

    def test_nonopaque_and_optional_scopes_withheld(self):
        resources={'/Pattern':{'/P1':pattern()},'/ExtGState':{'/Fade':DictionaryObject({NameObject('/ca'):NumberObject(0)})}}
        rows,work=recover(operations('q /Fade gs /Pattern cs /P1 scn 0 0 30 30 re f Q /OC /Layer BDC /Pattern cs /P1 scn 40 0 30 30 re f EMC'),resources,[0,0,800,400])
        self.assertEqual(rows,[])
        self.assertEqual(work['counts']['unsupported_graphics_or_clip_scope'],2)

    def test_curved_clip_is_preserved(self):
        rows,_=self.run_content('0 0 m 0 100 100 100 100 0 c h W n /Pattern cs /P1 scn 0 0 100 100 re f')
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['source_geometry_intersected'])
        self.assertLess(shape(rows[0]['geometry']).area,10000)

    def test_quota_failures_never_return_partial_records(self):
        text='/Pattern cs /P1 scn 0 0 30 30 re f 40 0 30 30 re f'
        for limits in ({'max_operations':1},{'max_records':1},{'max_path_operators':1},{'max_points':4},{'max_overlay_work':1}):
            with self.subTest(limits=limits),self.assertRaisesRegex(ValueError,'budget'):self.run_content(text,limits=limits)

    def test_unbalanced_source_and_cancellation(self):
        for text in ('Q','q','0 0 m 0 10 l W'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.run_content(text)
        with self.assertRaises(CancelledError):self.run_content('q Q',cancelled=lambda:True)

    def test_full_page_legend_and_overlay_rotation(self):
        with pymupdf.open() as doc,tempfile.TemporaryDirectory() as directory:
            page=source(doc);pin=hashlib.sha256(page.read_contents()).hexdigest()
            result=page_review(page,'a'*64,1)
            self.assertTrue(result['analysis_complete'],result.get('reason'))
            self.assertEqual(result['summary'],{'source_hatch_regions':2,'legend_associated_paving_regions':1,'curved_paving_regions':1})
            self.assertEqual(result['records'][1]['legend_claim']['printed_state'],'new')
            self.assertFalse(result['world_placement_eligible'])
            from voxel_mapper.planning_area_pilot import _preview
            for angle in (0,90,180,270):
                page.set_rotation(angle)
                rotated=page_review(page,'a'*64,1)
                for original,turned in zip(result['records'],rotated['records']):
                    self.assertEqual(original['geometry'],turned['geometry'])
                    self.assertEqual(original['source_operators'],turned['source_operators'])
                    self.assertEqual(original['id'],turned['id'])
                self.assertEqual(result['summary'],rotated['summary'])
                preview=_preview(page,Path(directory)/'page.png',800)
                overlay=write_overlay(result,preview,Path(directory)/'hatch.svg')
                self.assertEqual(overlay['legend_associated_paving_regions'],1)
            self.assertEqual(pin,hashlib.sha256(page.read_contents()).hexdigest())

    def test_hidden_and_duplicate_legends_cannot_transfer(self):
        with pymupdf.open() as doc:
            page=source(doc);page.draw_rect((645,70,790,90),color=None,fill=(1,1,1))
            result=page_review(page,'b'*64,1)
            self.assertTrue(result['analysis_complete'])
            self.assertEqual(result['summary']['legend_associated_paving_regions'],0)
        with pymupdf.open() as doc:
            page=source(doc);page.insert_text((650,95),'New Paving with levels',fontsize=8)
            result=page_review(page,'b'*64,1)
            self.assertEqual(result['summary']['legend_associated_paving_regions'],0)

    def test_translucent_source_is_reviewed_with_exact_opacity(self):
        from pypdf.generic import FloatObject
        resources={'/Pattern':{'/P1':pattern()},'/ExtGState':{'/Half':DictionaryObject({NameObject('/ca'):FloatObject(.5)})}}
        rows,_=recover(operations('q /Half gs /Pattern cs /P1 scn 0 0 30 30 re f Q /Pattern cs /P1 scn 40 0 30 30 re f'),resources,[0,0,800,400])
        self.assertEqual([r['fill_opacity'] for r in rows],[.5,1.])

    def test_legend_opacity_must_match_source_region(self):
        with pymupdf.open() as doc:
            page=source(doc)
            resource=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resource,'ExtGState','<< /Half << /ca 0.5 >> >>')
            paint=page.get_contents()[0]
            doc.update_stream(paint,doc.xref_stream(paint).replace(b'20 100 m',b'/Half gs 20 100 m'))
            result=page_review(page,'f'*64,1)
            self.assertTrue(result['analysis_complete'],result.get('reason'))
            self.assertEqual(result['summary']['legend_associated_paving_regions'],0)
            self.assertEqual([r['fill_opacity'] for r in result['records']],[1.,.5])

    def test_complete_legend_continuation_withholds_transfer(self):
        with pymupdf.open() as doc:
            page=source(doc)
            x=650+pymupdf.get_text_length('New Paving with levels',fontsize=8)
            page.insert_text((x,85),' removed',fontsize=8)
            result=page_review(page,'e'*64,1)
            self.assertEqual(result['summary']['legend_associated_paving_regions'],0)

    def test_clip_witness_retains_curve_controls_and_fill_rule(self):
        rows,_=self.run_content('0 0 m 0 100 100 100 100 0 c h W* n /Pattern cs /P1 scn 0 0 100 100 re f')
        clip=rows[0]['clip_references'][0]
        self.assertTrue(clip['even_odd'])
        self.assertEqual(clip['source_operators'][1]['points'],[[0.,0.],[0.,100.],[100.,100.],[100.,0.]])

    def test_page_budgets_and_validation(self):
        with pymupdf.open() as doc:
            page=source(doc)
            for options in ({'max_content_bytes':1},{'max_output_bytes':1},{'max_operations':1},{'max_points':1}):
                result=page_review(page,'c'*64,1,options=options)
                self.assertFalse(result['analysis_complete']);self.assertEqual(result['records'],[])
            for options in ({'unknown':1},{'max_points':200001},{'max_points':True}):
                with self.assertRaises(ValueError):page_review(page,'c'*64,1,options=options)
            with self.assertRaises(ValueError):page_review(page,'bad',1)
            page.set_cropbox(pymupdf.Rect(0,0,700,400))
            self.assertFalse(page_review(page,'c'*64,1)['analysis_complete'])

    def test_pilot_integration_does_not_promote_hatches(self):
        with pymupdf.open() as doc:
            page=source(doc)
            from voxel_mapper.planning_area_pilot import _page
            result=_page(page,'d'*64,1,'site-plan')
            self.assertEqual(result['source_hatch_region_review']['summary']['legend_associated_paving_regions'],1)
            self.assertIn('legend_hatch_paving_requires_visibility_and_physical_validation',result['summary']['blockers'])
            self.assertFalse(result['area_layout']['candidates'])


if __name__=='__main__':unittest.main()
