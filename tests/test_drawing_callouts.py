import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from tests.test_drawing_annotations import trace
from voxel_mapper.drawing_callouts import page_callouts,legend_entries
from voxel_mapper.drawing_annotations import contiguous_runs


def line(a,b,seq):
    return {'type':'s','level':0,'items':[('l',pymupdf.Point(a),pymupdf.Point(b))],'closePath':False,'seqno':seq,'dashes':'[] 0','stroke_opacity':1,'rect':pymupdf.Rect(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1]))}


def triangle(seq=4):
    points=[(50,5),(42,3),(42,7)]
    return {'type':'fs','level':0,'items':[('l',pymupdf.Point(points[i]),pymupdf.Point(points[(i+1)%3])) for i in range(3)],'seqno':seq,'fill_opacity':1,'rect':pymupdf.Rect(42,3,50,7)}


class Page:
    def __init__(self):
        self.paths=[line((12,5),(30,5),2),line((30,5),(50,5),3),triangle()]
        self.traces=[trace('1',(0,0,10,10),5),trace('1. Roof - Thatched effect roof tiles.',(100,100,300,110),6)]
    def get_drawings(self,extended=True):return self.paths
    def get_texttrace(self):return self.traces


class CalloutTests(unittest.TestCase):
    def test_unique_chain_arrow_and_exact_legend_retained(self):
        rows,report=page_callouts(Page(),'a'*64,1)
        self.assertEqual(rows[0]['status'],'explicit_material_anchor_candidate')
        self.assertEqual(rows[0]['target_page_point'],(50,5))
        self.assertEqual(rows[0]['component_class_candidate'],'roof_surface')
        self.assertEqual(rows[0]['leader_candidates'][0]['leader_paint_seqnos'],[2,3])
        self.assertFalse(rows[0]['accepted_feature']);self.assertFalse(rows[0]['outline_identity_verified'])

    def test_branched_chain_and_missing_arrow_withheld(self):
        page=Page();page.paths.append(line((30,5),(30,20),8))
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_ambiguous_or_missing_connection')
        page=Page();page.paths.pop()
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_ambiguous_or_missing_connection')

    def test_duplicate_legend_and_arrow_do_not_select_nearest(self):
        page=Page();page.traces.append(trace('1. Roof - Metal sheeting.',(100,200,300,210),9))
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(len(rows[0]['legend_candidates']),2)
        self.assertEqual(rows[0]['status'],'withheld_ambiguous_or_missing_connection')
        page=Page();page.paths.append(triangle(9))
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_ambiguous_or_missing_connection')

    def test_clipped_paths_are_excluded(self):
        page=Page();page.paths[0]['level']=1
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_ambiguous_or_missing_connection')

    def test_later_fill_or_hidden_legend_withheld(self):
        page=Page();page.traces[1]['opacity']=0
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_label_or_legend_visibility')
        page=Page();page.paths.append({'type':'f','items':[('re',pymupdf.Rect(0,0,10,10),1)],'level':0,'seqno':10,'rect':pymupdf.Rect(0,0,10,10),'fill_opacity':1})
        rows,_=page_callouts(page,'a'*64,1);self.assertEqual(rows[0]['status'],'withheld_label_or_legend_visibility')

    def test_page_budget_rejected(self):
        with self.assertRaisesRegex(ValueError,'budget'):page_callouts(Page(),'a'*64,1,max_paths=1)

    def test_legend_wrap_retains_material_line(self):
        runs=[trace('2. Upper Section of walls - Aged and',(100,100,300,110),0),trace('weathered effect horizontal timber cladding.',(100,112,320,122),2)]
        entries=legend_entries(contiguous_runs(runs))
        self.assertIn('timber cladding',entries['2'][0]['legend_text'])
        self.assertEqual(entries['2'][0]['trace_indices'],[0,1])

    def test_pipeline_callouts_do_not_become_features(self):
        from voxel_mapper.park_pipeline import run as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','sources':[]}))
            (root/'job.json').write_text(json.dumps({'manifest':'manifest.json','work_directory':'work','drawing_callouts':{'enabled':True,'documents':'documents.json'}}))
            receipt={'status':'unplaced_component_anchor_evidence','contract':{},'callouts_sha256':'a'*64}
            with patch('voxel_mapper.drawing_callouts.run',return_value=receipt):state=pipeline(root/'job.json','compile')
            self.assertEqual(state['stages']['drawing_callouts'],receipt)
            self.assertEqual(state['stages']['reconstruction']['status'],'awaiting_normalized_geometry')
