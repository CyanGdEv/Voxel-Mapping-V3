import unittest
import numpy as np
from shapely.geometry import box,mapping
from tests.test_raster_boundaries import drawing,group
from voxel_mapper.contrast_boundaries import prepare,audit,check_material_regions
from voxel_mapper.raster_boundaries import audit as base_audit


class ContrastTests(unittest.TestCase):
    def test_faint_closed_outline_recovers_candidate_without_source_edits(self):
        image=drawing();image[image==0]=190;original=image.copy()
        result=audit(prepare(image,group()),[65,60])
        self.assertEqual(result['status'],'unverified_contrast_boundary_candidate')
        self.assertGreaterEqual(result['original_ink_boundary_support'],.98)
        self.assertFalse(result['accepted_feature']);self.assertFalse(result['outline_identity_verified'])
        self.assertTrue(np.array_equal(image,original))

    def test_shadow_normalization_never_hides_original_dark_fill(self):
        image=drawing();image[65:180,60:260]=192
        result=audit(prepare(image,group()),[65,60])
        self.assertNotEqual(result['status'],'unverified_contrast_boundary_candidate')
        self.assertNotIn('geometry',result)

    def test_conflicting_material_anchors_withheld_and_same_material_allowed(self):
        def record(number):return {'document_sha256':'a','page':1,'number':number,'glyph_screen_status':'raster_consistent_candidate','target_page_point':[50,50],
                     'raster_contrast_boundary_review':{'status':'unverified_contrast_boundary_candidate','geometry':mapping(box(0,0,100,100)),'accepted_feature':False}}
        records=[record(1),record(2)];check_material_regions(records)
        self.assertTrue(all(r['raster_contrast_boundary_review']['status']=='withheld_contrast_mixed_material_anchors' for r in records))
        self.assertTrue(all('geometry' not in r['raster_contrast_boundary_review'] for r in records))
        same=[record(1),record(1)];check_material_regions(same)
        self.assertTrue(all(r['raster_contrast_boundary_review']['status']=='unverified_contrast_boundary_candidate' for r in same))

    def test_edit_masks_must_match_unmodified_source_crop(self):
        windows,_=prepare(drawing(),group())
        with self.assertRaisesRegex(ValueError,'edit masks'):base_audit(windows,[65,60],edit_masks=[np.zeros((1,1),bool)]*2)
