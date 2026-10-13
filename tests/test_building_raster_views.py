import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pymupdf
from PIL import Image

from voxel_mapper.building_raster_views import VERSION, placements, render
from voxel_mapper.building_pdf_discovery import discover_page


class RasterViewTests(unittest.TestCase):
    def source(self, root):
        image=BytesIO();Image.new('RGB',(20,10),'red').save(image,format='PNG')
        doc=pymupdf.open();page=doc.new_page(width=400,height=300)
        page.insert_image((30,40,230,140),stream=image.getvalue())
        page.insert_image((250,40,350,90),stream=image.getvalue())
        page.draw_rect((30,40,230,140),fill=(1,1,1),overlay=True)
        page.set_rotation(90);data=doc.tobytes();doc.close()
        (root/'source.pdf').write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def config(self,sha):
        return {'version':VERSION,'path':'source.pdf','sha256':sha,'page':1,
                'bounds_pdf_native':[25.3,155.7,240.8,265.2],'width_pixels':800,'rotation_degrees':0}

    def test_occurrences_native_pixels_rotation_and_hidden_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.source(root)
            with pymupdf.open(root/'source.pdf') as doc:
                page=doc[0];result=placements(page,sha,1)
                self.assertEqual(len(result['placements']),2)
                self.assertEqual(page.rotation,90)
                first=result['placements'][0];m=pymupdf.Matrix(first['pixel_edge_to_pdf_native_matrix'])
                self.assertEqual(tuple(pymupdf.Point(0,0)*m),(30,260))
                self.assertEqual(tuple(pymupdf.Point(20,10)*m),(230,160))
                self.assertFalse(first['visibility_verified'])
                self.assertNotEqual(first['id'],result['placements'][1]['id'])
                page.set_rotation(0)
                self.assertEqual(result,placements(page,sha,1))
                self.assertEqual(placements(page,sha,1,max_images=1)['placements'],[])
                with self.assertRaises(ValueError):placements(page,sha,1,max_images=True)

    def test_composited_crop_rounding_and_deterministic_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.source(root);config=self.config(sha)
            receipt=render(config,lambda p:root/p,root/'crop')
            again=render(config,lambda p:root/p,root/'again')
            self.assertEqual(receipt,again)
            png=(root/'crop/view.png').read_bytes()
            self.assertEqual(hashlib.sha256(png).hexdigest(),receipt['png_sha256'])
            image=Image.open(BytesIO(png));self.assertEqual(image.getpixel((400,400)),(255,255,255))
            m=pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])
            p=pymupdf.Point(0,0)*m
            # Outward integer rounding is preserved; no stretching by rounded height.
            self.assertLessEqual(p.x,config['bounds_pdf_native'][0]);self.assertGreaterEqual(p.y,config['bounds_pdf_native'][3])
            self.assertAlmostEqual(abs(m.a),abs(m.d))
            self.assertFalse(receipt['geometry_verified']);self.assertEqual(receipt['shared_specs_generated'],0)
            with self.assertRaises(ValueError):render(config,lambda p:root/p,root/'crop')

    def test_checksum_bounds_budgets_and_cli(self):
        from voxel_mapper.building_pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.source(root);config=self.config(sha)
            for override in ({'sha256':'f'*64},{'bounds_pdf_native':[0,0,500,300]},
                             {'bounds_pdf_native':[0,0,1,300]},{'width_pixels':True},
                             {'page':2},{'geometry_verified':True}):
                with self.assertRaises(ValueError):render({**config,**override},lambda p:root/p,root/'bad')
                self.assertFalse((root/'bad').exists())
            (root/'config.json').write_text(json.dumps(config))
            with redirect_stdout(StringIO()):main(['render-view','--config',str(root/'config.json'),'--output',str(root/'cli')])
            self.assertEqual(json.loads((root/'cli/receipt.json').read_text())['document_sha256'],sha)

    def test_all_review_rotations_preserve_pixel_native_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sha=self.source(root);config=self.config(sha)
            for rotation in (0,90,180,270):
                receipt=render({**config,'rotation_degrees':rotation},lambda p:root/p,root/str(rotation))
                m=pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix']);inverse=~m
                for x,y in ((40,170),(100,200),(200,240)):
                    original=pymupdf.Point(x,y);pixel=original*inverse;recovered=pixel*m
                    self.assertAlmostEqual(recovered.x,x,places=4);self.assertAlmostEqual(recovered.y,y,places=4)
                    self.assertGreaterEqual(pixel.x,0);self.assertGreaterEqual(pixel.y,0)
                    self.assertLess(pixel.x,receipt['size_pixels'][0]);self.assertLess(pixel.y,receipt['size_pixels'][1])
            config.pop('rotation_degrees')
            receipt=render(config,lambda p:root/p,root/'default')
            self.assertEqual(receipt['render_rotation_degrees'],90)

    def test_raster_only_discovery_keeps_placements_without_native_geometry(self):
        image=BytesIO();Image.new('RGB',(20,10),'red').save(image,format='PNG')
        doc=pymupdf.open();page=doc.new_page();page.insert_image((30,40,230,140),stream=image.getvalue())
        page.insert_text((30,180),'Elevation 1 to the S.East',fontsize=10)
        try:
            row=discover_page(page,'a'*64,1)
            self.assertEqual(row['status'],'no_native_geometry_candidates')
            self.assertEqual(len(row['source_image_placements']['placements']),1)
            self.assertFalse(row['world_placement_eligible']);self.assertEqual(row['source_geometry'],[])
            self.assertEqual(row['caption_layout']['view_captions'][0]['printed_claim']['view_number'],1)
        finally:doc.close()


if __name__=='__main__':unittest.main()
