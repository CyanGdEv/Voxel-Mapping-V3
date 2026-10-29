import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image
from pyproj import Transformer

from voxel_mapper.generation_cycles import file_hash
from voxel_mapper.world_surface_layers import LABELS, VERSION, apply_surfaces, load_manifest, merge_rgb, surface_coverage


def world():
    rr, cc = np.indices((16, 16))
    project = SimpleNamespace(transform=Transformer.from_crs(4326, 3857, always_xy=True).transform,
                              inverse=Transformer.from_crs(3857, 4326, always_xy=True).transform)
    return SimpleNamespace(e0=0, n1=16, width=16, height=16, ee=cc+.5, nn=15.5-rr,
        project=project, dtm=np.zeros((16, 16)), rgb=np.full((16, 16, 3), 10, np.float32),
        cloud={'roof': np.full((16, 16), np.nan)}, footprints=np.zeros((16, 16), bool),
        protected=np.zeros((16, 16), bool), water=np.full((16, 16), -32768),
        bridge=np.full((16, 16), -32768), family=np.zeros((16, 16), np.uint8),
        surface_source=np.zeros((16, 16), np.uint8), green=np.zeros((16, 16), bool),
        chm=np.zeros((16, 16)), audit={})


class WorldSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def source(self, name, size=64, colour=100, mask=None):
        image = self.root/(name+'.png'); Image.fromarray(np.full((size, size, 3), colour, np.uint8)).save(image)
        receipt = {'width': size, 'height': size, 'extent_epsg3857': [0, 0, 16, 16], 'image_sha256': file_hash(image)}
        path = self.root/(name+'.json'); path.write_text(json.dumps(receipt))
        entry = {'id': name, 'image': image.name, 'image_sha256': file_hash(image),
                 'receipt': path.name, 'receipt_sha256': file_hash(path), 'role': 'clean_rgb_only'}
        result = {'entry': entry, 'image_path': image, 'receipt': receipt}
        if mask is not None:
            path = self.root/(name+'-mask.png'); Image.fromarray(mask).save(path)
            entry.update(mask=path.name, mask_sha256=file_hash(path), role='partial_source_assisted_surface_interiors',
                         independent_human_review=False, inferred_canopy_ground_included=False)
            result['mask_path'] = path
        return result

    def test_submetre_path_and_unknown_hole_do_not_expand_to_full_cells(self):
        mask = np.full((64, 64), 255, np.uint8)
        mask[:, 16:20] = 0  # a fully supported one-metre corridor
        mask[20:24, 16:20] = 255  # an explicit unknown gap
        mask[:, 24:26] = 0  # a half-metre sliver cannot claim a whole metre
        target, conflicts, _ = surface_coverage(world(), [self.source('path', mask=mask)])
        self.assertEqual(int((target == 0).sum()), 15)
        self.assertTrue(np.all(target[np.arange(16) != 5, 4] == 0))
        self.assertEqual(target[5, 4], 255)
        self.assertTrue(np.all(target[:, 6] == 255))
        self.assertFalse(conflicts.any())

    def test_conflicting_sources_preserve_geometry_and_screen_infill(self):
        mask = np.full((64, 64), 255, np.uint8); mask[24:28, 24:28] = 0
        other = np.full_like(mask, 255); other[24:28, 24:28] = 2
        l = world(); l.family[6, 6] = 2
        apply_surfaces(l, [self.source('paving', mask=mask), self.source('grass', mask=other)], 'pinned')
        self.assertEqual(l.family[6, 6], 2)
        self.assertTrue(l.guide_exclusions[6, 6])
        self.assertEqual(l.audit['surface_guides']['conflicting_source_columns_unchanged'], 1)

    def test_water_building_protected_detail_and_roof_screen_new_paving(self):
        mask = np.full((64, 64), 0, np.uint8)
        l = world(); l.water[6, 5] = 1; l.footprints[6, 6] = True
        l.protected[6, 7] = True; l.cloud['roof'][6, 8] = 5
        apply_surfaces(l, [self.source('all', mask=mask)], 'pinned')
        self.assertTrue(np.all(l.family[6, 5:9] == 0))
        self.assertEqual(int((l.family > 0).sum()), 252)

    def test_explicit_grass_clears_paving_without_erasing_a_bridge(self):
        mask = np.full((64, 64), 255, np.uint8); mask[24:28, 24:32] = 2
        l = world(); l.family[6, 6:8] = 3; l.bridge[6, 7] = 3
        apply_surfaces(l, [self.source('grass', mask=mask)], 'pinned')
        self.assertEqual(l.family[6, 6], 0); self.assertEqual(l.family[6, 7], 3)
        self.assertEqual(l.audit['surface_guides']['cleared_paving_for_grass_columns'], 1)

    def test_finest_clean_rgb_wins_independent_of_manifest_order(self):
        coarse = self.source('coarse', size=16, colour=40)
        fine = self.source('fine', size=64, colour=200)
        a, b = world(), world()
        merge_rgb(a, [fine, coarse], 'pinned'); merge_rgb(b, [coarse, fine], 'pinned')
        np.testing.assert_array_equal(a.rgb, b.rgb)
        np.testing.assert_allclose(a.rgb[7, 7], 200)
        np.testing.assert_array_equal(a.rgb[0, 0], [10, 10, 10])
        self.assertGreater(a.audit['aerial_mosaic']['supplemental_columns'], 0)

    def test_manifest_rejects_sparse_traces_and_changed_masks(self):
        source = self.source('draft', mask=np.zeros((64, 64), np.uint8))
        manifest = {'version': VERSION, 'labels': LABELS, 'layers': [source['entry']]}
        path = self.root/'layers.json'; path.write_text(json.dumps(manifest))
        self.assertEqual(len(load_manifest(path)[0]), 1)
        source['entry']['role'] = 'sparse_positive_location_or_trace'; path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Sparse traces'): load_manifest(path)
        source['entry']['role'] = 'partial_source_assisted_surface_interiors'; path.write_text(json.dumps(manifest))
        Image.fromarray(np.full((64, 64), 2, np.uint8)).save(source['mask_path'])
        with self.assertRaisesRegex(ValueError, 'checksum'): load_manifest(path)

    def test_coarser_export_cannot_replace_the_base_image(self):
        l = world()
        merge_rgb(l, [self.source('coarser', size=16, colour=200)], 'pinned', np.full((16, 16), .5))
        self.assertTrue(np.all(l.rgb == 10))
        self.assertEqual(l.audit['aerial_mosaic']['supplemental_columns'], 0)

    def test_broad_paving_trace_cannot_fill_a_green_island_even_below_crowns(self):
        mask = np.zeros((64, 64), np.uint8)
        l = world(); l.green[5:8, 5:8] = True
        l.chm[6, 6] = 10
        apply_surfaces(l, [self.source('broad-plaza', mask=mask)], 'pinned')
        self.assertTrue(np.all(l.family[5:8, 5:8] == 0))
        self.assertEqual(int((l.family > 0).sum()), 247)
        self.assertEqual(l.audit['surface_guides']['paving_screened_by_green_rgb_columns'], 9)

    def test_explicit_rock_edged_island_screens_bare_soil_and_preserves_mapped_path(self):
        mask = np.zeros((64, 64), np.uint8)
        s = self.source('plaza', mask=mask)
        s['entry']['exclusions_sha256'] = 'pinned'
        s['exclusions'] = {'source': {'scope':'user-confirmed rock outline, assistant interior trace'}, 'features': [
            {'geometry':{'type':'Polygon','coordinates':[[[4,4],[8,4],[8,8],[4,8],[4,4]]]}}]}
        l = world(); l.family[9,5] = 3
        apply_surfaces(l, [s], 'pinned')
        self.assertEqual(int((l.family[8:12,4:8] == 0).sum()), 15)
        self.assertEqual(int(l.guide_added[8:12,4:8].sum()), 0)
        self.assertTrue(np.all(l.guide_exclusions[8:12,4:8]))
        self.assertEqual(l.family[9,5], 3)
        self.assertEqual(l.audit['surface_guides']['explicit_nonpaving_island_columns'], 16)
