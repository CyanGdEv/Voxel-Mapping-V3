import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper.drawing_annotations import categories,page_annotations,run,contiguous_runs


def trace(text,bbox,seq=0,direction=(1,0),opacity=1,kind=0,layer=''):
    return {'chars':[(ord(c),0,(bbox[0],bbox[1]),bbox) for c in text],'bbox':bbox,'dir':direction,'size':10,
            'seqno':seq,'opacity':opacity,'type':kind,'layer':layer}


class Page:
    rotation=90;mediabox=(0,0,600,800)
    def __init__(self,traces,paints):self.traces=traces;self.paints=paints
    def get_texttrace(self):return self.traces
    def get_bboxlog(self):return self.paints


class AnnotationTests(unittest.TestCase):
    def test_explicit_units_slope_and_untyped_values_stay_candidates(self):
        self.assertEqual(categories('1500 mm')[0]['value_m_candidate'],1.5)
        self.assertEqual(categories('1: 36 Slope Up')[0]['rise_per_run_candidate'],1/36)
        self.assertEqual(categories('1:100'),[])
        self.assertFalse(categories('185400')[0]['units_verified'])
        self.assertFalse(categories('Ridge 185.45')[0]['vertical_datum_verified'])
        self.assertEqual(categories('12 High Street'),[])

    def test_rotated_level_conflict_candidate_without_promotion(self):
        page=Page([trace('Ride Exit Bridge +185.80',(100,100,110,200),0,(0,-1)),trace('185400',(117,100,124,124),1,(0,-1))],[('fill-text',(100,100,110,200)),('fill-text',(117,100,124,124))])
        records,receipt=page_annotations(page,'a'*64,1)
        comparison=records[0]['numeric_level_comparison']
        self.assertEqual(comparison['status'],'conflicting_candidate_values')
        self.assertAlmostEqual(comparison['difference_m_candidate'],.4)
        self.assertFalse(comparison['association_verified'])
        self.assertTrue(all(not r['accepted_feature'] for r in records))
        self.assertEqual(receipt['rotation_degrees'],90)

    def test_ambiguous_neighbors_do_not_select_nearest(self):
        page=Page([trace('Shop Level +182.50',(0,0,100,10)),trace('182500',(5,12,50,20),1),trace('183500',(5,22,50,28),2)],[])
        records,_=page_annotations(page,'a'*64,1)
        self.assertEqual(len(records[0]['adjacent_numeric_candidates']),2)
        self.assertNotIn('numeric_level_comparison',records[0])

    def test_later_fill_overlap_and_invisible_text_withheld(self):
        page=Page([trace('Ridge 185.45',(0,0,100,10)),trace('182500',(0,20,50,30),1,opacity=0)],
                  [('fill-text',(0,0,100,10)),('fill-path',(0,0,100,10))])
        records,_=page_annotations(page,'a'*64,1)
        self.assertTrue(all(r['visibility_screen']=='withheld' for r in records))
        self.assertIn('later_fill_overlap_visibility_review_required',records[0]['visibility_reasons'])

    def test_layered_text_and_page_budgets_rejected(self):
        page=Page([trace('timber boarding',(0,0,100,10),layer='hidden')],[])
        records,_=page_annotations(page,'a'*64,1)
        self.assertEqual(records[0]['visibility_screen'],'withheld')
        with self.assertRaisesRegex(ValueError,'budget'):page_annotations(page,'a'*64,1,max_spans=0)

    def test_hash_bound_batch_cache_and_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pdf=root/'source.pdf'
            with pymupdf.open() as d:
                p=d.new_page();p.insert_text((50,50),'Shop Level +182.50');d.save(pdf)
            docs=root/'documents.json';docs.write_text(json.dumps([{'file':'source.pdf','sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}]))
            output=root/'out';report=run(docs,output)
            self.assertEqual(report['annotation_records'],1)
            self.assertEqual(report['world_geometry_additions'],0)
            self.assertEqual(run(docs,output),report)
            (output/'annotations.jsonl').write_text('')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):run(docs,output)
            pdf.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'pinned PDF'):run(docs,root/'changed')

    def test_pipeline_annotation_stage_does_not_become_feature_feed(self):
        from voxel_mapper.park_pipeline import run as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','sources':[]}))
            (root/'job.json').write_text(json.dumps({'manifest':'manifest.json','work_directory':'work','drawing_annotations':{'enabled':True,'documents':'documents.json'}}))
            report={'status':'unplaced_native_annotation_evidence','contract':{'version':'test'},'annotations_sha256':'a'*64}
            with patch('voxel_mapper.drawing_annotations.run',return_value=report) as inspect:
                state=pipeline(root/'job.json','compile');inspect.assert_called_once()
            self.assertEqual(state['stages']['drawing_annotations'],report)
            self.assertEqual(state['stages']['reconstruction']['status'],'awaiting_normalized_geometry')
            self.assertFalse((root/'work/geometry.sqlite').exists())

    def test_native_fragments_join_only_on_same_baseline(self):
        parts=[trace('1:',(0,0,10,10),0),trace('36',(11,0,21,10),2),trace(' Slope Up',(22,0,80,10),4)]
        joined=contiguous_runs(parts)
        self.assertEqual(len(joined),1)
        text=''.join(chr(c[0]) for c in joined[0]['chars']).strip()
        self.assertEqual(categories(text)[0]['kind'],'slope_ratio')
        self.assertEqual(joined[0]['trace_indices'],[0,1,2])
        parts[1]['chars'][0]=(ord('3'),0,(11,20),(11,20,21,30))
        self.assertGreater(len(contiguous_runs(parts)),1)
