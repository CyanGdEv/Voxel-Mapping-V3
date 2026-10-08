"""Deterministic, bounded tree silhouettes; species and dimensions come from callers."""
import hashlib
import math
import random
from .reconstruction.geometry import segment_cells


def stable_seed(identity):
    return int.from_bytes(hashlib.sha256(str(identity).encode()).digest()[:8],'big')


def tree_structure(x,ground,z,height,radius,profile='broadleaf',seed=0,wood='oak',branch_count=None):
    """Build a grounded fence skeleton first; return foliage-bearing members.

    Branch count, attachment levels, azimuths, elbows and terminal forks are
    procedural. Dimensions are metres; species/branch forms remain proxies.
    """
    if (not all(math.isfinite(v) for v in (x,ground,z,height,radius))
            or not 3<=height<=40 or not 1<=radius<=10):
        raise ValueError('Tree dimensions outside bounded metre range')
    if profile not in ('broadleaf','airy','conifer','pine','columnar','monkey_puzzle','weeping'):
        raise ValueError('Unknown tree silhouette')
    if wood not in ('oak','spruce','birch','dark_oak'):raise ValueError('Unsupported trunk palette')
    if branch_count is not None and (isinstance(branch_count,bool) or not isinstance(branch_count,int) or not 3<=branch_count<=80):
        raise ValueError('Branch count must be an integer from 3 to 80')
    x,ground,z=map(math.floor,(x,ground,z));height=math.floor(height)
    rng=random.Random(seed);cells={};foliar=set()
    def member(a,b,leaf_bearing=True):
        for k in segment_cells(a,b):
            cells[k]=wood+'_fence'
            if leaf_bearing:foliar.add(k)
    # A single connected main stem, bare below the first crown branches.
    member((x,ground+1,z),(x,ground+height,z),False)
    start=max(2,round(height*(.52 if profile=='pine' else .22 if profile in ('conifer','monkey_puzzle') else .30)))
    count=branch_count if branch_count is not None else max(5,min(40,round(height*.45+radius*1.5)))
    phase=rng.random()*math.tau
    for i in range(count):
        t=(i+.5)/count
        level=min(height-1,max(start,round(start+(height-1-start)*t+rng.uniform(-.65,.65))))
        angle=phase+i*2.399963229728653+rng.uniform(-.32,.32)
        reach=max(0,radius-1)*rng.uniform(.62,1)
        if profile in ('conifer','monkey_puzzle'):reach*=max(.22,(1-level/height)**.55)
        if profile=='columnar':reach*=.55
        def point(length,azimuth,y):
            return (x+round(math.cos(azimuth)*length),ground+max(2,min(height,round(y))),z+round(math.sin(azimuth)*length))
        origin=(x,ground+level,z)
        elbow=point(reach*.48,angle+rng.uniform(-.25,.25),level+rng.uniform(-1,1))
        tip=point(reach,angle,level+(rng.uniform(-2,0) if profile=='weeping' else rng.uniform(0,2.5)))
        member(origin,elbow);member(elbow,tip)
        # Unequal forks give each branch an open, irregular terminal structure.
        for side in (-1,1):
            fork=point(reach*rng.uniform(.7,1),angle+side*rng.uniform(.28,.75),level+rng.uniform(-1,2.5))
            member(elbow,fork)
        # Leaves can also cling to the upper central stem, keeping a sparse tip.
        foliar.add(origin)
    for y in range(max(start,height-2),height+1):foliar.add((x,ground+y,z))
    if height>=20 and radius>=5:
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            member((x,ground+1,z),(x+dx,ground+1,z+dz),False)
            member((x,ground+3,z),(x+dx,ground+1,z+dz),False)
    return cells,foliar


def tree_cells(x,ground,z,height,radius,profile='broadleaf',seed=0,wood='oak',leaves='oak',branch_count=None,leaf_density=None,leaf_palette=None):
    """Scatter mixed leaves on four horizontal sides of generated branches.

    There is no canopy volume fill. Every leaf touches a fence horizontally;
    seeded Bernoulli placement leaves open gaps and preserves reproducibility.
    """
    if leaves not in ('oak','spruce','birch','dark_oak','azalea'):raise ValueError('Unsupported foliage palette')
    density=leaf_density if leaf_density is not None else (.42 if profile=='airy' else .62 if profile in ('conifer','columnar') else .55)
    if isinstance(density,bool) or not isinstance(density,(float,int)) or not math.isfinite(density) or not 0<=density<=1:
        raise ValueError('Leaf density must be a finite probability')
    palette=leaf_palette if leaf_palette is not None else (('spruce','oak') if leaves=='spruce' else ('oak','birch'))
    if not isinstance(palette,(tuple,list)) or not 1<=len(palette)<=5 or any(m not in ('oak','spruce','birch','dark_oak','azalea') for m in palette):
        raise ValueError('Invalid leaf palette')
    cells,foliar=tree_structure(x,ground,z,height,radius,profile,seed,wood,branch_count)
    x,ground,z=map(math.floor,(x,ground,z));height=math.floor(height)
    rng=random.Random(seed^0x9e3779b97f4a7c15);sites=set()
    for xx,yy,zz in sorted(foliar):
        for dx,dz in ((-1,0),(1,0),(0,-1),(0,1)):
            k=(xx+dx,yy,zz+dz)
            if k in cells or (k[0]-x)**2+(k[2]-z)**2>radius**2:continue
            sites.add(k)
    for k in sorted(sites):
        if rng.random()<density:
            # Mixed blocks are colour proxies, not a botanical species claim.
            material=palette[0] if len(palette)==1 or rng.random()<.65 else rng.choice(palette[1:])
            cells[k]=material+'_leaves'
    return cells


def shrub_cells(x,ground,z,radius=2,height=2,seed=0,flowering=False):
    """Irregular low evergreen mass, with occasional flowering tips."""
    if not 1<=radius<=6 or not 1<=height<=5:raise ValueError('Shrub bounds exceeded')
    cells={}
    for dx in range(-math.ceil(radius),math.ceil(radius)+1):
        for dz in range(-math.ceil(radius),math.ceil(radius)+1):
            rr=(dx/radius)**2+(dz/radius)**2
            if rr>1:continue
            top=max(1,round(height*math.sqrt(1-rr)))
            for dy in range(1,top+1):
                flower=flowering and dy==top and ((dx*97+dz*31+seed)%13==0)
                cells[math.floor(x)+dx,math.floor(ground)+dy,math.floor(z)+dz]='flowering_azalea_leaves' if flower else 'azalea_leaves'
    return cells
