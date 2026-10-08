"""Deterministic, bounded tree silhouettes; species and dimensions come from callers."""
import hashlib
import math
import random
from .reconstruction.geometry import segment_cells


def stable_seed(identity):
    return int.from_bytes(hashlib.sha256(str(identity).encode()).digest()[:8],'big')


def value_noise(x,y,z,seed,scale=2.7):
    """Smooth seeded 3-D noise; neighbouring leaf cells form coherent patches."""
    coords=(x/scale,y/scale,z/scale);base=tuple(math.floor(v) for v in coords)
    f=[v-b for v,b in zip(coords,base)];f=[v*v*(3-2*v) for v in f]
    value=0
    for dx in (0,1):
        for dy in (0,1):
            for dz in (0,1):
                h=((base[0]+dx)*73856093)^((base[1]+dy)*19349663)^((base[2]+dz)*83492791)^seed
                h=(h^(h>>13))*1274126177;h=(h^(h>>16))&0xffffffff
                weight=(f[0] if dx else 1-f[0])*(f[1] if dy else 1-f[1])*(f[2] if dz else 1-f[2])
                value+=weight*(h/0xffffffff*2-1)
    return value


def tree_cells(x,ground,z,height,radius,profile='broadleaf',seed=0,wood='oak',leaves='oak'):
    """Connected fence skeleton with noisy lobed crowns or conifer whorls.

    Dimensions are metres at the current one-metre voxel scale. These are visual
    proxies, not botanical meshes or independently measured branch structures.
    """
    if (not all(math.isfinite(v) for v in (x,ground,z,height,radius))
            or not 3<=height<=40 or not 1<=radius<=10):
        raise ValueError('Tree dimensions outside bounded metre range')
    if profile not in ('broadleaf','airy','conifer','pine','columnar','monkey_puzzle','weeping'):
        raise ValueError('Unknown tree silhouette')
    if wood not in ('oak','spruce','birch','dark_oak') or leaves not in ('oak','spruce','birch','dark_oak','azalea'):
        raise ValueError('Unsupported foliage palette')
    x,ground,z=map(math.floor,(x,ground,z));height=math.floor(height);rng=random.Random(seed);cells={}
    def branch(a,b):
        for k in segment_cells(a,b):cells[k]=wood+'_fence'
    def crown(cx,cy,cz,rx,ry,rz):
        for xx in range(math.floor(cx-rx),math.ceil(cx+rx)+1):
            for yy in range(max(ground+2,math.floor(cy-ry)),min(ground+height,math.ceil(cy+ry))+1):
                for zz in range(math.floor(cz-rz),math.ceil(cz+rz)+1):
                    d=((xx-cx)/rx)**2+((yy-cy)/ry)**2+((zz-cz)/rz)**2
                    if (xx-x)**2+(zz-z)**2>radius**2:continue
                    if d>1.1:continue
                    noise=.72*value_noise(xx,yy,zz,seed)+.28*value_noise(xx,yy,zz,seed^0x9e3779b9,1.15)
                    if d>.90+.25*noise:continue
                    cells.setdefault((xx,yy,zz),leaves+'_leaves')
    trunk_top=ground+height-1 if profile in ('conifer','columnar','monkey_puzzle') else ground+max(3,round(height*.65))
    lean=(rng.choice((-1,0,1)),rng.choice((-1,0,1))) if height>10 else (0,0)
    joint=(x+lean[0],trunk_top,z+lean[1]);branch((x,ground+1,z),joint)
    branch((x,ground+1,z),(x,trunk_top,z))
    if profile in ('conifer','columnar','monkey_puzzle'):
        for dy in range(max(2,round(height*.18)),height,2):
            r=radius*(1-dy/height)**.65
            if profile=='columnar':r=radius*(.8 if dy<height*.7 else max(.2,1-(dy/height-.7)/.35))
            if profile=='monkey_puzzle':
                for i in range(5):
                    angle=i*math.tau/5+(dy%4)*.35
                    end=(x+math.cos(angle)*r,ground+dy+.8,z+math.sin(angle)*r)
                    branch((x,ground+dy,z),end);crown(*end,1.1,.8,1.1)
            else:
                crown(x+lean[0]*dy/height,ground+dy,z+lean[1]*dy/height,max(.8,r),1.7,max(.8,r*.9))
                if dy%4==0 and r>1.5:
                    for i in range(4):
                        angle=i*math.pi/2+dy*.25
                        branch((x,ground+dy,z),(x+math.cos(angle)*r*.65,ground+dy,z+math.sin(angle)*r*.65))
        crown(joint[0],ground+height-1,joint[2],.9,1,.9)
    else:
        centre_y=ground+height*(.82 if profile=='pine' else .72)
        vertical=height*(.17 if profile=='pine' else .25)
        crown(joint[0],centre_y,joint[2],radius*.7,vertical,radius*.7)
        lobes=5 if profile=='airy' else 7
        for i in range(lobes):
            angle=i*math.tau/lobes+rng.uniform(-.25,.25);reach=radius*rng.uniform(.4,.7)
            end=(joint[0]+math.cos(angle)*reach,centre_y+rng.uniform(-.5,.5)*vertical,joint[2]+math.sin(angle)*reach)
            fork=(x+lean[0],ground+max(2,round(height*.45)),z+lean[1])
            branch((x,ground+1,z),fork);branch(fork,end)
            rr=radius*rng.uniform(.42,.6)
            crown(*end,rr,vertical*rng.uniform(.55,.8),rr)
        # One high lobe reaches the supplied canopy height.
        crown(joint[0]-.5,ground+height-vertical*.55,joint[2]+.5,radius*.5,vertical*.55,radius*.5)
        if profile=='weeping':
            for i in range(14):
                angle=i*math.tau/14;xx=round(x+math.cos(angle)*radius*.9);zz=round(z+math.sin(angle)*radius*.9)
                if (xx-x)**2+(zz-z)**2>radius**2:continue
                for yy in range(ground+max(3,round(height*.3)),round(centre_y)+1):cells.setdefault((xx,yy,zz),leaves+'_leaves')
    if height>=20 and radius>=5:
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            branch((x,ground+1,z),(x+dx,ground+1,z+dz));branch((x,ground+3,z),(x+dx,ground+1,z+dz))
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
