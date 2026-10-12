import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from voxel_mapper.alton_world import merge_raster
from voxel_mapper.bedrock import export_world


class FullParkTests(unittest.TestCase):
    def raster(self,path,values,origin):
        with rasterio.open(path,'w',driver='GTiff',height=values.shape[0],width=values.shape[1],
                           count=1,dtype='float32',crs='EPSG:27700',transform=from_origin(*origin,1,1),nodata=-9999) as ds:
            ds.write(values.astype('float32'),1)

    def test_dated_patch_replaces_only_valid_aligned_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);self.raster(p/'base.tif',np.full((4,4),10),(400000,300004))
            self.raster(p/'patch.tif',np.array([[20,-9999],[30,40]]),(400001,300003))
            report=merge_raster(p/'base.tif',p/'patch.tif',p/'merged.tif')
            with rasterio.open(p/'merged.tif') as ds:values=ds.read(1)
            np.testing.assert_array_equal(values[1:3,1:3],[[20,10],[30,40]])
            self.assertEqual(report['replaced_cells'],3)
            self.assertEqual(report['patch_missing_cells_preserved_from_base'],1)

    def test_misaligned_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);self.raster(p/'base.tif',np.ones((4,4)),(400000,300004))
            self.raster(p/'patch.tif',np.ones((2,2)),(400000.5,300003))
            with self.assertRaisesRegex(ValueError,'align'):merge_raster(p/'base.tif',p/'patch.tif',p/'merged.tif')

    def test_chunk_foundations_preserve_hills_with_bounded_block_count(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);rows=[{'x':0,'y':10,'z':0,'kind':'terrain'},
                                   {'x':32,'y':110,'z':0,'kind':'terrain'}]
            (p/'v.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            q=export_world(p/'v.jsonl',p,{'voxel_size_m':1},max_blocks=40,foundation_mode='chunk')
            self.assertEqual(q['composed_blocks'],34)
            self.assertEqual(q['foundation']['mode'],'chunk')
            self.assertEqual(q['round_trip_validation'],'all written blocks and all unwritten air cells verified')
            with self.assertRaisesRegex(ValueError,'budget'):export_world(p/'v.jsonl',p/'shared',{'voxel_size_m':1},max_blocks=40)
