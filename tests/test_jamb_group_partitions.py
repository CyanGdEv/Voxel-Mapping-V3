import copy
import unittest

import numpy as np
from shapely.geometry import box, mapping

from voxel_mapper.jamb_group_partitions import partition
from voxel_mapper.raster_opening_scan import scan
from voxel_mapper.drawing_view_components import inspect_view


class JambPartitionTests(unittest.TestCase):
    def bands(self, count=36):
        gray = np.full((count*33+50, 430), 255, dtype=np.uint8)
        for i in range(count):
            top = 20+i*33
            for x in range(20, 371, 25): gray[top:top+25, x:x+2] = 70
            gray[top:top+2, 20:47] = 70
        return gray

    def test_more_than_512_original_groups_complete_with_small_exact_components(self):
        gray = self.bands(); before = gray.copy()
        self.assertEqual(scan(gray, representation='indexed')['reason'], 'vertical_run_group_budget')
        result = scan(gray, representation='indexed', partition_groups=True)
        self.assertEqual(result['status'], 'indexed_jamb_head_correspondence_candidates_only')
        self.assertEqual(len(result['index']['consensus_families']), 36)
        for proof in result['group_partition_proofs']:
            self.assertEqual(proof['total_original_groups'], 540)
            self.assertEqual(proof['max_component_groups'], 15)
            self.assertEqual(len(proof['components']), 36)
            self.assertEqual(proof['cross_component_eligible_pairs'], 0)
            self.assertEqual(proof['eligible_directed_pairs'], 3780)
        self.assertTrue(np.array_equal(gray, before)); self.assertFalse(result['physical_opening_verified'])

    def test_partitioned_and_legacy_indices_are_identical_where_both_fit(self):
        gray = self.bands(12); legacy = scan(gray, representation='indexed')
        current = scan(gray, representation='indexed', partition_groups=True)
        self.assertEqual(current['index'], legacy['index'])
        self.assertEqual(current['source_gray_sha256'], legacy['source_gray_sha256'])
        smaller = self.bands(2)
        self.assertTrue(scan(smaller)['candidates'])
        self.assertEqual(scan(smaller, partition_groups=True)['candidates'], scan(smaller)['candidates'])

    def test_transitive_endpoint_bridge_cannot_be_cut_into_false_work_components(self):
        groups = [{'left': 20+i*40, 'right': 22+i*40, 'top': 30+i*2, 'bottom': 100+i*2} for i in range(3)]
        original = copy.deepcopy(groups); proof = partition(groups, 20, 600, 512, lambda: None)
        self.assertEqual(proof['components'], [{'group_indices': [0, 1, 2], 'eligible_directed_pairs': 2}])
        self.assertEqual(groups, original)
        with self.assertRaisesRegex(OverflowError, 'component_group_budget'):
            partition(groups, 20, 600, 2, lambda: None)

    def test_component_membership_preserves_every_exhaustively_eligible_pair(self):
        groups = [{'left': x, 'right': x+2, 'top': top, 'bottom': top+70}
            for top in [20, 22, 24, 90] for x in [10, 35, 75, 800]]
        proof = partition(groups, 20, 600, 512, lambda: None)
        owner = {i: k for k, c in enumerate(proof['components']) for i in c['group_indices']}
        count = 0
        for i, left in enumerate(groups):
            for j, right in enumerate(groups):
                if 20 <= right['left']-left['right'] <= 600 and max(abs(left[k]-right[k]) for k in ['top', 'bottom']) <= 2:
                    self.assertEqual(owner[i], owner[j]); count += 1
        self.assertEqual(proof['eligible_directed_pairs'], count)
        self.assertEqual(sorted(owner), list(range(len(groups))))

    def test_component_and_work_budgets_discard_the_whole_scan(self):
        gray = self.bands(3)
        too_small = scan(gray, representation='indexed', partition_groups=True, max_groups=10)
        self.assertEqual(too_small['reason'], 'compatible_component_group_budget')
        self.assertIsNone(too_small['index']); self.assertNotIn('group_partition_proofs', too_small)
        exhausted = scan(gray, representation='indexed', partition_groups=True, max_checks=1)
        self.assertEqual(exhausted['reason'], 'compatible_group_partition_work_budget')
        self.assertIsNone(exhausted['index']); self.assertEqual(exhausted['candidates'], [])
        completed = scan(gray, representation='indexed', partition_groups=True)
        late = scan(gray, representation='indexed', partition_groups=True, max_checks=completed['checks']-1)
        self.assertEqual(late['status'], 'scan_budget_withheld'); self.assertIsNone(late['index'])
        self.assertNotIn('group_partition_proofs', late); self.assertEqual(late['candidates'], [])

    def test_retained_group_and_pair_caps_are_still_enforced(self):
        gray = np.full((1250, 600), 255, dtype=np.uint8)
        for i in range(40):
            for x in range(20, 571, 5): gray[10+i*30:35+i*30, x:x+1] = 70
        retained = scan(gray, representation='indexed', partition_groups=True)
        self.assertEqual(retained['reason'], 'retained_group_budget')
        self.assertIsNone(retained['index'])
        dense = np.full((160, 600), 255, dtype=np.uint8)
        for x in range(20, 471, 3): dense[30:125, x:x+1] = 70
        dense[30:32, 20:471] = 70
        paired = scan(dense, representation='indexed', partition_groups=True)
        self.assertEqual(paired['reason'], 'indexed_pair_count_budget'); self.assertIsNone(paired['index'])

    def test_width_and_endpoint_limits_never_bridge_incompatible_groups(self):
        for right_left, top in [(41, 34), (630, 30), (39, 30)]:
            groups = [{'left': 20, 'right': 22, 'top': 30, 'bottom': 100},
                      {'left': right_left, 'right': right_left+2, 'top': top, 'bottom': top+70}]
            proof = partition(groups, 20, 600, 512, lambda: None)
            self.assertEqual(proof['eligible_directed_pairs'], 0)
            self.assertEqual(len(proof['components']), 2)

    def test_threshold_ambiguity_and_exclusions_keep_original_evidence(self):
        gray = self.bands(2); gray[22:45, 22:23] = 228
        plain = scan(gray, representation='indexed')
        partitioned = scan(gray, representation='indexed', partition_groups=True)
        self.assertEqual(plain['index'], partitioned['index'])
        excluded = {'220': [[20, 20, 22, 45]], '235': [[20, 20, 22, 45]]}
        # This exclusion would be partial width at threshold 235.
        with self.assertRaises(ValueError): scan(gray, representation='indexed', partition_groups=True, excluded_groups=excluded)
        for kwargs in [{'partition_groups': 1}, {'partition_groups': True, 'pair_scope': 'adjacent_compatible_jambs'}]:
            with self.assertRaises(ValueError): scan(gray, **kwargs)

    def test_automatic_fallback_preserves_failed_attempts_and_all_residual_families(self):
        gray = self.bands(); height, width = gray.shape
        view = {'id': 'many-bands', 'document_sha256': 'a'*64, 'page': 1,
            'geometry': mapping(box(0, 0, width, height)), 'caption_text': 'South Elevation',
            'caption_evidence': {'reading_direction_pdf_native': [1, 0]},
            'printed_claim': {'view_kind': 'elevation', 'printed_state': 'unspecified'},
            'nominal_metres_per_pdf_point': None, 'native_to_nominal_local_affine': None}
        result = inspect_view(view, [], gray, [1, 0, 0, -1, 0, height])
        self.assertEqual(result['counts']['partitioned_scan_passes'], 2)
        self.assertEqual(result['counts']['raster_opening_families'], 36)
        self.assertEqual(result['counts']['residual_raster_families'], 36)
        self.assertEqual(set(result['legacy_group_limit_attempts']), {'raster', 'residual'})
        self.assertTrue(all(v['reason']=='vertical_run_group_budget' for v in result['legacy_group_limit_attempts'].values()))
        self.assertEqual(result['world_geometry_additions'], 0)
