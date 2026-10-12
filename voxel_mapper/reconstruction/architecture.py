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
    cells = {}
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
        rule = nested.value('raster_rule', ctx.sources, ctx.allow_estimates) if 'raster_rule' in nested.parameters else 'overlap'
        priority = nested.value('voxel_priority', ctx.sources, ctx.allow_estimates) if 'voxel_priority' in nested.parameters else 0
        if rule not in ('overlap', 'centroid') or isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100:
            raise ValueError('Invalid component raster rule or voxel priority')
        if rule == 'centroid' and (local.geom_type != 'Polygon' or local.area > 1 or local.interiors):
            raise ValueError('Centroid raster rule requires a small solid member')
        footprint = translate(rotate(local, angle, origin=(0, 0)), geom.x, geom.y)
        left, south, right, north = footprint.bounds
        if (right-left)*(north-south) > 30000:
            raise ValueError('Architectural footprint budget exceeded')
        # Positive overlap preserves thin columns; holes remain empty where a
        # whole voxel fits. Features smaller than a block necessarily alias.
        xs = [math.floor(footprint.centroid.x)] if rule == 'centroid' else range(math.floor(left), math.ceil(right))
        zs = [math.floor(footprint.centroid.y)] if rule == 'centroid' else range(math.floor(south), math.ceil(north))
        for x in xs:
            for z in zs:
                if footprint.intersection(box(x, z, x+1, z+1)).area <= 1e-9:
                    continue
                for y in range(math.floor(base+bottom), math.ceil(base+top)):
                    key = x, y, z
                    previous = cells.get(key)
                    if previous is None or priority > previous[0]:
                        cells[key] = priority, {material}
                    elif priority == previous[0]:
                        previous[1].add(material)
                    if len(cells) > ctx.max_feature_voxels:
                        raise EvidenceMissing('Feature budget exceeded')
    if any(len(materials) != 1 for _, materials in cells.values()):
        raise EvidenceMissing('Conflicting feature member material at equal priority')
    for key, (_, materials) in cells.items():
        yield key, next(iter(materials))
