"""Explicit voxel boundary review; geometric closure is a display hypothesis."""
from collections import deque
import math
from shapely.geometry import LineString,box,Polygon,Point


def boundary_columns(outline, scale):
    columns=set()
    for a,b in zip(outline,outline[1:]+outline[:1]):
        line=LineString([(a[0]*scale,a[1]*scale),(b[0]*scale,b[1]*scale)])
        x0,z0,x1,z1=line.bounds
        for x in range(math.floor(x0),math.floor(x1)+1):
            for z in range(math.floor(z0),math.floor(z1)+1):
                if line.intersection(box(x,z,x+1,z+1)).length>1e-8:columns.add((x,z))
    return columns


def opening_columns(openings, scale):
    masks={}
    for opening in openings:
        a,b=opening['endpoints'];axis=0 if abs(b[0]-a[0])>=abs(b[1]-a[1]) else 1
        lo,hi=sorted([a[axis]*scale,b[axis]*scale]);other=1-axis
        for i in range(math.floor(lo),math.ceil(hi)):
            if not lo<=i+.5<=hi:continue
            t=((i+.5)/scale-a[axis])/(b[axis]-a[axis])
            normal=math.floor((a[other]+t*(b[other]-a[other]))*scale)
            column=(i,normal) if axis==0 else (normal,i)
            masks[column]=max(masks.get(column,0),math.floor(opening['height_metres']*scale))
    return masks


def close_shell(model,wall,roof,scale):
    boundary=boundary_columns(model['outer_wall_base_outline'],scale)
    doors=opening_columns(model['opening_base_segments'],scale)
    # Close vertical stair risers between adjacent roof samples. This thickens
    # the voxel display locally, not the measured source roof.
    bottoms={}
    for x,y,z in roof:bottoms[x,z]=min(bottoms.get((x,z),y),y)
    risers=set()
    for (x,z),height in sorted(bottoms.items()):
        for q in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)):
            if q in bottoms and height>bottoms[q]:
                if height-bottoms[q]>2:raise ValueError('Unbounded roof step')
                risers.update((x,y,z) for y in range(bottoms[q],height))
    new_risers=risers-roof
    roof=roof|risers
    for x,y,z in risers:bottoms[x,z]=min(bottoms[x,z],y)
    shell=set(wall);added=set();removed=set()
    for x,z in sorted(boundary):
        if (x,z) not in bottoms:raise ValueError('Boundary lacks overhead roof')
        head=doors.get((x,z),0)
        for y in range(head,bottoms[x,z]):
            p=(x,y,z)
            if p not in shell:added.add(p)
            shell.add(p)
        for y in range(head):
            p=(x,y,z)
            if p in shell:removed.add(p)
            shell.discard(p)
    audit=leak_audit(shell|roof,boundary,doors,model['outer_wall_base_outline'],scale)
    if audit['interior_reached_from_exterior']:raise ValueError('Review shell leaks with doors temporarily sealed')
    return shell,roof,{'status':'estimated voxel closure, not measured construction',
        'wall_boundary_columns':len(boundary),'opening_columns':len(doors),
        'added_wall_cells':len(added),'removed_opening_cells':len(removed),
        'added_roof_riser_cells':len(new_risers),
        'door_air_verified':all((x,y,z) not in shell|roof for (x,z),head in doors.items() for y in range(head)),
        'leak_audit':audit}


def leak_audit(cells,boundary,doors,outline=None,scale=1):
    """Outside six-neighbour air flood, with door apertures sealed for this test."""
    blocked=set(cells)
    blocked.update((x,y,z) for (x,z),head in doors.items() for y in range(head))
    x0=min(p[0] for p in cells)-2;x1=max(p[0] for p in cells)+2
    z0=min(p[2] for p in cells)-2;z1=max(p[2] for p in cells)+2
    y1=max(p[1] for p in cells)+2
    volume=(x1-x0+1)*(z1-z0+1)*(y1+1)
    if volume>500000:raise ValueError('Shell leak audit budget exceeded')
    start=(x0,0,z0);queue=deque([start]);seen={start}
    while queue:
        x,y,z=queue.popleft()
        for p in ((x-1,y,z),(x+1,y,z),(x,y-1,z),(x,y+1,z),(x,y,z-1),(x,y,z+1)):
            if x0<=p[0]<=x1 and 0<=p[1]<=y1 and z0<=p[2]<=z1 and p not in blocked and p not in seen:
                seen.add(p);queue.append(p)
    targets={(0,1,0)}
    if outline is not None:
        footprint=Polygon([(p[0]*scale,p[1]*scale) for p in outline]);tops={}
        for x,y,z in cells:tops[x,z]=min(tops.get((x,z),y),y)
        targets={(x,y,z) for (x,z),top in tops.items() if (x,z) not in boundary and footprint.contains(Point(x+.5,z+.5))
                 for y in range(1,top) if (x,y,z) not in blocked}
    if not targets or (0,1,0) in blocked:raise ValueError('Shell audit lacks interior air')
    return {'method':'six-neighbour outside-air flood; floor sealed at study zero; door apertures temporarily sealed',
        'interior_probe_local_xyz':[0,1,0],'interior_reached_from_exterior':bool(targets&seen),
        'interior_air_cells_checked':len(targets),'reachable_interior_air_cells':len(targets&seen),
        'probe_is_air':(0,1,0) not in blocked,'visited_air_cells':len(seen),'bounded_volume_cells':volume,
        'physical_watertightness_verified':False}
