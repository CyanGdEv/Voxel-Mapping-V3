"""User-requested decorative timber posts and panels; dimensions are illustrative."""
from collections import Counter
import math


def decorate(model,cells):
    details={};records=[]
    outline=model['outer_wall_base_outline']
    for edge,(a,b) in enumerate(zip(outline,outline[1:]+outline[:1])):
        axis=0 if abs(b[0]-a[0])>=abs(b[1]-a[1]) else 1
        other=1-axis;lo,hi=sorted([a[axis],b[axis]])
        outward=-1 if (a[other]+b[other])/2<0 else 1
        direction=('west' if outward<0 else 'east') if other==0 else ('north' if outward<0 else 'south')
        # An opened trapdoor with outward-facing orientation lies against the
        # inward block face of its exterior cell.
        for i in range(math.ceil(lo),math.floor(hi)):
            t=(i+.5-a[axis])/(b[axis]-a[axis])
            normal=math.floor(a[other]+t*(b[other]-a[other]))
            x,z=(i,normal) if axis==0 else (normal,i)
            if cells.get((x,0,z))!='spruce_planks' or cells.get((x,1,z))!='spruce_planks':continue
            dx,dz=(outward,0) if other==0 else (0,outward)
            post=(i-math.ceil(lo))%3==0
            for y in (range(3) if post else (1,)):
                wall=(x,y,z);p=(x+dx,y,z+dz)
                if cells.get(wall)!='spruce_planks' or p in cells or p in details:continue
                material='dark_oak_fence' if post else f'spruce_trapdoor_{direction}'
                details[p]=material
                records.append({'local_xyz':list(p),'wall_anchor_local_xyz':list(wall),'edge':edge,'material':material})
    result=dict(cells);result.update(details)
    return result,{'status':'user-requested illustrative wall detail','source_geometry_modified':False,
        'post_spacing_blocks':3,'material_counts':dict(sorted(Counter(details.values()).items())),
        'placements':records,'door_policy':'only anchored to existing solid wall cells at both foot and head; no doorway facade columns decorated',
        'dimensions_source_verified':False}
