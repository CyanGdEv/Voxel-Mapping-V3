"""Retain an exact Alton window from the checksum-pinned upstream OSTN15 grid."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window

from voxel_mapper.horizontal_grid import ORIGINAL_SHA256, PIPELINE, SOURCE_URL


def retain(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != ORIGINAL_SHA256:
            raise ValueError('Original OSTN15 grid checksum mismatch')
    if output.exists():
        raise ValueError('Use a fresh grid output directory')
    output.mkdir(parents=True)
    target = output / 'alton-ostn15-grid.tif'
    window = Window(420, 956, 13, 13)
    with rasterio.open(source) as grid:
        values = grid.read(window=window)
        profile = grid.profile.copy()
        profile.update(width=13, height=13, transform=grid.window_transform(window),
                       tiled=False, blockxsize=13, blockysize=13)
        with rasterio.open(target, 'w', **profile) as crop:
            crop.write(values)
            crop.update_tags(**grid.tags())
            for index in grid.indexes:
                crop.set_band_description(index, grid.descriptions[index - 1])
                crop.update_tags(index, **grid.tags(index))
                crop.set_band_unit(index, grid.units[index - 1])
    original = Transformer.from_pipeline(PIPELINE.format(grid=source.as_posix()))
    cropped = Transformer.from_pipeline(PIPELINE.format(grid=target.as_posix()))
    checks = []
    for lon in (-1.8962, -1.8952, -1.8942):
        for lat in (52.9870, 52.98728, 52.9876):
            expected = original.transform(lon, lat, errcheck=True)
            actual = cropped.transform(lon, lat, errcheck=True)
            error = float(np.linalg.norm(np.asarray(expected) - actual))
            if error > 1e-6:
                raise ValueError('Cropped operation differs from original grid')
            checks.append({'wgs84': [lon, lat], 'original_bng_m': list(expected), 'crop_error_m': error})
    with rasterio.open(target) as crop:
        if not np.array_equal(crop.read(), values):
            raise ValueError('Grid samples changed during retention')
        bounds = list(crop.bounds)
    receipt = {'original_url': SOURCE_URL, 'original_sha256': ORIGINAL_SHA256,
               'crop_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
               'crop_bytes': target.stat().st_size, 'crop_bounds_osgb36_degrees': bounds,
               'window_columns_rows': [420, 956, 13, 13],
               'sample_values_sha256': hashlib.sha256(values.tobytes()).hexdigest(),
               'derivation': 'Exact source sample window; no resampling. All four bands, units, coordinates and source metadata retained.',
               'license': 'BSD-2-Clause', 'attribution': 'Derived from work by Ordnance Survey via PROJ-data.',
               'license_reference': 'https://raw.githubusercontent.com/OSGeo/PROJ-data/master/uk_os/uk_os_README.txt',
               'operation_equivalence_checks': checks,
               'independent_placement_accuracy': 'not_verified', 'vertical_transformation': False}
    (output / 'alton-ostn15-grid-provenance.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(retain(args.source, args.output)))
