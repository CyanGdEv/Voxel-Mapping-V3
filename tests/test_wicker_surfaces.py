import unittest
from voxel_mapper.wicker_surfaces import painted_polygon, visible_fills, extract_surfaces


def rectangle(bounds, **props):
    return {'type': 'f', 'items': [['re', bounds, 1]], 'fill': [.8, .7, .6],
            'fill_opacity': 1, 'even_odd': True, 'level': 0, 'seqno': 1, **props}


class SurfaceTests(unittest.TestCase):
    def test_existing_and_new_same_colour_cannot_establish_construction_state(self):
        vectors = [rectangle([200, 100, 260, 140], seqno=9),
                   rectangle([200, 160, 260, 200], seqno=10),
                   rectangle([10, 10, 70, 80], seqno=11)]
        labels = [{'text': 'Existing Paving with levels', 'bbox': [270, 105, 390, 120]},
                  {'text': 'New Paving with levels', 'bbox': [270, 165, 390, 180]}]
        candidates, report = extract_surfaces(vectors, labels, .1)
        self.assertEqual(candidates, [])
        self.assertTrue(all(l['status'] == 'withheld_colour_shared_by_existing_and_new_legends' for l in report['legends']))

    def test_invalid_scale_and_empty_even_odd_fill_are_rejected(self):
        for scale in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                extract_surfaces([], [], scale)
        path = rectangle([0, 0, 20, 20])
        path['items'].append(['re', [0, 0, 20, 20], 1])
        self.assertIsNone(painted_polygon(path))

    def test_even_odd_holes_remain_open_and_nonzero_subpaths_are_withheld(self):
        path = rectangle([0, 0, 20, 20])
        path['items'].append(['re', [5, 5, 15, 15], 1])
        polygon = painted_polygon(path)
        self.assertEqual(polygon.area, 300)
        self.assertEqual(len(polygon.interiors), 1)
        path['even_odd'] = False
        self.assertIsNone(painted_polygon(path))

    def test_explicit_clip_geometry_not_scissor_controls_visible_area(self):
        clip = {'type': 'clip', 'level': 0, 'even_odd': True, 'scissor': [0, 0, 100, 100],
                'items': [['l', [0, 0], [10, 0]], ['l', [10, 0], [0, 10]]]}
        fills, _ = visible_fills([clip, rectangle([0, 0, 20, 20], level=1)])
        self.assertEqual(fills[0]['polygon'].area, 50)

    def test_unsupported_scope_and_optional_layers_are_withheld(self):
        group = {'type': 'group', 'level': 0}
        fills, count = visible_fills([group, rectangle([0, 0, 20, 20], level=1),
                                     rectangle([0, 0, 20, 20], layer='optional')])
        self.assertEqual(fills, [])
        self.assertEqual(count, 2)

    def test_legend_matching_excludes_swatch_and_does_not_assign_material(self):
        vectors = [rectangle([200, 100, 260, 140], seqno=9),
                   rectangle([10, 10, 70, 80], seqno=10)]
        labels = [{'text': 'Existing Paving with levels', 'bbox': [270, 105, 390, 120]},
                  {'text': 'New Paving with levels', 'bbox': [270, 150, 390, 165]},
                  {'text': 'Plaza', 'bbox': [20, 20, 40, 30]}]
        candidates, report = extract_surfaces(vectors, labels, .1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['state'], 'existing')
        self.assertEqual(candidates[0]['contained_labels'], ['Plaza'])
        self.assertIsNone(candidates[0]['material'])
        self.assertEqual(report['legends'][1]['status'], 'withheld_no_unique_filled_swatch')

    def test_same_colour_text_mask_is_excluded_and_geometry_is_deduplicated(self):
        labels = [{'text': 'Existing Paving with levels', 'bbox': [270, 105, 390, 120]},
                  {'text': 'Plaza', 'bbox': [20, 20, 40, 30]}]
        vectors = [rectangle([200, 100, 260, 140]), rectangle([10, 10, 70, 80]),
                   rectangle([10, 10, 70, 80], seqno=3), rectangle([20, 20, 40, 30], seqno=4)]
        candidates, report = extract_surfaces(vectors, labels, .1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(report['excluded_text_masks'], 1)

    def test_ambiguous_legend_and_curves_cannot_supply_surface(self):
        labels = [{'text': 'Existing Paving with levels', 'bbox': [270, 105, 390, 120]}]
        vectors = [rectangle([200, 100, 260, 140]), rectangle([210, 100, 250, 140]),
                   rectangle([10, 10, 70, 80])]
        candidates, _ = extract_surfaces(vectors, labels, .1)
        self.assertEqual(candidates, [])
        curve = rectangle([0, 0, 20, 20]); curve['items'] = [['c', [0, 0], [1, 1], [2, 2], [3, 3]]]
        self.assertIsNone(painted_polygon(curve))
