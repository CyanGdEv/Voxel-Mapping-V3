import copy
import unittest

import numpy as np
from shapely.geometry import Point,shape

from tests.test_raster_boundaries import drawing,group
from voxel_mapper.contrast_boundaries import prepare,audit
from voxel_mapper.material_boundary_restoration import review


class RestorationTests(unittest.TestCase):
    def fixture(self):
        image=drawing()
        anchors=[{'number':'1','target_page_point':[65,36]},
                 {'number':'2','target_page_point':[65,85]}]
        return image,anchors

    def test_all_competing_restorations_keep_original_pixels_and_source_evidence(self):
        image,anchors=self.fixture();prepared=prepare(image,group());before=copy.deepcopy(prepared)
        self.assertEqual(audit(prepared,anchors[0]['target_page_point'])['status'],'unverified_contrast_boundary_candidate')
        result=review(prepared,anchors)
        self.assertTrue(result['alternatives']);self.assertGreater(len(result['alternatives']),1)
        self.assertIsNone(result['selected_physical_boundary_id'])
        for alternative in result['alternatives']:
            self.assertFalse(alternative['physical_boundary_identity_verified'])
            for region in alternative['regions']:
                check=region['boundary_review']
                self.assertGreaterEqual(check['original_ink_boundary_support'],.98)
                self.assertFalse(check['accepted_feature'])
                other=next(a for a in anchors if a['number']!=region['number'])
                self.assertFalse(shape(check['geometry']).covers(Point(other['target_page_point'])))
        self.assertTrue(np.array_equal(prepared[0][0],before[0][0]))
        self.assertTrue(all(np.array_equal(a,b) for a,b in zip(prepared[0][1],before[0][1])))
        self.assertTrue(all(np.array_equal(a,b) for a,b in zip(prepared[1],before[1])))
        self.assertEqual(result,review(prepared,anchors))

    def test_raster_review_retains_mixed_material_rejection_beside_alternatives(self):
        from unittest.mock import patch
        from voxel_mapper.raster_faces import review as raster_review
        image,anchors=self.fixture()
        records=[{**a,'document_sha256':'a'*64,'page':1,'raster_dependencies':[{}],
                  'glyph_screen_status':'raster_consistent_candidate'} for a in anchors]
        with patch('voxel_mapper.raster_faces.assemble',return_value=(image,{})),\
             patch('voxel_mapper.raster_faces.artwork_groups',return_value=[group()]):
            result=raster_review(None,records)
        self.assertTrue(all(r['raster_contrast_boundary_review']['status']=='withheld_contrast_mixed_material_anchors' for r in records))
        self.assertTrue(result['material_boundary_restoration_reviews'][0]['alternatives'])
        self.assertTrue(all('geometry' not in r['raster_contrast_boundary_review'] for r in records))

    def test_budget_withholds_whole_inventory_and_bad_recipe_is_rejected(self):
        image,anchors=self.fixture();prepared=prepare(image,group())
        for options in ({'max_trials':1},{'max_pixel_work':1}):
            result=review(prepared,anchors,**options)
            self.assertEqual(result['status'],'restoration_budget_withheld')
            self.assertEqual(result['alternatives'],[]);self.assertEqual(result['trials'],[])
        broken=copy.deepcopy(prepared);broken[0][2]['variants'][0]['contrast_pixels_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'checksum'):review(broken,anchors)
        with self.assertRaises(ValueError):review(prepared,anchors,max_trials=True)


if __name__=='__main__':unittest.main()
