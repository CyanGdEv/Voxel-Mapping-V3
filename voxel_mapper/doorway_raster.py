"""Finite source opening spans cut through a quantized, one-metre display wall."""
import math

from .shop_shell import opening_columns

VERSION = 'native-wall-opening-v1'
PLAYER_WIDTH_M = .6


def wall_openings(openings):
    """Return a bounded native void mask and explicit width-quantization evidence.

    A cell centre must project between the original jambs and lie within one
    cell's normal projection radius of their plane. This can clear both native
    columns of an oblique display wall without moving either source endpoint.
    The resulting cell envelope is an approximation, not a measured aperture.
    """
    if not isinstance(openings, list) or len(openings) > 128:
        raise ValueError('Bounded source opening list required')
    masks, reports = {}, []
    for index, opening in enumerate(openings):
        points = opening.get('endpoints')
        height = opening.get('height_metres')
        if (not isinstance(points, list) or len(points) != 2
                or any(not isinstance(p, list) or len(p) != 3 or
                       any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 200 for v in p)
                       for p in points)
                or type(height) not in (int, float) or not math.isfinite(height) or not 0 < height <= 64):
            raise ValueError('Finite bounded opening endpoints and height required')
        a, b = points
        width = math.hypot(b[0] - a[0], b[1] - a[1])
        if width < 1e-8:
            raise ValueError('Nondegenerate source opening span required')
        ux, uz = (b[0] - a[0]) / width, (b[1] - a[1]) / width
        radius = .5 * (abs(ux) + abs(uz))
        legacy = opening_columns([opening], 1)
        columns = set(legacy)
        x0, x1 = math.floor(min(a[0], b[0]) - 1), math.ceil(max(a[0], b[0]) + 1)
        z0, z1 = math.floor(min(a[1], b[1]) - 1), math.ceil(max(a[1], b[1]) + 1)
        if (x1 - x0) * (z1 - z0) > 16_384:
            raise ValueError('Opening raster sampling budget exceeded')
        if width >= PLAYER_WIDTH_M:
            for x in range(x0, x1):
                for z in range(z0, z1):
                    dx, dz = x + .5 - a[0], z + .5 - a[1]
                    along, normal = dx * ux + dz * uz, -dx * uz + dz * ux
                    if -1e-9 <= along <= width + 1e-9 and abs(normal) <= radius + 1e-9:
                        columns.add((x, z))
        head = math.floor(height)
        for column in columns:
            masks[column] = max(masks.get(column, 0), head)
        along = [(x + .5 - a[0]) * ux + (z + .5 - a[1]) * uz for x, z in columns]
        low, high = (min(along) - radius, max(along) + radius) if along else (None, None)
        reports.append({'id': opening.get('id', str(index)), 'source_width_m': width, 'source_height_m': height,
            'source_endpoints': points, 'native_columns_xz': [list(p) for p in sorted(columns)],
            'legacy_columns_xz': [list(p) for p in sorted(legacy)],
            'additional_columns_xz': [list(p) for p in sorted(columns - set(legacy))],
            'normal_cell_projection_radius_m': radius,
            'native_cell_envelope_width_m': high - low if along else None,
            'endpoint_envelope_overruns_m': [max(0, -low), max(0, high - width)] if along else None,
            'representation_status': ('source_too_narrow_for_player' if width < PLAYER_WIDTH_M else
                                      'quantized_source_aperture' if columns else 'unrepresented_on_native_grid'),
            'native_geometry_exact': False})
    return masks, {'version': VERSION, 'source_geometry_modified': False, 'world_blocks_per_source_metre': 1,
        'minimum_source_player_width_m': PLAYER_WIDTH_M, 'openings': reports,
        'limitations': ['Cell envelopes can exceed the original jamb span; per-end overruns are explicit.',
                        'Normal band describes display raster thickness, not measured wall thickness.',
                        'Source endpoints and mesh dimensions are unchanged; native aperture geometry is approximate.']}
