"""Describe export sampling separately from point-reported intrinsic imagery detail."""
import datetime
import math

from pyproj import Transformer


def audit(receipt):
    width, height = receipt.get('width'), receipt.get('height')
    if any(type(v) is not int or not 1 <= v <= 4096 for v in (width, height)):
        raise ValueError('Positive native image dimensions required')
    extent = receipt.get('extent_epsg3857')
    if not isinstance(extent, list) or len(extent) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in extent) or not extent[0] < extent[2] or not extent[1] < extent[3]:
        raise ValueError('Finite projected imagery extent required')
    _, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform((extent[0]+extent[2])/2, (extent[1]+extent[3])/2)
    scale = math.cos(math.radians(lat))
    pixels = [(extent[2]-extent[0])/width*scale, (extent[3]-extent[1])/height*scale]
    observations = []; resolutions = []
    for row in receipt.get('point_source_metadata', []):
        try: value = float(row.get('RESOLUTION (M)', 'nan'))
        except (ValueError, TypeError): value = float('nan')
        if math.isfinite(value) and value > 0: resolutions.append(value)
        date = row.get('DATE (YYYYMMDD)'); parsed = None
        if isinstance(date, str):
            try: parsed = datetime.datetime.strptime(date, '%Y%m%d').date().isoformat()
            except ValueError: pass
        if math.isfinite(value) and value > 0 or parsed:
            item = {'point_resolution_m': value if math.isfinite(value) and value > 0 else None,
                'point_capture_date': parsed, 'source': row.get('SOURCE'), 'description': row.get('DESCRIPTION')}
            if item not in observations: observations.append(item)
    best = min(resolutions) if resolutions else None
    return {'version': 'imagery-capture-quality-v1', 'image_sha256': receipt.get('image_sha256'),
        'native_export_dimensions': [width, height], 'approx_export_ground_sampling_m_xy': pixels,
        'finest_reported_point_resolution_m': best, 'point_observations': observations,
        'export_finer_than_reported_point_source': bool(best and min(pixels) < best*.95),
        'whole_image_capture_date_verified': False, 'whole_image_intrinsic_resolution_verified': False,
        'genuine_resolution_upgrade_verified': False,
        'limitations': ['Export pixel spacing is not proof of independent optical detail.',
            'Point metadata is not automatically valid across an entire mosaic.',
            'Capture date/resolution observations do not verify physical registration.']}
