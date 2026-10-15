import copy
import unittest

import numpy as np

from voxel_mapper.raster_opening_scan import scan,width_candidates
from tests import test_raster_opening_scan as fixtures


class IndexedScanTests(unittest.TestCase):
    def test_index_expands_to_every_original_threshold_correspondence(self):
        image=fixtures.OpeningScanTests().frame();image[33:125,43:44]=228;before=image.copy()
        expanded=scan(image);compact=scan(image,representation='indexed');index=compact['index'];restored=[]
        for family in index['consensus_families']:
            for second in family['second_pair_indices']:
                pair_evidence=[]
                for variant,identity in zip(index['variants'],[family['first_pair_index'],second]):
                    pair=copy.deepcopy(variant['pairs'][identity]);left,right=pair.pop('jamb_group_indices')
                    pair.update(left_jamb=variant['jamb_groups'][left],right_jamb=variant['jamb_groups'][right])
                    pair_evidence.append(pair)
                restored.append(pair_evidence)
        self.assertEqual(restored,[c['threshold_candidates'] for c in expanded['candidates']])
        self.assertTrue(any(pair[0]['bounds_pixels']!=pair[1]['bounds_pixels'] for pair in restored))
        self.assertTrue(np.array_equal(image,before));self.assertFalse(compact['physical_opening_verified'])

    def test_many_pairs_survive_compact_storage_and_budget_failure_is_whole(self):
        image=np.full((160,700),255,dtype='uint8')
        for x in range(40,626,15):image[30:125,x:x+3]=80
        image[30:33,40:628]=80
        self.assertEqual(scan(image)['reason'],'opening_pair_count_budget')
        compact=scan(image,representation='indexed')
        self.assertEqual(compact['status'],'indexed_jamb_head_correspondence_candidates_only')
        self.assertEqual([len(v['pairs']) for v in compact['index']['variants']],[741,741])
        self.assertEqual(compact['index']['consensus_edge_count'],741)
        self.assertEqual(len(compact['index']['consensus_families']),741)
        failed=scan(image,representation='indexed',max_checks=1)
        self.assertEqual(failed['status'],'scan_budget_withheld');self.assertIsNone(failed['index'])
        with self.assertRaises(ValueError):scan(image,representation='truncate')

    def test_width_query_preserves_all_matches_and_cannot_use_withheld_index(self):
        compact=scan(fixtures.OpeningScanTests().frame(),representation='indexed')
        found=width_candidates(compact,127,2,lambda:None)
        expected=[(i,f) for i,f in enumerate(compact['index']['consensus_families']) if abs(f['bounds_pixels'][2]-f['bounds_pixels'][0]-127)<=2]
        self.assertEqual(found,expected);self.assertTrue(found)
        self.assertEqual(width_candidates({'status':'scan_budget_withheld'},127,2,lambda:None),[])
        with self.assertRaises(ValueError):width_candidates(compact,float('nan'),2,lambda:None)


if __name__=='__main__':unittest.main()
