import unittest
from types import SimpleNamespace

import numpy as np
from shapely.geometry import Polygon

from voxel_mapper.alton_aligned_world import ChunkRenderer, _local_mask, _native_roof


def layers():
    shape = (16, 16)
    cloud = {'vegetation': np.full(shape, np.nan), 'leaf_voxels': np.empty(0, np.uint64),
             'leaf_chunk_offsets': np.array([0, 0])}
    return SimpleNamespace(width=16, height=16, offset=0, ground=np.full(shape, 64, np.int16),
        material=np.full(shape, 'grass_block', dtype='U24'),
        roof_material=np.full(shape, 'stone_slab', dtype='U24'),
        wall_material=np.full(shape, 'stone_bricks', dtype='U24'),
        building_floor=np.full(shape, -32768, np.int16), roof_half=np.full(shape, -32768, np.int16),
        water=np.full(shape, -32768, np.int16), bridge=np.full(shape, -32768, np.int16),
        wall=np.zeros(shape, bool), footprints=np.zeros(shape, bool), protected=np.zeros(shape, bool),
        family=np.zeros(shape, np.uint8), tree_species=np.zeros(shape, np.uint8), cloud=cloud,
        detail={}, clear={}, trunks={}, spawn=[15, 66, -1])


class AltonWorldTests(unittest.TestCase):
    def test_polygon_holes_and_north_up_native_cells(self):
        geometry = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)],
                           holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]])
        r, c, mask = _local_mask(geometry, [0, 0, 16, 16], (16, 16))
        self.assertEqual((r.start, r.stop, c.start, c.stop), (12, 16, 0, 4))
        self.assertEqual(mask.sum(), 12)
        self.assertFalse(mask[1, 1])

    def test_missing_roof_uses_only_in_footprint_observations(self):
        observed = np.full((5, 5), np.nan)
        footprint = np.zeros((5, 5), bool); footprint[1:4, 1:4] = True
        observed[0, 0] = 100  # canopy outside the building must never seed its roof
        observed[2, 2] = 12
        roof, count = _native_roof(observed, footprint, 4, 3)
        self.assertEqual(count, 1)
        self.assertTrue(np.all(roof[footprint] == 12))

    def test_water_bed_bridge_and_hollow_slab_roof_remain_separate(self):
        l = layers(); l.water[2, 2] = 64; l.bridge[2, 2] = 67
        l.footprints[5, 5] = True; l.building_floor[5, 5] = 64; l.roof_half[5, 5] = 148
        renderer = ChunkRenderer(l); arr, bottom = renderer.chunk(0, -1)
        def material(x, y, z): return renderer.materials[int(arr[x, y-bottom, z])]
        self.assertEqual(material(2, 62, 2), 'stone')
        self.assertEqual(material(2, 63, 2), 'water')
        self.assertEqual(material(2, 65, 2), 'air')
        self.assertEqual(material(2, 67, 2), 'stone_bricks')
        self.assertEqual(material(5, 65, 5), 'air')
        self.assertEqual(material(5, 73, 5), 'stone_slab_top')
        self.assertEqual(material(5, 74, 5), 'air')

    def test_retained_track_and_clearance_override_foliage(self):
        l = layers(); l.cloud['vegetation'][3, 3] = 72
        packed = np.array([(3*16+3) | ((67+512) << 22)], np.uint64)
        l.cloud.update(leaf_voxels=packed, leaf_chunk_offsets=np.array([0, 1]))
        l.detail[(0, -1)] = [(3, 66, 3, 'dark_oak_fence')]
        l.clear[(0, -1)] = [(3, 67, 3)]
        renderer = ChunkRenderer(l); arr, bottom = renderer.chunk(0, -1)
        self.assertEqual(renderer.materials[int(arr[3, 66-bottom, 3])], 'dark_oak_fence')
        self.assertEqual(renderer.materials[int(arr[3, 67-bottom, 3])], 'air')

    def test_reference_geometry_is_saved_and_retained_track_keeps_priority(self):
        l=layers();l.reference_detail={(0,-1):[(3,70,3,'white_concrete'),(4,66,4,'red_concrete')]}
        l.reference_air={(0,-1):[(3,65,3)]};l.detail={(0,-1):[(4,66,4,'dark_oak_fence')]}
        renderer=ChunkRenderer(l);arr,bottom=renderer.chunk(0,-1)
        self.assertEqual(renderer.materials[int(arr[3,70-bottom,3])],'white_concrete')
        self.assertEqual(renderer.materials[int(arr[3,65-bottom,3])],'air')
        self.assertEqual(renderer.materials[int(arr[4,66-bottom,4])],'dark_oak_fence')
