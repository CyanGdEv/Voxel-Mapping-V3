"""Park-independent half-block walking profiles and colour-aware barriers.

Heights are walking-surface elevations, not block origins. Coordinates use
local east/north metres; stair facing is converted to Minecraft north (-Z).
Source extraction and world collision checks deliberately remain separate.
"""
import math


def barrier_material(colour=None):
    return 'green_stained_glass_pane' if colour and ('green' in colour.lower() or colour.upper()=='RAL6008') else 'iron_bars'


def uphill_facing(dx,dz,rise):
    if rise<0:dx,dz=-dx,-dz
    return ('east' if dx>=0 else 'west') if abs(dx)>abs(dz) else ('north' if dz>=0 else 'south')


def walking_block(height,grade,dx,dz,material='stone',stairs=False):
    """Quantize a finite surface to half metres; stairs above 1:2 gradient.

    Bottom slabs have a real half-block top; top slabs have an integer top.
    A stair's taller back faces uphill. Flat integer surfaces use full blocks.
    """
    if not all(math.isfinite(v) for v in (height,grade,dx,dz)):raise ValueError('Finite walking profile required')
    if material not in ('stone','stone_brick','sandstone','brick'):raise ValueError('Unsupported walking material')
    top=round(height*2)/2
    if (stairs or abs(grade)>=.5) and abs(grade)>.02:
        return math.ceil(top)-1,f'{material}_stairs_{uphill_facing(dx,dz,grade)}'
    if top!=math.floor(top):return math.floor(top),f'{material}_slab'
    if abs(grade)>.02:return int(top)-1,f'{material}_slab_top'
    return int(top)-1,{'stone_brick':'stone_bricks','brick':'bricks'}.get(material,material)


def barrier_column(x,z,walking_top,colour=None,height_m=1.1):
    """Grounded voxel railing; 1.1 m rounds to one thin railing block.

    Footing fills any half-block gap. Adjacent heights need overlapping cells;
    callers must rasterize routes with face-connected horizontal cells.
    """
    if not math.isfinite(height_m) or not 0<height_m<=3:raise ValueError('Barrier height outside budget')
    base=math.ceil(walking_top);material=barrier_material(colour)
    return {(x,y,z):material for y in range(base,base+max(1,round(height_m)))}


def path_transitions(surfaces):
    """Smooth actual path columns, never generate a parallel footprint.

    Each cell declares its native walking top, material and route tangent.
    Slabs are added on the lower paved cell at isolated one-block rises.
    Stair runs replace the paving block and face an actual forward neighbour;
    their low/high half-treads connect consecutive whole-block elevations.
    A top landing receives a terminal stair when approached by a stair run.
    """
    neighbours=((1,0),(-1,0),(0,1),(0,-1));up={};down={};steep=set()
    def aligned(a,b,dx,dz):
        tx,tz=a.get('tangent',(dx,dz));norm=math.hypot(tx,tz)
        return abs((dx*tx+dz*tz)/norm)>.35 if norm else True
    for k,a in surfaces.items():
        options=[];lower=[]
        for dx,dz in neighbours:
            q=(k[0]+dx,k[1]+dz);b=surfaces.get(q)
            if b is None or not aligned(a,b,dx,dz):continue
            rise=b['top']-a['top']
            if .5<rise<=1.01:options.append((rise,q))
            if -1.01<=rise<-.5:lower.append(q)
        if options:up[k]=max(options,key=lambda v:(v[0],v[1]))[1]
        if lower:down[k]=lower
    for k,q in up.items():
        if k in down:steep.add(k)
    result={}
    for k,q in up.items():
        a=surfaces[k];h=a['top'];family=a['family'];dx,dz=q[0]-k[0],q[1]-k[1]
        if h!=int(h) or a.get('partial'):continue # Do not stack transitions on existing partial blocks.
        if k in steep:result[k]={'y':int(h)-1,'material':f'{family}_stairs_{uphill_facing(dx,dz,1)}','kind':'stairs','higher_neighbour':q}
        else:result[k]={'y':int(h),'material':f'{family}_slab','kind':'slab','higher_neighbour':q}
    for k in steep:
        q=up[k]
        if q in up or q in result:continue
        a=surfaces[q];h=a['top']
        if h!=int(h) or a.get('partial'):continue
        dx,dz=q[0]-k[0],q[1]-k[1]
        result[q]={'y':int(h)-1,'material':f"{a['family']}_stairs_{uphill_facing(dx,dz,1)}",'kind':'landing_stair','lower_neighbour':k}
    return result
