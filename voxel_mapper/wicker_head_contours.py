"""Reference-assisted opposing faces, quantised to native half-block contours.

The head has its own survey context and facing anchor. The figure pose does not
rotate the track or the registered support-footprint frame.
"""
import math
import heapq

import numpy as np


def contoured_head(profile,e0,n0,offset):
    front=np.asarray(profile['head_front_bng_direction'],float);front/=np.linalg.norm(front)
    side=np.array([-front[1],front[0]])
    centre=np.asarray(profile['head_center_bng_en'],float);base=profile['base_odn_m']
    section=np.asarray(profile['contoured_head']['skull_sections_h_width_depth_m'],float)
    muzzle=np.asarray(profile['contoured_head']['muzzle_sections_h_width_front_m'],float)
    human=np.asarray(profile['contoured_head']['human_sections_h_width_front_m'],float)
    controls=np.asarray(profile['contoured_head']['horn_path_u_v_h_m'],float)
    horn_paths=[controls*np.array([sign,1,1]) for sign in (-1,1)]
    horn_radius=float(profile['contoured_head']['horn_radius_m'])
    octants=np.array([(x,y,z) for x in (.25,.75) for y in (.25,.75) for z in (.25,.75)])
    template=[('',np.ones(8,bool)),('_slab',octants[:,1]<.5),('_slab_top',octants[:,1]>.5)]
    for direction,axis,positive in [('east',0,True),('west',0,False),('south',2,True),('north',2,False)]:
        raised=octants[:,axis]>.5 if positive else octants[:,axis]<.5
        template.append(('_stairs_'+direction,(octants[:,1]<.5)|raised))
        template.append(('_stairs_'+direction+'_top',(octants[:,1]>.5)|raised))

    def local(points):
        en=np.column_stack([points[:,0]+e0,n0-points[:,2]])-centre
        return np.column_stack([en@side,en@front,points[:,1]-base-offset])

    def horn_distance(points):
        distance=np.full(len(points),np.inf)
        for path in horn_paths:
            for a,b in zip(path,path[1:]):
                d=b-a;t=np.clip((points-a)@d/(d@d),0,1)
                distance=np.minimum(distance,np.linalg.norm(points-a-t[:,None]*d,axis=1))
        return distance

    def shape(points):
        u,v,h=points.T
        ru=np.interp(h,section[:,0],section[:,1]);rv=np.interp(h,section[:,0],section[:,2])
        skull=(u/ru)**2+(v/rv)**2<=1
        skull&=(h>=section[0,0])&(h<=section[-1,0])
        width=np.interp(h,muzzle[:,0],muzzle[:,1]);face=np.interp(h,muzzle[:,0],muzzle[:,2])
        back=1.0;mid=(face+back)/2;depth=(face-back)/2
        ram=(u/width)**2+((v-mid)/np.maximum(.1,depth))**2<=1
        ram&=(h>=muzzle[0,0])&(h<=muzzle[-1,0])
        width=np.interp(h,human[:,0],human[:,1]);face=np.interp(h,human[:,0],human[:,2])
        edge=face+.45*(abs(u)/width)**2
        man=(abs(u)<=width)&(v>=edge)&(v<=edge+1.25)
        man&=(h>=human[0,0])&(h<=human[-1,0])
        nose=(abs(u)<.42)&(14.15<=h)&(h<=15.7)&(v>=face-.7)&(v<=face+.7)
        neck=((u/1.35)**2+(v/1.35)**2<=1)&(11.3<=h)&(h<=13.3)
        occupied=skull|ram|man|nose|neck
        # Recesses have actual air depth. The narrow backing boards are added
        # later, so neither face gets a pair of projecting block-button eyes.
        eyes=(.55<abs(u))&(abs(u)<1.65)&(15.1<h)&(h<15.7)
        occupied&=~(eyes&(((v>1.55)&(v<2.75))|((v<face+.4)&(v>face-.5))))
        mouth=(abs(u)<.85)&(13.35<h)&(h<13.85)&(v<face+.35)&(v>face-.6)
        occupied&=~mouth
        horns=horn_distance(points)<=horn_radius
        return occupied|horns,horns

    all_points=np.vstack([*horn_paths,[[0,0,section[0,0]],[0,0,section[-1,0]]]])
    span=max(5,float(abs(all_points[:,:2]).max()+1))
    corners=np.array([centre+side*u+front*v for u in (-span,span) for v in (-span,span)])
    x0=math.floor(corners[:,0].min()-e0);x1=math.ceil(corners[:,0].max()-e0)
    z0=math.floor(n0-corners[:,1].max());z1=math.ceil(n0-corners[:,1].min())
    y0=math.floor(base+11.3+offset)
    y1=math.ceil(base+profile['height_m']+offset)
    result={}
    for x in range(x0,x1):
        for z in range(z0,z1):
            for y in range(y0,y1):
                p=local(octants+np.array([x,y,z]));wanted,horns=shape(p)
                if not wanted.any():continue
                # Prefer empty over a large protrusion for a tiny corner hit.
                # Boundary steps are chosen from their actual octant occupancy.
                costs=[1.4*np.sum(mask&~wanted)+np.sum(wanted&~mask) for _,mask in template]
                best=int(np.argmin(costs))
                if costs[best]>=wanted.sum():continue
                suffix,mask=template[best]
                horn=bool(np.sum(horns&mask)>np.sum(mask)*.45)
                u,v,h=local(np.array([[x+.5,y+.5,z+.5]]))[0]
                wood='dark_oak' if horn else 'spruce' if (13.8<h<14.3 or 16.15<h<16.55) and v>0 else 'oak'
                result[x,y,z]=wood+(suffix if suffix else '_planks')

    def cell(u,v,h):
        en=centre+side*u+front*v
        return math.floor(en[0]-e0),math.floor(base+h+offset),math.floor(n0-en[1])
    def put(u,v,h,material):result[cell(u,v,h)]=material
    # Thin sloping brows, a slim nose bridge and a lip, instead of a cubic mask.
    def ribbon(points,wood='oak'):
        for a,b in zip(np.asarray(points,float),np.asarray(points,float)[1:]):
            en_direction=side*(b[0]-a[0])+front*(b[1]-a[1])
            dx,dz=en_direction[0],-en_direction[1]
            direction=('east' if dx>0 else 'west') if abs(dx)>=abs(dz) else ('south' if dz>0 else 'north')
            for t in np.linspace(0,1,max(3,math.ceil(np.linalg.norm(b-a)*6))):
                put(*(a+t*(b-a)),wood+'_stairs_'+direction)
    for sign in (-1,1):
        ribbon([(sign*.45,2.25,15.85),(sign*1.2,2.05,16.05),(sign*1.9,1.55,15.8)])
        ribbon([(sign*.4,-2.3,15.9),(sign*1.1,-2.05,16.15),(sign*1.8,-1.6,15.95)])
        put(sign*1.05,1.65,15.3,'dark_oak_slab_top')
        put(sign*1.05,-1.65,15.3,'dark_oak_slab_top')
    ribbon([(-.85,-2.25,13.15),(0,-2.65,12.95),(.85,-2.25,13.15)])
    put(0,-2.25,13.55,'dark_oak_slab_top')
    # A half-block snout tip drops forward, with narrow inset nostril boards.
    put(0,3.05,12.7,'oak_slab_top')
    # A thin pale collar follows the new neck rather than the old head's yaw.
    for angle in np.linspace(0,2*np.pi,48,endpoint=False):
        key=cell(1.65*np.cos(angle),1.65*np.sin(angle),12.2)
        if key not in result:result[key]='smooth_stone_slab'
    _stitch_contours(result,local,horn_distance,profile,cell)
    return result


def _stitch_contours(result,local,horn_distance,profile,cell):
    """Narrow timber ties join metre-grid corner crossings around open curls."""
    from collections import deque
    directions=((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1))
    def neighbours(k):
        for d in directions:yield tuple(a+b for a,b in zip(k,d))
    hole=profile['contoured_head']['horn_opening_test_u_v_h']
    protected={cell(sign*hole[0],hole[1],hole[2]) for sign in (-1,1)}
    # Keep the opening explicit after native quantisation.
    for key in protected:result.pop(key,None)
    remaining=set(result);parts=[]
    while remaining:
        component={remaining.pop()};queue=deque(component)
        while queue:
            for key in neighbours(queue.popleft()):
                if key in remaining:remaining.remove(key);component.add(key);queue.append(key)
        parts.append(component)
    parts.sort(key=len,reverse=True);root=set(parts[0]);bounds=np.array(list(result));low=bounds.min(0)-1;high=bounds.max(0)+1
    for component in parts[1:]:
        # Loose decorative collar corners are omitted instead of making a
        # solid square band around a narrow neck.
        if all(result[k].startswith('smooth_stone') for k in component):
            for key in component:result.pop(key)
            continue
        queue=[(0,0,key) for key in sorted(component)];heapq.heapify(queue)
        previous={k:None for k in component};costs={k:0 for k in component};finish=None
        while queue:
            score,steps,current=heapq.heappop(queue)
            if score!=costs[current]:continue
            if current in root:finish=current;break
            if steps>=6:continue
            for key in neighbours(current):
                if key in protected or np.any(np.array(key)<low) or np.any(np.array(key)>high):continue
                point=local(np.array(key,float)[None,:]+.5)
                distance=float(horn_distance(point)[0]);new=score+(0 if key in root else 1+min(4,distance)*2)
                if new>=costs.get(key,np.inf):continue
                costs[key]=new;previous[key]=current;heapq.heappush(queue,(new,steps+1,key))
        if finish is None:raise ValueError('Head contours cannot connect while preserving the horn opening')
        current=finish
        while current is not None:
            if current not in result:
                distance=float(horn_distance(local(np.array(current,float)[None,:]+.5))[0])
                result[current]='dark_oak_fence' if distance<1.2 else 'oak_slab_top'
            root.add(current);current=previous[current]
        root.update(component)
