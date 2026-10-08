"""Evidence-gated architectural components, rather than solid building boxes."""
import math
from shapely.geometry import shape, box
from shapely.affinity import rotate, translate
from .model import Feature, EvidenceMissing
from .generators import number


def architectural_components(feature, geom, ctx):
    if geom.geom_type != 'Point':
        raise EvidenceMissing('Architecture needs a registered anchor point')
    base = number(feature, 'base_elevation_m', ctx, -1000, 10000)
    angle = number(feature, 'rotation_degrees', ctx, -360, 360)
    elevation_source = ctx.sources[feature.parameters['base_elevation_m']['source']]
    if not ctx.vertical_datum or elevation_source.vertical_datum != ctx.vertical_datum:
        raise EvidenceMissing('Architectural base elevation datum mismatch')
    parts = feature.value('components', ctx.sources, ctx.allow_estimates)
    if not isinstance(parts, list) or not 1 <= len(parts) <= 1000:
        raise ValueError('Architecture requires 1–1000 components')
    ids = set()
    for part in parts:
        if not isinstance(part, dict) or 'geometry' not in part:
            raise ValueError('Architectural component object and geometry required')
        identifier = part.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('Unique architectural component identity required')
        ids.add(identifier)
        source = ctx.sources.get(part.get('geometry_source'))
        if source is None or source.registration_status != 'accepted':
            raise EvidenceMissing('Component profile registration not accepted')
        local = shape(part['geometry'])
        if local.geom_type not in ('Polygon', 'MultiPolygon') or local.is_empty or not local.is_valid or local.has_z:
            raise ValueError('Valid 2D architectural footprint required')
        if any(abs(v) > 100 for v in local.bounds):
            raise ValueError('Architectural relative footprint exceeds 100 m')
        # Each height and material keeps its own source/status, including estimates.
        nested = Feature(identifier, 'component', part['geometry'], part['geometry_source'], part.get('parameters', {}))
        bottom = number(nested, 'bottom_m', ctx, -20, 100)
        top = number(nested, 'top_m', ctx, -20, 100)
        if top <= bottom:
            raise ValueError('Component top must exceed bottom')
        material = nested.value('material', ctx.sources, ctx.allow_estimates)
        footprint = translate(rotate(local, angle, origin=(0, 0)), geom.x, geom.y)
        left, south, right, north = footprint.bounds
        if (right-left)*(north-south) > 30000:
            raise ValueError('Architectural footprint budget exceeded')
        # Positive overlap preserves thin columns; holes remain empty where a
        # whole voxel fits. Features smaller than a block necessarily alias.
        for x in range(math.floor(left), math.ceil(right)):
            for z in range(math.floor(south), math.ceil(north)):
                if footprint.intersection(box(x, z, x+1, z+1)).area <= 1e-9:
                    continue
                for y in range(math.floor(base+bottom), math.ceil(base+top)):
                    yield (x, y, z), material
