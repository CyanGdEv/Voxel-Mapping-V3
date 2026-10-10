import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_wicker_terrain_section import build, candidate_cells, pinned_archives
from voxel_mapper.shop_slabs import assemble
from voxel_mapper.shop_wall_details import decorate
from voxel_mapper.reconstruction.local_buildings import rotate_model

ROOT = Path(__file__).resolve().parents[1]


class TerrainSectionTests(unittest.TestCase):
    def test_changed_raster_and_wrong_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'dtm.zip'
            for name, message in [('DTM_SK0540_P_10682_20220105_20220105.tif', 'checksum'),
                                  ('DTM_SK0540_P_999_20230105_20230105.tif', 'pinned dated')]:
                with zipfile.ZipFile(p,'w') as z:
                    z.writestr(name, b'changed survey')
                with self.assertRaisesRegex(ValueError, message):
                    pinned_archives({'dtm':p, 'dsm':p})

    def test_candidate_native_orientation_preserves_all_mesh_cells(self):
        model = json.loads((ROOT/'evidence/wicker-shop-projection-model.json').read_text())
        angle = -154.75564001904897
        rotated = rotate_model(model,angle)
        raw,_ = assemble(rotated)
        raw,_ = decorate(rotated,raw)
        native = candidate_cells(model,{'rotation_degrees':angle})
        self.assertEqual(set(raw),set(native))
        for p,material in raw.items():
            if material.endswith('_trapdoor_north'):
                self.assertEqual(native[p],material.removesuffix('_north')+'_south')
            elif material.endswith('_trapdoor_south'):
                self.assertEqual(native[p],material.removesuffix('_south')+'_north')
            else:
                self.assertEqual(native[p],material)

    def test_invalid_provisional_floor_fails_before_acquisition(self):
        for floor in (float('nan'), float('inf'), True, 10001):
            with self.assertRaisesRegex(ValueError,'provisional floor'):
                build('missing','missing','missing','missing','missing','missing',floor)
