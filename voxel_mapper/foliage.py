"""Deterministic, bounded tree silhouettes; species and dimensions come from callers."""
import hashlib
import math
import random
from .reconstruction.geometry import segment_cells


def stable_seed(identity):
    return int.from_bytes(hashlib.sha256(str(identity).encode()).digest()[:8],'big')


def crown_radius_at_height(height, radius, level):
    """Keep the lower crown broad, rounding its upper third into a leafy tip."""
    t=max(0,min(1,(level/height-.65)/.35))
    return max(1,radius*math.sqrt(max(0,1-t*t)))


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
    member((x,ground+1,z),(x,ground+height-1,z),False)
    start=max(2,round(height*(.52 if profile=='pine' else .22 if profile in ('conifer','monkey_puzzle') else .30)))
    count=branch_count if branch_count is not None else max(5,min(40,round(height*.45+radius*1.5)))
    phase=rng.random()*math.tau
    for i in range(count):
        t=(i+.5)/count
        level=min(height-2,max(start,round(start+(height-1-start)*t+rng.uniform(-.65,.65))))
        angle=phase+i*2.399963229728653+rng.uniform(-.32,.32)
        reach=max(0,radius-1)*rng.uniform(.62,1)
        if profile in ('conifer','monkey_puzzle'):reach*=max(.22,(1-level/height)**.55)
        if profile=='columnar':reach*=.55
        def point(length,azimuth,y):
            y=max(2,min(height-1,round(y)))
            length=min(length,max(0,crown_radius_at_height(height,radius,y)-1))
            return (x+round(math.cos(azimuth)*length),ground+y,z+round(math.sin(azimuth)*length))
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
    for y in range(max(2,min(start,height-2)),height):foliar.add((x,ground+y,z))
    if height>=20 and radius>=5:
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            member((x,ground+1,z),(x+dx,ground+1,z+dz),False)
            member((x,ground+3,z),(x+dx,ground+1,z+dz),False)
    return cells,foliar


def tree_cells(x,ground,z,height,radius,profile='broadleaf',seed=0,wood='oak',leaves='oak',branch_count=None,leaf_density=None,leaf_palette=None):
    """Scatter mixed leaves around generated branches, including leafy caps.

    Every leaf touches a fence. Dense side placement plus top/bottom caps hide
    more branch faces; seeded sampling preserves irregular gaps and bounds.
    """
    if leaves not in ('oak','spruce','birch','dark_oak','azalea'):raise ValueError('Unsupported foliage palette')
    density=leaf_density if leaf_density is not None else (.88 if profile=='airy' else .98 if profile in ('conifer','columnar') else .95)
    if isinstance(density,bool) or not isinstance(density,(float,int)) or not math.isfinite(density) or not 0<=density<=1:
        raise ValueError('Leaf density must be a finite probability')
    palette=leaf_palette if leaf_palette is not None else (('spruce','oak') if leaves=='spruce' else ('oak','birch'))
    if not isinstance(palette,(tuple,list)) or not 1<=len(palette)<=5 or any(m not in ('oak','spruce','birch','dark_oak','azalea') for m in palette):
        raise ValueError('Invalid leaf palette')
    cells,foliar=tree_structure(x,ground,z,height,radius,profile,seed,wood,branch_count)
    x,ground,z=map(math.floor,(x,ground,z));height=math.floor(height)
    sites={}
    for xx,yy,zz in sorted(foliar):
        for dx,dy,dz in ((-1,0,0),(1,0,0),(0,0,-1),(0,0,1),(0,1,0),(0,-1,0)):
            k=(xx+dx,yy+dy,zz+dz)
            if k in cells or not ground+2<=k[1]<=ground+height or (k[0]-x)**2+(k[2]-z)**2>crown_radius_at_height(height,radius,k[1]-ground)**2:continue
            sites[k]=max(sites.get(k,0),.9 if dy else 1)
    for k in sorted(sites):
        # Per-site decisions make increasing density add leaves consistently;
        # neither the skeleton nor existing leaf colours change with density.
        h=stable_seed((seed,*k));chance=(h&0xffffffff)/2**32;mix=(h>>32)/2**32
        if chance<density*sites[k]:
            # Mixed blocks are colour proxies, not a botanical species claim.
            material=palette[0] if len(palette)==1 or mix<.65 else palette[1+min(len(palette)-2,int((mix-.65)/.35*(len(palette)-1)))]
            cells[k]=material+'_leaves'
    # Finish the leader with a leaf rather than an exposed, flat fence end.
    if density>0:cells[x,ground+height,z]=palette[0]+'_leaves'
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
