import tempfile
import unittest
from pathlib import Path

from voxel_mapper.landcover import acquire, request_grid

try:
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds
except ImportError:
    rasterio = None

class Response:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield self.data
    def close(self): pass

class LandcoverTests(unittest.TestCase):
    bounds = (-1.9, 52.98, -1.899, 52.981)

    def test_grid(self):
        grid, width, height = request_grid(self.bounds)
        self.assertTrue(all(v % 10 == 0 for v in grid))
        self.assertEqual(width*10, grid[2]-grid[0])
        self.assertEqual(height*10, grid[3]-grid[1])

    def test_budget(self):
        with self.assertRaisesRegex(ValueError,"budget"):
            request_grid((-10,40,10,50))

    @unittest.skipIf(rasterio is None, "install .[gis]")
    def test_raw_classes_and_year(self):
        grid, width, height = request_grid(self.bounds)
        with MemoryFile() as mem:
            with mem.open(driver="GTiff",width=width,height=height,count=1,dtype="uint8",
                          crs="EPSG:3857",transform=from_bounds(*grid,width,height),nodata=0) as dst:
                dst.write(np.full((height,width),2,dtype=np.uint8),1)
            data = mem.read()
        def get(url,params,timeout,stream):
            self.assertIn("Year = 2024",params["mosaicRule"])
            self.assertEqual(params["interpolation"],"RSP_NearestNeighbor")
            return Response(data)
        with tempfile.TemporaryDirectory() as temp:
            report = acquire(self.bounds,2024,Path(temp),get=get)
            self.assertEqual(report["class_counts"],{2:width*height})
            self.assertEqual(report["usable_fraction"],1)
            self.assertTrue((Path(temp)/report["path"]).is_file())

    @unittest.skipIf(rasterio is None, "install .[gis]")
    def test_reject_rendered_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,"raw TIFF"):
                acquire(self.bounds,2025,Path(temp),get=lambda *a,**kw:Response(b'{"error":"token required"}'))

if __name__ == "__main__":
    unittest.main()
