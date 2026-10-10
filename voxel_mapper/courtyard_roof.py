"""Robust estimated pitched ring roofs; DSM is a height guide, never a voxel stencil."""
import math
import numpy as np
from shapely.geometry import Point,Polygon
from .reconstruction.geometry import roof_cells


def pitched_shell(polygon, ground, surface):
    if not polygon.is_valid or len(polygon.interiors)!=1 or not 10<polygon.area<1600:
        raise ValueError('Bounded courtyard ring required')
    outer=Polygon(polygon.exterior).boundary
    inner=Polygon(polygon.interiors[0]).boundary
    samples=[]
    for x,z in roof_cells(polygon):
        p=Point(x+.5,z+.5);g,s=ground(p.x,p.y),surface(p.x,p.y)
        if g is None or s is None or not math.isfinite(g+s):raise ValueError('Complete finite elevation coverage required')
        d=min(p.distance(outer),p.distance(inner))
        samples.append((x,z,g,s,d))
    usable=[r for r in samples if .6<r[4] and 3<r[3]-r[2]<10]
    if len(usable)<20:raise ValueError('Insufficient roof-height observations')
    d=np.array([r[4] for r in usable]);s=np.array([r[3] for r in usable])
    # Bounded roof pitches and median loss prevent isolated high returns from
    # creating towers/spikes. A common eaves level joins all four wings.
    fits=[]
    for pitch in np.linspace(.4,1.2,81):
        eaves=float(np.median(s-pitch*d))
        error=float(np.median(np.abs(s-eaves-pitch*d)))
        fits.append((error,float(pitch),eaves))
    error,pitch,eaves=min(fits)
    if error>1.5 or not 2<eaves-np.median([r[2] for r in samples])<8:
        raise ValueError('Surface observations do not support bounded pitched roof')
    columns={(x,z) for x,z,*_ in samples};heights={}
    for x,z,g,s,d in samples:heights[x,z]=eaves+pitch*d
    rows=[]
    for x,z,g,s,d in samples:
        bottom=math.ceil(g)+1;roof=math.ceil(heights[x,z])-1
        if roof-bottom<1:raise ValueError('Pitched roof lacks wing clearance')
        edge=any((x+dx,z+dz) not in columns for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))
        # A vertical roof seam closes any quantized step. Both columns touch
        # even when their top blocks differ by one or more metres.
        neighbour_tops=[math.ceil(heights[q])-1 for q in ((x+1,z),(x-1,z),(x,z+1),(x,z-1)) if q in heights]
        skin=min([roof]+neighbour_tops)
        for y in range(bottom,roof+1):
            material='red_terracotta' if y>=skin else 'bricks' if edge else 'air'
            rows.append(dict(x=x,y=y,z=z,kind='structure',material=material,feature='mutiny/courtyard-wings',
                             source='mutiny-pitched-roof-estimate',material_origin='estimated_brick_and_tile_shell'))
    return rows,{'mapped_columns':len(samples),'roof_guide_samples':len(usable),'eaves_odn_m':eaves,
                 'pitch_rise_per_m':pitch,'median_guide_residual_m':error,
                 'roof_top_odn_range_m':[min(heights.values()),max(heights.values())],
                 'roof_rule':'Common eaves; bounded median-fit pitch; minimum distance to mapped outer/inner boundaries; joined quantized seams',
                 'shell_rule':'Full mapped ring; retained ground/floor; boundary brick walls; hollow wing interiors',
                 'status':'estimated_pitched_ring_not_registered_plan_geometry'}


def audit_native_roof(world, offset, rows, expected_columns):
    roof={(r['x'],r['y'],r['z']) for r in rows if r['material']=='red_terracotta'}
    columns={(x,z) for x,y,z in roof}
    if not roof or len(columns)!=expected_columns:raise ValueError('Pitched roof does not cover every mapped wing column')
    chunks={}
    for x,y,z in roof:
        key=x//16,(-z)//16
        if key not in chunks:chunks[key]=world.get_chunk(*key,'minecraft:overworld')
        c=chunks[key];block=c.block_palette[int(c.blocks[x%16,y+offset,(-z)%16])]
        if block.base_name!='stained_terracotta' or str(block.properties.get('color')).strip('"')!='red' or block.extra_blocks:
            raise ValueError('Native pitched roof material/clearance mismatch')
    remaining=set(roof);queue=[remaining.pop()]
    while queue:
        x,y,z=queue.pop()
        for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            p=x+dx,y+dy,z+dz
            if p in remaining:remaining.remove(p);queue.append(p)
    if remaining:raise ValueError('Pitched roof has disconnected native seams')
    return {'status':'passed','roof_columns':len(columns),'roof_blocks':len(roof),'face_connected_components':1,
            'roof_native_top_odn_range_m':[min(y for x,y,z in roof)+1,max(y for x,y,z in roof)+1]}
