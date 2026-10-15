import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pyproj import CRS
from pyproj.exceptions import ProjError
import rasterio

from voxel_mapper.horizontal_grid import OSTN15Transform, VERSION
from voxel_mapper.terrain import Terrain

ROOT = Path(__file__).resolve().parents[1]
GRID = ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid.tif'
PROOF = ROOT / 'docs/evidence/world-pilot/alton-ostn15-grid-provenance.json'


class HorizontalGridTests(unittest.TestCase):
    def specification(self, path=GRID):
        return {'method': VERSION, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_retained_samples_match_original_operation_checks_without_global_grid_setup(self):
        proof = json.loads(PROOF.read_text())
        operation = OSTN15Transform(4326, 27700, self.specification())
        for check in proof['operation_equivalence_checks']:
            observed = operation.transform(*check['wgs84'])
            for actual, expected in zip(observed, check['original_bng_m']):
                self.assertAlmostEqual(actual, expected, places=6)
            recovered = operation.inverse(*observed)
            for actual, expected in zip(recovered, check['wgs84']):
                self.assertAlmostEqual(actual, expected, places=9)
        with rasterio.open(GRID) as grid:
            self.assertEqual(hashlib.sha256(grid.read().tobytes()).hexdigest(), proof['sample_values_sha256'])
        report = operation.report()
        self.assertFalse(report['fallback_allowed'])
        self.assertFalse(report['vertical_transformation'])
        self.assertEqual(report['independent_placement_accuracy'], 'not_verified')

    def test_outside_grid_wrong_crs_and_wrong_datum_do_not_fall_back(self):
        operation = OSTN15Transform(4326, 27700, self.specification())
        with self.assertRaises(ProjError):
            operation.transform(0, 0)
        for source, target in [(4326, 3857), (4269, 27700)]:
            with self.assertRaises(ValueError):
                OSTN15Transform(source, target, self.specification())

    def test_checksum_mismatch_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='grid path ') as temporary:
            path = Path(temporary) / 'grid file.tif'
            shutil.copyfile(GRID, path)
            specification = self.specification(path)
            operation = OSTN15Transform(4326, 27700, specification)
            self.assertAlmostEqual(operation.transform(-1.8952, 52.98728)[0], 407132.5125101812, places=6)
            with path.open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                OSTN15Transform(4326, 27700, specification)

    def test_terrain_uses_fixed_operation_for_actual_source_pixel_and_reports_it(self):
        path = ROOT / 'docs/evidence/smiler-review/ea-national-dtm.tif'
        config = {'path': str(path), 'source_id': 'dem', 'units': 'm', 'vertical_datum': 'ODN',
                  'horizontal_operation': self.specification()}
        with rasterio.open(path) as raster:
            row, column = raster.index(407132.5125101812, 343330.20242216287)
            expected = float(raster.read(1)[row, column])
        terrain = Terrain(config, CRS.from_epsg(4326), {'dem': {}})
        try:
            self.assertEqual(terrain.sample(-1.8952, 52.98728), expected)
            report = terrain.report()['coordinate_transform']
            self.assertEqual(report['accuracy_m'], 1.0)
            self.assertEqual(report['pinned_operation']['grid_sha256'], self.specification()['sha256'])
        finally:
            terrain.close()


if __name__ == '__main__':
    unittest.main()
