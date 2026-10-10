"""Bounded bridge deck, arch and approach geometry in a metric east/north frame."""
import math
from shapely.geometry import Point,LineString
from .geometry import roof_cells,line_cells
from .garden_surfaces import walking_block


def bridge_cells(line,width,top,ground,style='footbridge',approach_length=6,water_top=None):
    if line.geom_type!='LineString' or len(line.coords)!=2 or not 1<=line.length<=100:
        raise ValueError('Short straight reviewed bridge axis required')
    if not all(math.isfinite(v) for v in (width,top,approach_length)) or not 1<=width<=12 or not 1<=approach_length<=30:
        raise ValueError('Bounded finite bridge dimensions required')
    if style not in ('footbridge','cast_iron_three_span','white_ashlar_arch'):raise ValueError('Unknown bridge style')
    a,b=line.coords;dx=(b[0]-a[0])/line.length;dz=(b[1]-a[1])/line.length;cells={};walk={};clear=set()
    def put(x,y,z,m):cells[x,y,z]=m
    deck_y=math.ceil(top)-1
    for x,z in set(roof_cells(line.buffer(width/2,cap_style=2)))|set(line_cells(line)):
        put(x,deck_y,z,'gray_concrete' if style=='cast_iron_three_span' else 'stone')
        walk[x,z]=deck_y+1
        for y in range(deck_y+1,deck_y+3):clear.add((x,y,z))
        floor=ground(x,z)
        if floor is None:raise ValueError('Bridge needs native ground at all columns')
        s=line.project(Point(x+.5,z+.5));t=s/line.length
        if style=='white_ashlar_arch':
            # Single flattened arch proxy; opening remains above the lower path.
            crown=top-1.2-3.0*(abs(2*t-1)**2)
            for y in range(floor+1,deck_y):
                if y>=crown:put(x,y,z,'white_concrete')
                else:clear.add((x,y,z))
        elif (s<1.2 or line.length-s<1.2) and (water_top is None or water_top(x,z) is None):
            for y in range(floor+1,deck_y):put(x,y,z,'sandstone')
    # Railings sit outside the rasterized walking columns, with explicit footing.
    for side in (-1,1):
        offset=width/2+.65
        rail=LineString([(a[0]-dz*side*offset,a[1]+dx*side*offset),(b[0]-dz*side*offset,b[1]+dx*side*offset)])
        for (x,z),s in line_cells(rail).items():
            if (x,z) in walk:continue
            put(x,deck_y,z,'white_concrete' if style=='white_ashlar_arch' else 'stone')
            put(x,deck_y+1,z,'sandstone_wall' if style=='white_ashlar_arch' else 'iron_bars')
            if style=='cast_iron_three_span':
                # Three segmented side ribs; sub-metre ironwork aliases at 1:1.
                t=(s/line.length*3)%1;rib_y=deck_y-1 if abs(2*t-1)>.6 else deck_y
                put(x,rib_y,z,'iron_bars')
    for end,p,sign in [(0,a,-1),(1,b,1)]:
        q=(p[0]+dx*sign*approach_length,p[1]+dz*sign*approach_length)
        outer=ground(math.floor(q[0]),math.floor(q[1]))
        if outer is None:raise ValueError('Missing approach terrain')
        outer_top=outer+1;route=LineString([p,q]);grade=(outer_top-top)/approach_length
        for x,z in set(roof_cells(route.buffer(width/2,cap_style=2)))|set(line_cells(route)):
            if (x,z) in walk:continue
            s=route.project(Point(x+.5,z+.5));h=top+(outer_top-top)*s/approach_length
            y,m=walking_block(h,grade,dx*sign,dz*sign)
            floor=ground(x,z)
            if floor is None or y-floor>8 or floor-y>2:raise ValueError('Approach exceeds terrain adjustment budget')
            wet=water_top(x,z) if water_top else None
            if wet is not None and y<=wet:raise ValueError('Bridge approach below water surface')
            if wet is None:
                for yy in range(min(floor,y),y):put(x,yy,z,'stone')
            put(x,y,z,m);walk[x,z]=y+.5 if m=='stone_slab' else y+1
            for yy in range(y+1,max(y+3,floor+2)):clear.add((x,yy,z))
    # Deck and raised foundations override clearance envelopes.
    clear.difference_update(cells)
    return cells,clear,walk
