import json
from pathlib import Path
import tempfile
import unittest

import pymupdf
from shapely.geometry import shape,Point

from voxel_mapper.planning_hatch_regions import page_review,recover,write_overlay
from tests.test_planning_hatch_regions import operations


def solid_source(document, *, backplates=False):
    page=document.new_page(width=800,height=400)
    page.insert_text((650,85),'Existing Paving with levels',fontsize=8)
    content=b'q 0.9 0.8 0.7 rg 580 300 60 30 re f 40 30 300 180 re 80 60 30 30 re f* Q'
    if backplates:
        page.insert_text((50,150),'Plaza',fontsize=12)
        span=next(t for t in page.get_texttrace() if ''.join(chr(c[0]) for c in t['chars'])=='Plaza')
        inverse=~page.transformation_matrix;r=pymupdf.Rect(span['bbox'])*inverse
        content+=f' q 0.9 0.8 0.7 rg {r.x0} {r.y0} {r.width} {r.height} re f Q'.encode()
        page.insert_text((150,150),'Sign',fontsize=12)
        page.insert_text((150,170),'Entrance',fontsize=12)
        # One source-authored L-shaped backplate, matching both text lines.
        trace=page.get_texttrace();sign=next(t for t in trace if ''.join(chr(c[0]) for c in t['chars'])=='Sign')
        entrance=next(t for t in trace if ''.join(chr(c[0]) for c in t['chars'])=='Entrance')
        a=pymupdf.Rect(sign['bbox'])*inverse;b=pymupdf.Rect(entrance['bbox'])*inverse
        content+=(f' q 0.9 0.8 0.7 rg {a.x0} {a.y1} m {a.x1} {a.y1} l '
                  f'{a.x1} {a.y0-3} l {b.x1} {a.y0-3} l {b.x1} {b.y0} l {b.x0} {b.y0} l h f Q').encode()
    paint=document.get_new_xref();document.update_object(paint,'<< >>');document.update_stream(paint,content)
    original=page.get_contents();document.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [paint]+original)+']')
    return page


class ExistingPavingTests(unittest.TestCase):
    def test_solid_only_page_recovers_existing_plaza_with_hole(self):
        with pymupdf.open() as document:
            page=solid_source(document);result=page_review(page,'a'*64,1)
            self.assertTrue(result['analysis_complete'],result.get('reason'))
            self.assertEqual(result['summary']['source_hatch_regions'],0)
            self.assertEqual(result['summary']['existing_paving_regions'],1)
            self.assertEqual(result['summary']['proposed_paving_regions'],0)
            candidate=next(r for r in result['records'] if r['legend_claim'])
            g=shape(candidate['geometry'])
            self.assertEqual(g.area,53100)
            self.assertFalse(g.contains(Point(90,70)))
            self.assertEqual(candidate['solid_colour_components'],[.9,.8,.7])
            self.assertFalse(candidate['world_placement_eligible'])

    def test_solid_color_space_and_graphics_restore(self):
        rows,_=recover(operations('0.9 0.8 0.7 rg 0 0 20 20 re f q 0.5 g 20 0 20 20 re f Q 40 0 20 20 re f 0 1 1 0 k 60 0 20 20 re f'),{},[0,0,800,400],include_solid_fills=True)
        self.assertEqual([r['solid_colour_space'] for r in rows],['/DeviceRGB','/DeviceGray','/DeviceRGB','/DeviceCMYK'])
        self.assertEqual(rows[0]['appearance_sha256'],rows[2]['appearance_sha256'])
        self.assertNotEqual(rows[0]['appearance_sha256'],rows[1]['appearance_sha256'])

    def test_device_color_scn_and_unknown_color_space(self):
        rows,_=recover(operations('/DeviceRGB cs 0.9 0.8 0.7 scn 0 0 20 20 re f /Unknown cs 0.9 0.8 0.7 scn 20 0 20 20 re f'),{},[0,0,800,400],include_solid_fills=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['solid_colour_components'],[.9,.8,.7])

    def test_exact_solid_color_has_no_rgb_tolerance(self):
        with pymupdf.open() as document:
            page=solid_source(document);paint=page.get_contents()[0]
            data=document.xref_stream(paint).replace(b'40 30 300 180 re',b'0.90001 0.8 0.7 rg 40 30 300 180 re')
            document.update_stream(paint,data);result=page_review(page,'b'*64,1)
            self.assertEqual(result['summary']['existing_paving_regions'],0)

    def test_rectangular_and_multiline_backplates_not_paving(self):
        with pymupdf.open() as document:
            page=solid_source(document,backplates=True);result=page_review(page,'c'*64,1)
            self.assertTrue(result['analysis_complete'],result.get('reason'))
            self.assertEqual(result['summary']['existing_paving_regions'],1)
            self.assertEqual(result['summary']['text_background_fills_withheld'],2)
            masks=[r for r in result['records'] if 'text_background_evidence' in r]
            self.assertTrue(all(r['legend_claim'] is None for r in masks))
            self.assertTrue(all(not r['text_background_evidence']['physical_role_inferred'] for r in masks))

    def test_duplicate_conflicting_existing_and_new_solid_keys_withhold(self):
        with pymupdf.open() as document:
            page=solid_source(document);page.insert_text((650,95),'New Paving with levels',fontsize=8)
            result=page_review(page,'d'*64,1)
            self.assertEqual(result['summary']['existing_paving_regions'],0)
            self.assertEqual(result['summary']['proposed_paving_regions'],0)

    def test_solid_quota_failures_clear_all_records(self):
        with pymupdf.open() as document:
            page=solid_source(document,backplates=True)
            for options in ({'max_records':1},{'max_text_mask_checks':1},{'max_overlay_work':1}):
                result=page_review(page,'e'*64,1,options=options)
                self.assertFalse(result['analysis_complete'],(options,result.get('summary')))
                self.assertEqual(result['records'],[])
                self.assertNotIn('summary',result)

    def test_retraced_existing_fill_uses_original_pdf_fill_rule(self):
        with pymupdf.open() as document:
            page=solid_source(document);paint=page.get_contents()[0]
            content=document.xref_stream(paint).replace(b'40 30 300 180 re 80 60 30 30 re f*',
                b'40 30 m 340 30 l 340 210 l 40 210 l 40 30 l 80 60 l 80 90 l 110 90 l 110 60 l 80 60 l 40 30 l h f*')
            document.update_stream(paint,content)
            result=page_review(page,'a'*64,1)
            self.assertTrue(result['analysis_complete'],result.get('reason'))
            self.assertEqual(result['summary']['existing_paving_regions'],1)
            region=next(r for r in result['records'] if r['legend_claim'])
            self.assertEqual(region['fill_rule_resolution'],'source_fill_rule_arrangement')
            self.assertEqual(shape(region['geometry']).area,53100)
            self.assertFalse(shape(region['geometry']).contains(Point(90,70)))
            self.assertEqual(result['work']['source_passes'],2)
            for options in ({'max_fill_rule_work':1},{'max_scan_operations':1}):
                limited=page_review(page,'a'*64,1,options=options)
                self.assertFalse(limited['analysis_complete'])
                self.assertEqual(limited['records'],[])

    def test_self_crossing_winding_and_retraced_edges(self):
        from voxel_mapper.planning_hatch_regions import _source_fill_arrangement
        bowtie=[[(0,0),(40,40),(0,40),(40,0),(0,0)]]
        g=_source_fill_arrangement(bowtie,True,{'checks':0},100000)
        self.assertEqual(g.area,800)
        self.assertEqual(g.geom_type,'MultiPolygon')
        ring=[(0,0),(40,0),(40,40),(0,40),(0,0)]
        self.assertEqual(_source_fill_arrangement([ring,ring],True,{'checks':0},100000).area,0)
        self.assertEqual(_source_fill_arrangement([ring,ring],False,{'checks':0},100000).area,1600)
        self.assertEqual(_source_fill_arrangement([ring,list(reversed(ring))],False,{'checks':0},100000).area,0)

    def test_cross_column_path_requires_original_legend_backplate(self):
        for panel in (False,True):
            with self.subTest(panel=panel),pymupdf.open() as document:
                page=solid_source(document);paint=page.get_contents()[0]
                content=b'q 0.9 0.8 0.7 rg 40 30 720 180 re f '
                if panel:content+=b'1 g 560 250 240 150 re f '
                content+=b'0.9 0.8 0.7 rg 580 300 60 30 re f Q'
                document.update_stream(paint,content)
                result=page_review(page,'b'*64,1)
                self.assertTrue(result['analysis_complete'],result.get('reason'))
                self.assertEqual(result['summary']['existing_paving_regions'],1 if panel else 0)
                if panel:
                    region=next(r for r in result['records'] if r['legend_claim'])
                    self.assertEqual(shape(region['geometry']).bounds[2],760)
                    self.assertEqual(len(result['legend_backplates']),1)

    def test_legend_occlusion_changes_only_review_display_geometry(self):
        with pymupdf.open() as document:
            page=solid_source(document);paint=page.get_contents()[0]
            document.update_stream(paint,b'q 0.9 0.8 0.7 rg 40 300 720 90 re f 1 g 560 250 240 150 re f 0.9 0.8 0.7 rg 580 300 60 30 re f Q')
            result=page_review(page,'c'*64,1)
            self.assertEqual(result['summary']['existing_paving_regions'],1)
            region=next(r for r in result['records'] if r['legend_claim'])
            self.assertEqual(shape(region['geometry']).bounds[2],760)
            self.assertEqual(shape(region['review_geometry']).bounds[2],560)
            self.assertFalse(region['later_overpaint_visibility_verified'])

    def test_overlay_omits_unclassified_solid_paint(self):
        with pymupdf.open() as document,tempfile.TemporaryDirectory() as directory:
            page=solid_source(document);page.draw_rect((5,5,30,30),fill=(0,1,0),color=None)
            result=page_review(page,'f'*64,1)
            self.assertEqual(result['summary']['existing_paving_regions'],1)
            from voxel_mapper.planning_area_pilot import _preview
            root=Path(directory);preview=_preview(page,root/'page.png',800)
            overlay=write_overlay(result,preview,root/'paving.svg')
            svg=(root/'paving.svg').read_text()
            self.assertEqual(svg.count('<path '),1)
            self.assertEqual(overlay['existing_paving_regions'],1)


if __name__=='__main__':unittest.main()
