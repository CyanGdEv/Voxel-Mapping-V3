import unittest
import numpy as np

from voxel_mapper.appearance_palettes import PALETTES, choose, strength
from voxel_mapper.bedrock import ALLOWED_MATERIALS, PLAN_MARKING_WOOLS, material_block



class AppearanceTests(unittest.TestCase):
    def test_brick_strength_tracks_redness_without_brightness_bias(self):
        assert strength('brick', [180, 110, 80]) > strength('brick', [160, 151, 140])
        assert np.isclose(strength('brick', [180, 110, 80]), strength('brick', [90, 55, 40]))


    def test_asphalt_strength_tracks_darkness(self):
        assert strength('asphalt', [40, 42, 44]) > strength('asphalt', [140, 142, 144])


    def test_two_variants_and_stone_recipe_use_supported_blocks(self):
        assert set(PALETTES) == {'brick_strong', 'brick_faded', 'asphalt_strong', 'asphalt_faded', 'stone'}
        for palette in PALETTES.values():
            assert sum(weight for _, weight in palette) == 100
            for material, _ in palette:
                assert material in ALLOWED_MATERIALS
                material_block(material)
        assert 'gray_wool' not in PLAN_MARKING_WOOLS
        assert str(material_block('gray_wool').properties['color']) == 'gray'


    def test_palette_is_independent_of_chunk_partition(self):
        r, c = np.indices((32, 32))
        rgb = np.full((32, 32, 3), [150, 110, 85])
        whole, _ = choose('brick', rgb, c+407000, r+343000)
        piece, _ = choose('brick', rgb[16:, :16], c[16:, :16]+407000, r[16:, :16]+343000)
        assert np.array_equal(piece, whole[16:, :16])
        assert set(whole.ravel()) <= {m for key in ('brick_strong', 'brick_faded') for m, _ in PALETTES[key]}


    def test_stone_is_one_recipe_independent_of_rgb(self):
        r, c = np.indices((20, 20))
        dark, _ = choose('stone', np.full((20, 20, 3), 20), c, r)
        light, _ = choose('stone', np.full((20, 20, 3), 230), c, r)
        assert np.array_equal(dark, light)
