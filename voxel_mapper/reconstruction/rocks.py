"""Deterministic faceted rock proxies inside reviewed metre footprints."""
import math
from shapely.geometry import Point
from .geometry import roof_cells
from .garden_surfaces import uphill_facing

ROCK_TYPES = {
    'jagged': ('stone', 'cobblestone', 'cobblestone'),
    'layered_sandstone': ('sandstone', 'sandstone', 'sandstone'),
    'weathered_granite': ('granite', 'granite', 'granite'),
}


def rock_cells(footprint, ground, rock_type='jagged', height_m=2):
    """Full cores, half ledges, inward stairs and narrow grounded wall tips.

    Type is an explicit visual recipe unless a source identifies lithology.
    Height is a bounded reconstruction estimate; no dimensions are inferred
    from a plan's generic rockwork label.
    """
    if (footprint.geom_type not in ('Polygon', 'MultiPolygon') or not footprint.is_valid
            or footprint.is_empty or not .15 <= footprint.area <= 500):
        raise ValueError('Bounded valid rock footprint required')
    if rock_type not in ROCK_TYPES or not math.isfinite(height_m) or not 1 <= height_m <= 8:
        raise ValueError('Supported rock type and bounded height required')
    columns = roof_cells(footprint)
    if not columns:
        return {}, {'status': 'sub_voxel_footprint', 'columns': 0}
    full, partial, wall = ROCK_TYPES[rock_type]
    depths = {(x,z): footprint.boundary.distance(Point(x+.5,z+.5)) for x,z in columns}
    deepest = max(depths.values()) or 1
    heights = {}
    for k, depth in depths.items():
        if rock_type == 'layered_sandstone':
            h = max(1, math.ceil(height_m * (.5 + .5 * depth / deepest)))
        else:
            h = max(1, math.ceil(height_m * .6), math.ceil(height_m * (.35 + .65 * depth / deepest)))
        heights[k] = h
    cells = {}
    forms = {}
    for (x,z), h in sorted(heights.items()):
        floor = ground(x,z)
        if floor is None or not math.isfinite(floor):
            raise ValueError('Complete finite rock ground required')
        base = math.floor(floor) + 1
        grain = ((x * 73856093) ^ (z * 19349663)) & 0xffffffff
        for y in range(base, base + h - 1):
            cells[x,y,z] = full
        neighbours = [(heights.get((x+dx,z+dz),0), dx, dz)
                      for dx,dz in ((1,0),(-1,0),(0,1),(0,-1))]
        higher, dx, dz = max(neighbours)
        edge = any(v == 0 for v,_,_ in neighbours)
        if higher > h or (edge and grain % 3 == 0):
            if higher <= h:
                cx,cz = footprint.centroid.coords[0]
                dx,dz = cx-(x+.5),cz-(z+.5)
            material = partial + '_stairs_' + uphill_facing(dx,dz,1)
            form = 'stairs'
        elif edge or rock_type == 'layered_sandstone':
            material = partial + ('_slab_top' if grain % 2 else '_slab')
            form = 'slab'
        else:
            material, form = full, 'full'
        cells[x,base+h-1,z] = material
        forms[form] = forms.get(form,0) + 1
        # Keep a full support beneath a narrow tip; never perch it on a slab.
        if rock_type != 'layered_sandstone' and h >= 2 and grain % 4 == 0:
            cells[x,base+h-1,z] = wall + '_wall'
            forms[form] -= 1
            forms['wall'] = forms.get('wall',0) + 1
    forms = {}
    for material in cells.values():
        form = ('stairs' if '_stairs_' in material else 'slab' if '_slab' in material
                else 'wall' if material.endswith('_wall') else 'full')
        forms[form] = forms.get(form, 0) + 1
    return cells, {'status': 'estimated_faceted_rock', 'columns': len(columns),
                   'rock_type': rock_type, 'height_estimate_m': height_m,
                   'forms': {k:v for k,v in forms.items() if v},
                   'lithology_verified': False,
                   'shape_status': 'Full cores, slab ledges, stair facets and grounded narrow tips are visual proxies'}
