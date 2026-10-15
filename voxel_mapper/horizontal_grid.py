"""An explicit, offline OSTN15 operation; never fall back to a Helmert fit."""
import hashlib
from pathlib import Path
import re

from pyproj import CRS, Transformer
import rasterio

VERSION = 'ostn15-bng-v1'
ORIGINAL_SHA256 = '5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa'
SOURCE_URL = 'https://cdn.proj.org/uk_os_OSTN15_NTv2_OSGBtoETRS.tif'
PIPELINE = ('+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad '
            '+step +inv +proj=hgridshift +grids="{grid}" '
            '+step +proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 '
            '+x_0=400000 +y_0=-100000 +ellps=airy')


class OSTN15Transform:
    """WGS84-based local coordinates to BNG, with a pinned horizontal grid.

    The advertised 1 m accuracy is the EPSG:7710 WGS84 approximation, not
    independent survey validation. No vertical transformation is performed.
    """
    accuracy = 1.0
    description = 'Explicit OSTN15 WGS84-to-OSGB36 grid operation and British National Grid projection'

    def __init__(self, local_crs, target_crs, specification):
        local = CRS.from_user_input(local_crs)
        if (specification.get('method') != VERSION or CRS.from_user_input(target_crs) != CRS.from_epsg(27700)
                or not local.geodetic_crs.equals(CRS.from_epsg(4326), ignore_axis_order=True)):
            raise ValueError('Pinned OSTN15 requires a WGS84-based input and EPSG:27700 raster')
        self.path = Path(specification['path']).resolve()
        self.sha256 = specification.get('sha256')
        if (not isinstance(self.sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.sha256)
                or '"' in str(self.path)):
            raise ValueError('Pinned horizontal grid path and SHA256 required')
        with self.path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.sha256:
                raise ValueError('Horizontal grid checksum mismatch')
        with rasterio.open(self.path) as grid:
            if (grid.crs != rasterio.crs.CRS.from_epsg(4277) or grid.count != 4
                    or grid.width * grid.height > 1_000_000
                    or grid.tags().get('TYPE') != 'HORIZONTAL_OFFSET'
                    or grid.descriptions[:2] != ('latitude_offset', 'longitude_offset')
                    or grid.units[:2] != ('arc-second', 'arc-second')):
                raise ValueError('Expected a bounded OSGB36 OSTN15 horizontal-offset grid')
            self.bounds = list(grid.bounds)
        self.local_to_wgs84 = Transformer.from_crs(local, 4326, always_xy=True, allow_ballpark=False)
        self.grid_to_bng = Transformer.from_pipeline(PIPELINE.format(grid=self.path.as_posix()))

    def transform(self, x, y):
        lon, lat = self.local_to_wgs84.transform(x, y, errcheck=True)
        # errcheck is mandatory: points outside the retained grid cannot select
        # a lower-accuracy operation or receive an identity transformation.
        return self.grid_to_bng.transform(lon, lat, errcheck=True)

    def get_last_used_operation(self):
        return self

    def report(self):
        return {'method': VERSION, 'grid_sha256': self.sha256,
                'grid_bounds_osgb36_degrees': self.bounds, 'advertised_accuracy_m': self.accuracy,
                'original_grid_sha256': ORIGINAL_SHA256,
                'pipeline': PIPELINE.format(grid='<pinned-grid>'),
                'fallback_allowed': False, 'vertical_transformation': False,
                'independent_placement_accuracy': 'not_verified',
                'accuracy_basis': 'EPSG:7710 approximates ETRS89 as WGS84 at advertised 1 m accuracy; no epoch correction.'}
