"""Explicit estimated level pads supporting local buildings down to sampled terrain."""
import math
from shapely.geometry import Polygon, box


def level_pad(model, cells, anchor, base, ground):
    """Return local cells above existing terrain; never excavate or extend walls."""
    outline = Polygon([(p[0], p[1]) for p in model['outer_wall_base_outline']])
    if not outline.is_valid or outline.area <= 0:
        raise ValueError('Valid foundation footprint required')
    xmin,zmin,xmax,zmax = outline.bounds
    columns = {(x,z) for x in range(math.floor(xmin),math.ceil(xmax))
               for z in range(math.floor(zmin),math.ceil(zmax))
               if outline.intersection(box(x,z,x+1,z+1)).area>1e-8}
    # Exterior decorative posts and rasterized wall cells also need a bearing.
    columns.update((x,z) for x,y,z in cells if y==0)
    result = {}
    depths = []
    existing_contact = 0
    for x,z in sorted(columns):
        value = ground(x+round(anchor[0])+.5,z+round(anchor[1])+.5)
        if value is None or not math.isfinite(value):
            raise ValueError('Foundation lacks terrain coverage')
        local_ground = math.floor(value)-round(base)
        if local_ground >= 0:
            raise ValueError('Terrain is above foundation floor; grading review required')
        depth = -1-local_ground
        if depth>16:
            raise ValueError('Estimated foundation exceeds 16-block depth limit')
        depths.append(depth)
        existing_contact += depth==0
        for y in range(local_ground+1,0):
            if (x,y,z) in cells:
                raise ValueError('Foundation overlaps source building cells')
            result[x,y,z] = 'spruce_planks' if y==-1 else 'stone'
    return result, {'status':'estimated level floor and terrain-bearing foundation',
                    'footprint_columns':len(columns), 'added_cells':len(result),
                    'maximum_fill_depth_blocks':max(depths,default=0),
                    'existing_terrain_at_floor_columns':existing_contact,
                    'floor_local_y':-1, 'continuous_terrain_contact':True,
                    'terrain_excavation_cells':0, 'source_dimensions_modified':False,
                    'materials_source_verified':False}
