import copy
import json
from pathlib import Path
import unittest

import numpy as np

from voxel_mapper.aerial_feature_supervision import LABELS, extract


class AerialFeatureSupervisionTests(unittest.TestCase):
    def definition(self, name):
        return json.loads((Path(__file__).resolve().parents[1]/'voxel_mapper/data'/name).read_text())

    def test_same_purple_has_image_local_track_and_rock_meanings(self):
        rgb = np.full((32, 32, 3), 70, np.uint8); rgb[8:11, 8:11] = (200, 20, 200)
        a, _ = extract(rgb, self.definition('smiler-aerial-legend.json'))
        b, _ = extract(rgb, self.definition('towers-street-aerial-legend.json'))
        self.assertEqual(a[9, 9], LABELS['roller_coaster_track'])
        self.assertEqual(b[9, 9], LABELS['rock_boundary'])
        self.assertEqual(a[0, 0], 255)

    def test_red_theme_or_path_and_orange_theme_remain_distinct(self):
        rgb = np.full((32, 32, 3), 70, np.uint8)
        rgb[8:11, 8:11] = (245, 20, 20); rgb[20:23, 20:23] = (245, 150, 20)
        definition = self.definition('towers-street-aerial-legend.json')
        for rule in definition['colour_rules']: rule.pop('include_box', None)
        a, _ = extract(rgb, self.definition('smiler-aerial-legend.json'))
        b, _ = extract(rgb, definition)
        self.assertEqual(a[9, 9], LABELS['theming_structure'])
        self.assertEqual(b[9, 9], LABELS['path_trace'])
        self.assertEqual(b[21, 21], LABELS['theming_structure'])

    def test_small_grass_location_and_tree_outline_dashes_do_not_swap(self):
        rgb = np.full((80, 160, 3), 70, np.uint8)
        rgb[10:22, 10:22] = (20, 210, 20)  # larger tree marker
        for x in (45, 53, 61, 69): rgb[35:37, x:x+2] = (20, 210, 20)  # tree outline
        rgb[60:62, 130:132] = (124, 192, 79)  # isolated tiny grass-island marker
        labels, report = extract(rgb, self.definition('towers-street-aerial-legend.json'))
        self.assertEqual(labels[15, 15], LABELS['tree_feature'])
        self.assertEqual(labels[35, 53], LABELS['tree_feature'])
        self.assertEqual(labels[60, 130], LABELS['grass_island_location'])
        self.assertFalse(report['green']['grass_extent_inferred'])

    def test_conflicting_colour_roles_raise_instead_of_last_wins(self):
        rgb = np.full((32, 32, 3), 70, np.uint8); rgb[8:11, 8:11] = (200, 20, 200)
        definition = self.definition('smiler-aerial-legend.json')
        rule = copy.deepcopy(definition['colour_rules'][0]); rule['label'] = 'fence_barrier'
        definition['colour_rules'].append(rule)
        with self.assertRaisesRegex(ValueError, 'overlap'): extract(rgb, definition)


if __name__ == '__main__': unittest.main()
