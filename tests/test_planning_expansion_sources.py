"""Source availability and application association must not fabricate area geometry."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from voxel_mapper import planning_expansion_sources as sources
from voxel_mapper.planning_area_pilot import validate


class ExpansionSourceTests(unittest.TestCase):
    def test_review_excludes_upper_gardens_and_retains_unknown_katanga_state(self):
        review=sources.profile()
        self.assertFalse(review['world_placement_eligible']);self.assertFalse(review['training_eligible'])
        excluded={r['sha256'] for r in review['excluded_sources']}
        self.assertFalse(excluded&{r['sha256'] for r in review['sources']})
        self.assertEqual({r['drawing_state'] for r in review['sources'] if r['area_id']=='katanga-canyon'},{'unknown'})

    def test_mixed_available_missing_and_corrupt_sources_remain_distinct(self):
        review=sources.profile()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'originals';source.mkdir()
            with pymupdf.open() as doc:
                page=doc.new_page(width=300,height=200);page.insert_text((20,50),'Existing test plan')
                raw=doc.tobytes()
            good=copy.deepcopy(review['sources'][0]);good['sha256']=hashlib.sha256(raw).hexdigest();good['file']=good['sha256']+'.pdf'
            (source/good['file']).write_bytes(raw)
            corrupt=copy.deepcopy(review['sources'][1]);(source/corrupt['file']).write_bytes(b'wrong original')
            review['sources']=[good,corrupt,review['sources'][-1]]
            with patch.object(sources,'profile',return_value=review):result=sources.prepare(source,root/'pack')
            self.assertEqual(result['included_originals'],1);self.assertEqual(result['unavailable_originals'],1)
            self.assertEqual(result['withheld_originals'],1);self.assertEqual(result['park_world_blocks_added'],0)
            self.assertEqual((root/'pack/files'/good['file']).read_bytes(),raw)
            self.assertFalse((root/'pack/files'/corrupt['file']).exists())
            for area in ('mutiny-bay','katanga-canyon'):
                config=json.loads((root/'pack'/(area+'-pilot.json')).read_text());validate(config)
                self.assertEqual(config['source_directory'],'files')
            # Never silently overwrite a previously reviewed pack.
            with self.assertRaises(FileExistsError):sources.prepare(source,root/'pack')

    def test_excluded_sheet_cannot_be_added_by_its_application_membership(self):
        review=sources.profile();review['sources'][0]['sha256']=review['excluded_sources'][0]['sha256']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'review.json';path.write_text(json.dumps(review))
            with patch.object(sources,'PROFILE_PATH',path),self.assertRaises(ValueError):sources.profile()



class SelectedPlanPagesTests(unittest.TestCase):
    def test_long_bundle_keeps_original_and_only_previews_selected_pages(self):
        review=sources.profile()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'originals';source.mkdir()
            with pymupdf.open() as doc:
                for i in range(12):doc.new_page(width=300,height=200)
                raw=doc.tobytes()
            row=copy.deepcopy(review['sources'][-1]);row.update(sha256=hashlib.sha256(raw).hexdigest(),pages=[11,12],page_roles={'11':'site-plan','12':'elevation'})
            row['file']=row['sha256']+'.pdf';(source/row['file']).write_bytes(raw)
            review['sources']=[review['sources'][0],row];review['raster_sources']=[]
            with patch.object(sources,'profile',return_value=review):result=sources.prepare(source,root/'pack')
            self.assertEqual(result['included_originals'],1)
            self.assertEqual([r['page'] for r in result['sources'][1]['pages']],[11,12])
            self.assertEqual(result['sources'][1]['total_document_pages'],12)
            self.assertEqual((root/'pack/files'/row['file']).read_bytes(),raw)

    def test_original_jpeg_is_preserved_without_claiming_pdf_geometry(self):
        from PIL import Image
        review=sources.profile()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'originals';source.mkdir();p=source/'image.jpg';Image.new('RGB',(100,80),'white').save(p)
            raw=p.read_bytes();row=copy.deepcopy(review['raster_sources'][0]);row.update(sha256=hashlib.sha256(raw).hexdigest(),pixel_dimensions=[100,80]);row['file']=row['sha256']+'.jpg';p.rename(source/row['file'])
            review['raster_sources']=[row]
            with patch.object(sources,'profile',return_value=review):result=sources.prepare(source,root/'pack')
            self.assertEqual(result['included_raster_originals'],1)
            self.assertEqual((root/'pack/files'/row['file']).read_bytes(),raw)
            config=json.loads((root/'pack/katanga-canyon-pilot.json').read_text())
            self.assertNotIn(row['sha256'],[r['sha256'] for r in config['documents']])
            self.assertFalse(result['world_placement_eligible'])

if __name__=='__main__':unittest.main()
