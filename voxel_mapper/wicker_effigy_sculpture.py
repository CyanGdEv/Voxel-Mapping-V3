"""Stepped timber sculpture guided by the user's Minecraft close-up references.

This is a model of an identified object. It does not promote vegetation-labelled
survey points into measured timber, or change any retained ride member.
"""
import math

import numpy as np


def sculpted_effigy(profile, e0, n0, offset):
    front=np.asarray(profile['front_bng_direction'],float)
    front/=np.linalg.norm(front)
    side=np.array([-front[1],front[0]])
    body=np.asarray(profile['body_center_bng_en'],float)
    delta=np.asarray(profile['head_center_bng_en'],float)-body
    hu,hv=delta@side,delta@front
    base=profile['base_odn_m'];height=profile['height_m']
    sections=np.asarray(profile['body_sections_height_half_width_half_depth_m'])
    head_sections=np.asarray(profile['head_sections_height_half_width_half_depth_m'])
    result={}

    def facing(direction):
        dx,dz=direction[0],-direction[1]
        return ('east' if dx>0 else 'west') if abs(dx)>=abs(dz) else ('south' if dz>0 else 'north')

    forward,back=facing(front),facing(-front)

    def world(u,v,h):
        en=body+u*side+v*front
        return math.floor(en[0]-e0),math.floor(base+h+offset),math.floor(n0-en[1])

    def put(u,v,h,material):
        result[world(u,v,h)]=material

    def beam(points,wood='oak',surface='stairs'):
        """A deliberately routed stepped ribbon, not a full log-wall texture."""
        previous=None
        for a,b in zip(np.asarray(points,float),np.asarray(points,float)[1:]):
            direction=facing(side*(b[0]-a[0])+front*(b[1]-a[1]))
            material=wood+'_stairs_'+direction if surface=='stairs' else wood+'_'+surface
            for t in np.linspace(0,1,max(3,math.ceil(np.linalg.norm(b-a)*10))):
                key=world(*(a+t*(b-a)))
                # Supercover ties at 45 degrees so a diagonal does not consist
                # of isolated corner-touching cells at native metre resolution.
                if previous is not None:
                    bridge=list(previous)
                    for axis in (0,2,1):
                        while bridge[axis]!=key[axis]:
                            bridge[axis]+=1 if key[axis]>bridge[axis] else -1
                            result[tuple(bridge)]=material
                result[key]=material;previous=key

    def shell(u,v,ru,rv,thickness):
        outer=(abs(u)/ru)**3+(abs(v)/rv)**3<=1
        inner=(abs(u)/max(.2,ru-thickness))**3+(abs(v)/max(.2,rv-thickness))**3<1
        return outer and not inner

    # Layered plank shell with a narrow, arched chest opening. Upper shoulders
    # rise above the high track visit; the scene reserves every actual passage.
    for h in np.arange(.25,sections[-1,0]+.01,.5):
        ru=np.interp(h,sections[:,0],sections[:,1]);rv=np.interp(h,sections[:,0],sections[:,2])
        for u in np.arange(-ru,ru+.01,.35):
            arch=profile['arch_spring_height_m']+profile['arch_rise_m']*math.sqrt(max(0,1-(u/profile['front_arch_half_width_m'])**2))
            if abs(u)<=profile['front_arch_half_width_m'] and h<arch:continue
            for v in np.arange(-rv,rv+.01,.35):
                cap=h>11.35 and abs(u)>3.3
                if not(shell(u,v,ru,rv,profile['shell_thickness_m']) or
                       (cap and (abs(u)/ru)**3+(abs(v)/rv)**3<=1)):continue
                material='spruce_planks' if int(h)%4 else 'oak_planks'
                # Infill is arranged in recessed side panels, with the wooden
                # frame added afterwards. No broad vertical log cladding.
                if abs(u)>3.0 and int(h)%4 in (1,2) and abs(v)>rv-.7:
                    material='terracotta'
                put(u,v,h,material)

    # Both faces of the chest receive their own arch rim and woven ribs.
    for face_sign,direction in ((1,forward),(-1,back)):
        rim=[(-2.5,3.35,0),(-2.5,3.4,3.8),(-2.0,3.45,5.7),
             (-1.0,3.5,6.7),(0,3.5,7.0),(1.0,3.5,6.7),
             (2.0,3.45,5.7),(2.5,3.4,3.8),(2.5,3.35,0)]
        beam([(u,v*face_sign,h) for u,v,h in rim])
        for h in (7.5,9.5,11.4):
            beam([(-4.9,face_sign*2.7,h-.3),(-2.3,face_sign*3.4,h),
                  (2.3,face_sign*3.4,h),(4.9,face_sign*2.7,h-.3)],wood='spruce' if h==9.5 else 'oak')
        for sign in (-1,1):
            # Crossing bands wrap around each shoulder and side of the arch.
            for index,points in enumerate((
                [(4.7,2.35,1.0),(3.1,3.3,3.5),(5.3,2.8,6.6),(3.3,3.4,9.0),(5.5,2.6,11.7)],
                [(3.2,3.2,1.0),(5.1,2.7,4.0),(3.3,3.4,6.6),(5.4,2.7,9.0),(4.0,3.0,11.9)])):
                beam([(sign*u,face_sign*v,h) for u,v,h in points],wood='oak' if index==0 else 'spruce')
            # Board plates sit between the raised ribbons rather than turning
            # the full shoulder into a column of bark-textured log blocks.
            for h in (2.5,5.5,8.5,10.5):
                key=world(sign*4.35,face_sign*2.9,h)
                if key in result:result[key]='oak_trapdoor_'+direction
            beam([(sign*5.0,face_sign*1.3,1),(sign*5.4,face_sign*1.5,5.5),
                  (sign*5.8,face_sign*1.3,9.6),(sign*5.0,face_sign*1.1,12.0)],wood='spruce')

    shoulder_result=dict(result)
    # A short neck and continuous collar seat the head on the shoulders.
    for h in np.arange(11.3,13.4,.35):
        for u in np.arange(-1.4,1.41,.35):
            for v in np.arange(-1.4,1.41,.35):
                if shell(u,v,1.55,1.55,.8):put(hu+u,hv+v,h,'spruce_planks')
    for u in np.arange(-2.45,2.46,.3):
        for v in (-1.95,1.95):put(hu+u,hv+v,12.3,'smooth_stone_slab')
    for v in np.arange(-1.95,1.96,.3):
        for u in (-2.45,2.45):put(hu+u,hv+v,12.3,'smooth_stone_slab')

    # The head is shorter and tapered. Shape, brows, cheek planes and the long
    # downward ram muzzle carry the likeness; dark door buttons are not eyes.
    for h in np.arange(head_sections[0,0],height+.01,.3):
        ru=np.interp(h,head_sections[:,0],head_sections[:,1]);rv=np.interp(h,head_sections[:,0],head_sections[:,2])
        for u in np.arange(-ru,ru+.01,.3):
            for v in np.arange(-rv,rv+.01,.3):
                if shell(u,v,ru,rv,.8) or h>16.65:
                    if (abs(u)/ru)**3+(abs(v)/rv)**3<=1:put(hu+u,hv+v,h,'oak_planks')
    for h in np.arange(12.7,16.25,.3):
        width=np.interp(h,[12.7,13.5,15.0,16.25],[.45,.85,1.55,2.1])
        v=np.interp(h,[12.7,14.3,16.25],[3.15,2.65,1.75])
        for u in np.arange(-width,width+.01,.3):
            for depth in np.arange(1.2,v+.01,.3):
                put(hu+u,hv+depth,h,'oak_planks')
        for u in (-width,width):put(hu+u,hv+v,h,'oak_stairs_'+forward)
    # Human face inclines upward, with cheeks, a narrow projecting nose and jaw.
    for h in np.arange(12.8,16.7,.3):
        width=np.interp(h,[12.8,14.5,15.8,16.7],[1.15,2.0,2.1,1.8])
        v=-np.interp(h,[12.8,14.5,16.7],[1.8,2.15,1.7])
        for u in np.arange(-width,width+.01,.3):put(hu+u,hv+v,h,'oak_planks')
        if 14.1<h<16.05:put(hu,hv+v-.65,h,'oak_stairs_'+back)
    for sign,direction in ((1,forward),(-1,back)):
        # Actual inset eye slots, backed in dark timber and overhung by brows.
        for side_sign in (-1,1):
            u=hu+side_sign*1.25
            for h in (15.1,15.45):
                for v in np.arange(1.6,2.81,.2):result.pop(world(u,hv+sign*v,h),None)
                put(u,hv+sign*1.55,h,'dark_oak_planks')
            beam([(hu+side_sign*.45,hv+sign*2.25,16.0),
                  (hu+side_sign*1.9,hv+sign*2.05,15.9)])
        beam([(hu-1.2,hv+sign*2.05,13.0),(hu,hv+sign*2.45,12.8),
              (hu+1.2,hv+sign*2.05,13.0)])
    put(hu,hv-2.45,13.7,'dark_oak_planks')
    for u in np.arange(-1.6,1.61,.35):put(hu+u,hv-1.7,16.8,'oak_stairs_'+back)

    # The curl lies around the side of the skull (front/depth versus height),
    # not across the face. Its centre is recessed behind the outer ring.
    path=profile['ram_horn_control_points_u_v_height_m']
    for sign in (-1,1):
        for u in np.arange(2.0,3.7,.2):
            for v in np.arange(-.7,.81,.2):
                for h in np.arange(14.5,15.9,.2):result.pop(world(hu+sign*u,hv+v,h),None)
        for h in (14.8,15.3):put(hu+sign*1.8,hv, h,'dark_oak_planks')
        beam([(hu+sign*u,hv+v,h) for u,v,h in path],wood='dark_oak')
        u,v,h=path[-1];put(hu+sign*u,hv+v,h,'dark_oak_slab')
    # Narrow dark horizontal slots remain visible underneath the brows, with
    # depth in the surrounding cheek planes instead of projecting door buttons.
    for sign in (-1,1):
        for u in (-1.2,1.2):put(hu+u,hv+sign*2.65,15.3,'dark_oak_slab_top')
    if profile.get('head_mesh')=='half-block-contoured-opposing-faces-v1':
        from .wicker_head_contours import contoured_head
        result=shoulder_result
        result.update(contoured_head(profile,e0,n0,offset))
    # Two shoulder emitters avoid the six overlapping smoke plumes of v5.
    for sign in (-1,1):
        put(sign*4.8,0,11.9,'spruce_planks')
        key=world(sign*4.8,0,13.1)
        result[key[0],key[1]-1,key[2]]='spruce_planks'
        result[key]='campfire'
        for v in (-1.5,1.5):put(sign*5.0,v,12.0,'oak_trapdoor_top')
        for v in (-1.5,1.5):
            beam([(sign*4.8,v,11.7),(sign*5.7,v,12.0)],wood='spruce')
            key=world(sign*5.7,v,12.7)
            result[key[0],key[1]-1,key[2]]='spruce_planks'
            result[key]='oak_fence'
    cap=base+height+offset
    for key in result:
        if key[1]<cap<key[1]+1 and abs(cap-key[1]-.5)<1e-6:result[key]='oak_slab'
    return result
