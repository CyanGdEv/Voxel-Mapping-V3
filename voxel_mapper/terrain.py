"""GeoTIFF terrain sampling with explicit source and vertical datum contracts."""
import math
import hashlib
import numpy as np
from pathlib import Path
import rasterio
from pyproj import Transformer


class Terrain:
    def __init__(self, config, local_crs, sources):
        self.config = config
        if config.get('source_id') not in sources:
            raise ValueError('Terrain requires a registered source_id')
        if not config.get('vertical_datum'):
            raise ValueError('Terrain requires vertical_datum; no automatic vertical transformation')
        if config.get('units') != 'm':
            raise ValueError('Terrain elevation units must explicitly be m')
        self.dataset = rasterio.open(config['path'])
        if self.dataset.crs is None:
            self.dataset.close()
            raise ValueError('Terrain raster has no horizontal CRS')
        self.transformer = Transformer.from_crs(local_crs, self.dataset.crs, always_xy=True)
        self.offset = float(config.get('offset_m', 0))
        if not math.isfinite(self.offset):
            self.dataset.close()
            raise ValueError('Terrain offset must be finite')
        if self.dataset.width*self.dataset.height > 16_000_000:
            self.dataset.close()
            raise ValueError("Terrain raster exceeds in-memory pixel budget")
        self.values = self.dataset.read(1, masked=True)
        self.inverse = ~self.dataset.transform
        self.sampled = self.missing = 0
        with Path(config['path']).open('rb') as stream:
            self.checksum = hashlib.file_digest(stream, 'sha256').hexdigest()

    def sample(self, x, z):
        self.sampled += 1
        rx, ry = self.transformer.transform(x, z)
        col, row = self.inverse * (rx, ry)
        row, col = math.floor(row), math.floor(col)
        if not (0 <= row < self.dataset.height and 0 <= col < self.dataset.width):
            self.missing += 1
            return None
        value = self.values[row, col]
        if np.ma.is_masked(value) or not math.isfinite(float(value)):
            self.missing += 1
            return None
        return float(value) + self.offset

    def report(self):
        try:
            operation = self.transformer.get_last_used_operation()
            transform_info = {'accuracy_m':operation.accuracy, 'description':operation.description}
        except Exception:
            transform_info = {'accuracy_m':self.transformer.accuracy, 'description':self.transformer.description}
        return {'source_id': self.config['source_id'], 'vertical_datum': self.config['vertical_datum'],
                'sha256': self.checksum, 'horizontal_crs': self.dataset.crs.to_wkt(),
                'pixel_size_native_units': list(self.dataset.res), 'sampling': 'nearest neighbour',
                'coordinate_transform':transform_info, 'sample_requests': self.sampled, 'missing_requests': self.missing}

    def close(self):
        self.dataset.close()
