import unittest
from unittest.mock import patch
import numpy as np
from voxel_mapper.raster_boundaries import stroke_families, prepare, audit


def drawing():
    image=np.full((240,320),255,dtype='uint8')
    image[30:210,30:33]=0;image[30:210,287:290]=0
    image[30:33,30:290]=0;image[207:210,30:290]=0
    for y in range(45,200,10):image[y:y+2,30:290]=150
    return image


def group():
    return {'id':'review','bbox_page_points':[15,15,145,105]}


class BoundaryTests(unittest.TestCase):
    def test_periodic_strokes_preserve_endpoints_and_crossing_edges(self):
        image=drawing();image[30:210,150:153]=0
        mask,families=stroke_families(image,224)
        self.assertTrue(families);self.assertTrue(mask.any())
        self.assertFalse(mask[:,30:36].any());self.assertFalse(mask[:,284:290].any())
        self.assertFalse(mask[:,148:155].any())
        self.assertFalse(mask[45:47].any());self.assertFalse(mask[195:197].any())
        self.assertTrue(all(not f['hatch_identity_verified'] for f in families))

    def test_vertical_rotation_is_equivalent(self):
        image=drawing();a,fa=stroke_families(image,224);b,fb=stroke_families(image.T.copy(),224)
        self.assertTrue(np.array_equal(a,b.T))
        self.assertEqual(fa[0]['axis'],'horizontal');self.assertEqual(fb[0]['axis'],'vertical')

    def test_sparse_irregular_strokes_and_dark_fill_not_hatches(self):
        for positions in ([40,70,100],[40,46,65,70,93,110]):
            image=np.full((200,200),255,dtype='uint8')
            for y in positions:image[y:y+2,20:180]=150
            mask,families=stroke_families(image,224)
            self.assertFalse(mask.any());self.assertFalse(families)
        image=np.full((200,200),255,dtype='uint8');image[20:180,20:180]=192
        mask,families=stroke_families(image,224)
        self.assertFalse(mask.any());self.assertFalse(families)

    def test_suppression_candidate_never_accepted_and_input_unchanged(self):
        image=drawing();original=image.copy();prepared=prepare(image,group());result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'unverified_hatch_suppressed_boundary_candidate')
        self.assertGreaterEqual(result['original_ink_boundary_support'],.98)
        self.assertFalse(result['accepted_feature']);self.assertFalse(result['outline_identity_verified'])
        self.assertEqual(result['world_geometry_additions'],0)
        self.assertTrue(np.array_equal(image,original))
        self.assertEqual(len(prepared[2]['variants']),2)

    def test_open_gap_never_closed_by_hatch_edits(self):
        image=drawing();image[60:180,30:33]=255
        result=audit(prepare(image,group()),[65,60])
        self.assertNotEqual(result['status'],'unverified_hatch_suppressed_boundary_candidate')
        self.assertNotIn('geometry',result)

    def test_budget_and_outside_anchor(self):
        image=np.full((2000,2000),255,dtype='uint8')
        with self.assertRaisesRegex(ValueError,'budget'):prepare(image,{'id':'large','bbox_page_points':[0,0,1000,1000]})
        result=audit(prepare(drawing(),group()),[-1,-1])
        self.assertNotIn('geometry',result)

    def test_unsupported_original_outline_withheld(self):
        image=drawing();prepared=prepare(image,group())
        # A fabricated processed rectangle has no closure in the original source.
        fake=np.full(image.shape,255,dtype='uint8');fake[15:225,15:305]=0;fake[40:200,40:280]=255
        prepared=(np.full(image.shape,255,dtype='uint8'),[fake,fake],prepared[2])
        result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'withheld_unsupported_source_outline')
        self.assertNotIn('geometry',result)

    def test_no_nearest_window_assignment_and_prepare_budget_withheld(self):
        from voxel_mapper.raster_faces import review
        record={'raster_dependencies':[{}],'glyph_screen_status':'raster_consistent_candidate','target_page_point':[60,60]}
        windows=[{'id':identity,'bbox_page_points':[0,0,100,100]} for identity in ('a','b')]
        gray=np.full((200,200),255,dtype='uint8')
        with patch('voxel_mapper.raster_faces.assemble',return_value=(gray,{})),patch('voxel_mapper.raster_faces.artwork_groups',return_value=windows):
            receipt=review(None,[record])
        self.assertEqual(record['raster_boundary_review']['status'],'withheld_ambiguous_artwork_review_window')
        self.assertFalse(receipt['boundary_review_windows'])
        with patch('voxel_mapper.raster_faces.assemble',return_value=(gray,{})),patch('voxel_mapper.raster_faces.artwork_groups',return_value=windows[:1]),patch('voxel_mapper.raster_boundaries.prepare',side_effect=ValueError('budget')):
            review(None,[record])
        self.assertEqual(record['raster_boundary_review']['status'],'withheld_hatch_review_window')

    def test_variant_geometry_disagreement_withheld(self):
        from shapely.geometry import box,mapping
        prepared=prepare(drawing(),group())
        candidates=[{'status':'unverified_stable_raster_region_candidate','geometry':mapping(box(20,20,90,90))},
                    {'status':'unverified_stable_raster_region_candidate','geometry':mapping(box(20,20,130,100))}]
        with patch('voxel_mapper.raster_boundaries.region_screen',side_effect=candidates):result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'withheld_hatch_suppression_disagreement')
        self.assertNotIn('geometry',result)

    def test_shadow_fill_ambiguity_withheld(self):
        from shapely.geometry import box,mapping
        image=drawing();prepared=prepare(image,group());crop,variants,receipt=prepared
        source=crop.copy();source[65:150,60:180]=192
        prepared=(source,[source.copy(),source.copy()],receipt)
        candidate={'status':'unverified_stable_raster_region_candidate','geometry':mapping(box(16.5,23.5,143.5,97.5))}
        with patch('voxel_mapper.raster_boundaries.region_screen',return_value=candidate):result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'withheld_shadow_or_dark_fill_ambiguity')
        self.assertNotIn('geometry',result)

    def test_boundary_on_periodic_lines_is_explicit_extent_ambiguity(self):
        result=audit(prepare(drawing(),group()),[65,60])
        self.assertFalse(result['extent_completeness_verified'])
        self.assertGreater(result['periodic_stroke_boundary_fraction_candidate'],.02)
        self.assertEqual(result['extent_ambiguity'],'boundary_near_periodic_strokes')

    def test_invalid_region_polygon_withheld(self):
        prepared=prepare(drawing(),group())
        candidate={'status':'unverified_stable_raster_region_candidate','geometry':
                   {'type':'Polygon','coordinates':[[(20,20),(90,90),(20,90),(90,20),(20,20)]]}}
        with patch('voxel_mapper.raster_boundaries.region_screen',return_value=candidate):result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'withheld_invalid_boundary_polygon')
        self.assertNotIn('geometry',result)

    def test_equal_opening_counts_with_shifted_openings_withheld(self):
        from shapely.geometry import box,Polygon,mapping
        image=drawing();image[80:84,80:84]=0;prepared=prepare(image,group())
        outer=list(box(16.5,23.5,143.5,97.5).exterior.coords)
        candidates=[{'status':'unverified_stable_raster_region_candidate','geometry':mapping(Polygon(outer,[box(x,x,x+2,x+2).exterior.coords]))} for x in (40,50)]
        with patch('voxel_mapper.raster_boundaries.region_screen',side_effect=candidates):result=audit(prepared,[65,60])
        self.assertEqual(result['status'],'withheld_opening_geometry_disagreement')
        self.assertNotIn('geometry',result)
