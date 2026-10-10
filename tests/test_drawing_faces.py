import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from shapely.geometry import Polygon,box,mapping
from tests.test_drawing_callouts import Page
from voxel_mapper.drawing_faces import face_matches,page_faces,raster_references,run
from voxel_mapper.drawing_callouts import page_callouts


def face(geometry,identity='face'):
    return {'id':identity,'geometry':mapping(geometry),'extraction_kind':'linework_boundaries'}


class FaceTests(unittest.TestCase):
    def test_openings_preserved_and_boundary_not_snapped(self):
        polygon=Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(40,40),(60,40),(60,60),(40,60)]])
        candidate=face(polygon)
        self.assertEqual(face_matches([candidate],[20,20]),[candidate])
        self.assertEqual(face_matches([candidate],[50,50]),[])
        self.assertEqual(face_matches([candidate],[0,20]),[])
        self.assertEqual(len(candidate['geometry']['coordinates']),2)

    def test_nested_faces_remain_ambiguous(self):
        matches=face_matches([face(box(0,0,100,100),'outer'),face(box(10,10,90,90),'inner')],[50,50])
        self.assertEqual(len(matches),2)

    def evaluate(self,candidates,raster=None,visible=True):
        page=Page();callouts,receipt=page_callouts(page,'a'*64,1)
        with patch('voxel_mapper.drawing_faces.page_callouts',return_value=(callouts,receipt)),patch('voxel_mapper.drawing_faces.extract_page',return_value=(['parent'],{})),patch('voxel_mapper.drawing_faces.recover_page',return_value=(candidates,{})),patch('voxel_mapper.drawing_faces.native_inverse',return_value=pymupdf.Matrix(1,1)),patch('voxel_mapper.drawing_faces.screen_span',return_value={'status':'raster_consistent_candidate' if visible else 'withheld'}),patch('voxel_mapper.drawing_faces.raster_references',return_value=raster or []):
            return page_faces(page,'a'*64,1)

    def test_unique_face_candidate_never_promoted(self):
        polygon=Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(40,40),(60,40),(60,60),(40,60)]])
        records,_,_=self.evaluate([face(polygon)])
        self.assertEqual(records[0]['status'],'unique_enclosed_face_candidate')
        self.assertEqual(records[0]['opening_count_candidate'],1)
        self.assertFalse(records[0]['accepted_feature']);self.assertFalse(records[0]['opening_identity_verified'])
        self.assertFalse(records[0]['view_identity_verified'])

    def test_raster_dependency_and_failed_visibility_withheld(self):
        records,_,_=self.evaluate([],raster=[{'xref':1}])
        self.assertEqual(records[0]['status'],'withheld_raster_face_adapter_required')
        self.assertNotIn('face_candidate_id',records[0])
        records,_,_=self.evaluate([face(box(0,0,100,100))],visible=False)
        self.assertEqual(records[0]['status'],'withheld_glyph_visibility')

    def test_image_pixel_reference_uses_original_affine(self):
        with pymupdf.open() as document:
            page=document.new_page(width=200,height=200)
            image=pymupdf.Pixmap(pymupdf.csRGB,pymupdf.IRect(0,0,20,10),False);image.clear_with(255)
            page.insert_image(pymupdf.Rect(40,50,80,70),pixmap=image)
            references=raster_references(page,[60,60])
            self.assertEqual(len(references),1)
            self.assertEqual(references[0]['image_size_pixels'],[20,10])
            self.assertEqual(references[0]['anchor_image_pixel_candidate'],[10,5])
            self.assertFalse(references[0]['component_boundary_verified'])
            self.assertEqual(raster_references(page,[0,0]),[])

    def test_batch_checksums_cache_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pdf=root/'source.pdf'
            with pymupdf.open() as document:document.new_page();document.save(pdf)
            docs=root/'documents.json';docs.write_text(json.dumps([{'file':'source.pdf','sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}]))
            with patch('voxel_mapper.drawing_faces.page_faces',return_value=([],[],{'glyph_checks':0,'glyph_screen_passes':0})):
                report=run(docs,root/'out')
            self.assertEqual(run(docs,root/'out'),report)
            (root/'out/face-associations.jsonl').write_text('corrupt')
            with self.assertRaisesRegex(ValueError,'checksum'):run(docs,root/'out')
            pdf.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'pinned'):run(docs,root/'changed')

    def test_pipeline_face_evidence_is_not_geometry_feed(self):
        from voxel_mapper.park_pipeline import run as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'manifest.json').write_text(json.dumps({'crs':'EPSG:27700','sources':[]}))
            (root/'job.json').write_text(json.dumps({'manifest':'manifest.json','work_directory':'work','drawing_faces':{'enabled':True,'documents':'documents.json'}}))
            report={'status':'unplaced_face_association_evidence','contract':{},'output_sha256':{}}
            with patch('voxel_mapper.drawing_faces.run',return_value=report):state=pipeline(root/'job.json','compile')
            self.assertEqual(state['stages']['drawing_faces'],report)
            self.assertEqual(state['stages']['reconstruction']['status'],'awaiting_normalized_geometry')
