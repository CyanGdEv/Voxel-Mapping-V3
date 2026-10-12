"""Reviewed orthophoto masks; imagery supplies evidence, never guessed semantics."""
import hashlib
from pathlib import Path
import numpy as np
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.windows import Window
from pyproj import CRS
from shapely.geometry import shape, mapping
from .model import EvidenceMissing


def imagery_masks_adapter(data, source, base_directory):
    from .sources import geojson_adapter
    if source.kind != 'imagery' or source.registration_status != 'accepted':
        raise EvidenceMissing('Imagery registration must be accepted')
    capture_date = source.metadata.get('capture_date')
    if not capture_date:
        raise EvidenceMissing('Imagery capture date required')
    spec = data['imagery']
    path = Path(base_directory) / spec['file']
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not spec.get('sha256') or spec['sha256'] != digest:
        raise EvidenceMissing('Imagery hash missing or changed')
    accepted = []
    decisions = []
    with rasterio.open(path) as raster:
        if raster.crs is None or CRS.from_user_input(raster.crs) != CRS.from_user_input(source.crs):
            raise EvidenceMissing('Imagery CRS missing or differs from source')
        if raster.count < 3:
            raise EvidenceMissing('RGB imagery requires at least three bands')
        for index, item in enumerate(data.get('features', [])):
            identifier = str(item.get('id', f'{source.id}/{index}'))
            try:
                properties = item.get('properties', {})
                if properties.get('reviewed') is not True or not properties.get('reviewer'):
                    raise EvidenceMissing('Polygon needs explicit review and reviewer')
                if properties.get('kind') not in ('path', 'plaza', 'sidewalk', 'queue'):
                    raise EvidenceMissing('Only reviewed pedestrian paving masks supported')
                geom = shape(item['geometry'])
                if geom.geom_type not in ('Polygon', 'MultiPolygon') or geom.is_empty or not geom.is_valid or geom.has_z:
                    raise EvidenceMissing('Valid 2D paving polygon required')
                # Rotated rasters use their true quadrilateral footprint, not bounds.
                from shapely.geometry import Polygon
                footprint = Polygon([raster.transform * point for point in
                                     ((0, 0), (raster.width, 0), (raster.width, raster.height), (0, raster.height))])
                if not footprint.covers(geom):
                    raise EvidenceMissing('Polygon extends beyond imagery')
                window = geometry_window(raster, [mapping(geom)])
                if window.width * window.height > 4_000_000:
                    raise EvidenceMissing('Polygon imagery window exceeds pixel budget')
                pixels = 0
                for row in range(int(window.row_off), int(window.row_off + window.height), 512):
                    for col in range(int(window.col_off), int(window.col_off + window.width), 512):
                        tile = Window(col, row, min(512, window.col_off + window.width - col),
                                      min(512, window.row_off + window.height - row))
                        inside = geometry_mask([mapping(geom)], out_shape=(int(tile.height), int(tile.width)),
                                               transform=raster.window_transform(tile), invert=True, all_touched=True)
                        valid = np.all(raster.read_masks([1, 2, 3], window=tile) > 0, axis=0)
                        # Dataset mask also handles an alpha band or external mask.
                        valid &= raster.dataset_mask(window=tile) > 0
                        if np.any(inside & ~valid):
                            raise EvidenceMissing('Polygon intersects nodata or transparent imagery')
                        pixels += int(inside.sum())
                if not pixels:
                    raise EvidenceMissing('Polygon has no imagery pixels')
                feature = geojson_adapter({'features': [item]}, source)[0]
                feature.id = identifier
                if not any(key in feature.parameters for key in ('surface', 'material')):
                    raise EvidenceMissing('Reviewed material or surface required')
                feature.metadata.update(imagery_sha256=digest, capture_date=capture_date,
                                        reviewer=properties['reviewer'], imagery_pixels=pixels,
                                        pixel_size=list(raster.res), material_inferred_from_colour=False)
                accepted.append(feature)
                decisions.append({'id': identifier, 'status': 'accepted', 'imagery_pixels': pixels})
            except (EvidenceMissing, ValueError, KeyError) as error:
                decisions.append({'id': identifier, 'status': 'withheld', 'reason': str(error)})
    return accepted, decisions
