import unittest
from unittest.mock import patch
import numpy as np
import pymupdf
from voxel_mapper.raster_faces import assemble, propose, review, artwork_groups


class RasterTests(unittest.TestCase):
    def test_stable_region_preserves_hole(self):
        image = np.zeros((200, 200), dtype='uint8')
        image[30:170,30:170] = 255
        image[80:120,80:120] = 0
        result = propose(image, [25,25])
        self.assertEqual(result['status'], 'unverified_stable_raster_region_candidate')
        self.assertEqual(result['opening_count_candidate'], 1)
        self.assertEqual(result['geometry']['coordinates'][0][0], (15.,15.))
        self.assertFalse(result['accepted_feature'])
        self.assertFalse(result['opening_identity_verified'])

    def test_background_stripe_ink_and_unstable_rejected(self):
        for kind in ('background','stripe','ink','unstable'):
            with self.subTest(kind=kind):
                image = np.zeros((200,200), dtype='uint8')
                if kind == 'background': image[:] = 255
                if kind == 'stripe': image[30:170,95:105] = 255
                if kind == 'unstable':
                    image[20:180,20:180] = 200; image[50:150,50:150] = 255
                result = propose(image,[50,50])
                self.assertEqual(result['status'],'withheld_unstable_or_unbounded_raster_region')
                self.assertNotIn('geometry',result)

    def test_window_leak_not_cropped_into_fake_face(self):
        image=np.zeros((1000,1000),dtype='uint8');image[50:950,50:950]=255
        result=propose(image,[250,250],radius_points=40)
        self.assertTrue(all(r['reason']=='region_reaches_review_window_edge' for r in result['threshold_receipts']))

    def test_adjacent_tiles_reassemble_and_page_rotation_unchanged(self):
        with pymupdf.open() as document:
            page=document.new_page(width=100,height=100)
            for x, color in ((0,0),(50,255)):
                image=pymupdf.Pixmap(pymupdf.csRGB,pymupdf.IRect(0,0,50,100),False);image.clear_with(color)
                page.insert_image(pymupdf.Rect(x,0,x+50,100),pixmap=image)
            page.set_rotation(90)
            gray,receipt=assemble(page)
            self.assertEqual(page.rotation,90)
            self.assertLess(gray[100,20],10);self.assertGreater(gray[100,180],240)
            self.assertEqual(len(receipt['placements']),2)
            self.assertFalse(receipt['clipping_verified'])

    def test_cardinal_rotated_tile_orientation(self):
        with pymupdf.open() as document:
            page=document.new_page(width=100,height=100)
            data=np.full((20,40,3),255,dtype='uint8');data[:,:20]=0
            image=pymupdf.Pixmap(pymupdf.csRGB,40,20,data.tobytes(),False)
            page.insert_image(pymupdf.Rect(0,0,100,100),pixmap=image,rotate=90,keep_proportion=False)
            gray,_=assemble(page)
            self.assertGreater(gray[20,100],240);self.assertLess(gray[180,100],10)

    def test_overlapping_tiles_preserve_paint_order(self):
        with pymupdf.open() as document:
            page=document.new_page(width=100,height=100)
            image=pymupdf.Pixmap(pymupdf.csRGB,pymupdf.IRect(0,0,10,10),False);image.clear_with(255)
            page.insert_image(pymupdf.Rect(0,0,60,60),pixmap=image)
            image.clear_with(0)
            page.insert_image(pymupdf.Rect(40,40,100,100),pixmap=image)
            gray,receipt=assemble(page)
            self.assertEqual(len(receipt['overlapping_image_pairs']),1)
            self.assertGreater(gray[20,20],240);self.assertLess(gray[100,100],10)
            self.assertFalse(receipt['clipping_verified'])

    def test_atlas_budget_and_review_withholding(self):
        with pymupdf.open() as document:
            page=document.new_page(width=10000,height=10000)
            with self.assertRaisesRegex(ValueError,'pixel budget'):assemble(page)
        record={'raster_dependencies':[{}],'glyph_screen_status':'raster_consistent_candidate','target_page_point':[10,10]}
        with patch('voxel_mapper.raster_faces.assemble',side_effect=ValueError('unsupported')):
            receipt=review(None,[record])
        self.assertEqual(receipt['status'],'withheld_atlas')
        self.assertEqual(record['raster_region_review']['status'],'withheld_atlas')
        self.assertNotIn('geometry',record)

    def test_reflected_tile_matches_source_render(self):
        with pymupdf.open() as document:
            page=document.new_page(width=100,height=100)
            data=np.full((20,40,3),255,dtype='uint8');data[:,:20]=0
            image=pymupdf.Pixmap(pymupdf.csRGB,40,20,data.tobytes(),False)
            page.insert_image(pymupdf.Rect(0,0,100,100),pixmap=image,rotate=90,keep_proportion=False)
            xref=page.get_contents()[0]
            content=document.xref_stream(xref)
            # Reflect placement x in the page: the source image affine now has negative determinant.
            document.update_stream(xref,b'q -1 0 0 1 100 0 cm '+content+b' Q')
            gray,receipt=assemble(page)
            source=page.get_pixmap(matrix=pymupdf.Matrix(2,2),colorspace=pymupdf.csGRAY,alpha=False)
            expected=np.frombuffer(source.samples,dtype=np.uint8).reshape(200,200)
            self.assertTrue(receipt['placements'][0]['reflected_source_x'])
            self.assertTrue(np.array_equal(gray,expected))

    def test_artwork_windows_separate_distant_ink_without_face_promotion(self):
        gray=np.full((500,500),255,dtype='uint8')
        gray[20:100,20:100]=0;gray[350:470,350:470]=0
        groups=artwork_groups(gray)
        self.assertEqual(len(groups),2)
        self.assertTrue(all(not g['view_identity_verified'] for g in groups))
        self.assertTrue(all('geometry' not in g for g in groups))

    def test_native_annotation_strokes_excluded_from_atlas(self):
        with pymupdf.open() as document:
            page=document.new_page(width=100,height=100)
            image=pymupdf.Pixmap(pymupdf.csRGB,pymupdf.IRect(0,0,10,10),False);image.clear_with(255)
            page.insert_image(pymupdf.Rect(0,0,100,100),pixmap=image)
            page.draw_line((0,50),(100,50),width=5)
            gray,_=assemble(page)
            self.assertEqual(int(gray.min()),255)
            rendered=page.get_pixmap(colorspace=pymupdf.csGRAY)
            self.assertEqual(min(rendered.samples),0)

    def test_region_review_rejects_unbounded_parameters(self):
        gray=np.zeros((100,100),dtype='uint8')
        for arguments in ({'radius_points':10000},{'zoom':100}):
            with self.assertRaises(ValueError):propose(gray,[1,1],**arguments)
        with self.assertRaises(ValueError):propose(gray,[float('nan'),1])
