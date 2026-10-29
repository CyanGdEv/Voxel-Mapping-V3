"""Complete the reference-assisted effigy and separate planned timber from trees."""
from collections import Counter, defaultdict
import math

import numpy as np
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.affinity import affine_transform

from .generation_cycles import file_hash

VERSION = 'wicker-structural-reconstruction-v1'


def blocked_vegetation(layers, rows, cols, levels):
    """A vertical semantic mask; real canopy above/beyond it remains eligible."""
    if not hasattr(layers, 'structural_vegetation_min'):
        return np.zeros(np.shape(levels), bool)
    return ((levels >= layers.structural_vegetation_min[rows, cols])
            & (levels <= layers.structural_vegetation_max[rows, cols]))


def volume(scene, geometry, maximum_y):
    l = scene.l
    if not hasattr(l, 'structural_vegetation_min'):
        l.structural_vegetation_min = np.full(l.ground.shape, 32767, np.int16)
        l.structural_vegetation_max = np.full(l.ground.shape, -32768, np.int16)
    rr, cc = scene.cells(geometry)
    if not len(rr):
        return
    top = np.broadcast_to(maximum_y, rr.shape).astype(np.int16)
    low = l.ground[rr, cc]+1
    valid = top >= low
    rr, cc, top, low = rr[valid], cc[valid], top[valid], low[valid]
    l.structural_vegetation_min[rr, cc] = np.minimum(l.structural_vegetation_min[rr, cc], low)
    l.structural_vegetation_max[rr, cc] = np.maximum(l.structural_vegetation_max[rr, cc], top)


def support_volumes(scene):
    """Source brown-footing/member corridors, bounded by their own deck level."""
    from .alton_aligned_world import WICKER_AFFINE
    profile = scene.structure_profile['vegetation']
    rows = scene.l.wicker_quality['fence_supports']['constructed_supports']
    corridors = 0
    for row in rows:
        foot = row['source_post']['xy']
        target = row['target']['xy']
        corridor = affine_transform(LineString([foot, target]), WICKER_AFFINE)
        if corridor.length < .05:
            corridor = corridor.centroid
        geometry = corridor.buffer(profile['support_horizontal_margin_m'])
        top = math.ceil(row['deck_top_m']+scene.l.offset+profile['support_upper_margin_m'])
        volume(scene, geometry, top)
        corridors += 1
    for row in getattr(scene.l,'parent_wicker_supports',()):
        corridor=affine_transform(LineString([row['source_post']['xy'],row['target']['xy']]),WICKER_AFFINE)
        volume(scene,corridor.buffer(profile['support_horizontal_margin_m']),
            math.ceil(row['deck_top_m']+scene.l.offset+profile['support_upper_margin_m']))
    scene.records.append({'id':'wicker-support-vegetation-separation',
        'role':'registered_brown_footing_to_assigned_deck_structural_volumes',
        'source_corridors':corridors, 'quality_report_sha256':file_hash(scene.l.wicker/'quality-report.json'),
        'horizontal_margin_m':profile['support_horizontal_margin_m'],
        'upper_deck_margin_m':profile['support_upper_margin_m'],
        'source_support_blocks_relocated':False, 'vegetation_returns_bulk_converted_to_wood':False,
        'raw_survey_classifications_overwritten':False})


def effigy_model(profile, e0, n0, offset):
    """Connected hollow body, two sculpted faces and curled horns in native cells.

    This completes a shape from explicit references; it is not raw-point truth.
    Running passages and retained geometry are applied separately by the scene.
    """
    if profile.get('mesh')=='stepped-woven-bust-v2':
        from .wicker_effigy_sculpture import sculpted_effigy
        return sculpted_effigy(profile,e0,n0,offset)
    front = np.asarray(profile['front_bng_direction'], float)
    front /= np.linalg.norm(front)
    side = np.array([-front[1], front[0]])
    body = np.asarray(profile['body_center_bng_en'], float)
    head = np.asarray(profile['head_center_bng_en'], float)
    head_uv = np.array([(head-body)@side, (head-body)@front])
    base, height = profile['base_odn_m'], profile['height_m']
    body_sections = np.asarray(profile['body_sections_height_half_width_half_depth_m'],float)
    head_sections = np.asarray(profile['head_sections_height_half_width_half_depth_m'],float)
    thickness = profile['shell_thickness_m']
    result = {}
    def world(u,v,h):
        en = body+u*side+v*front
        return int(math.floor(en[0]-e0)), int(math.floor(base+h+offset)), int(math.floor(n0-en[1]))
    def material(u,v,h,head_part=False):
        rib = (int(math.floor(u*1.1)) % 3 == 0 or int(math.floor(h)) % 4 == 0)
        if rib:return profile['rib_material']
        return profile['head_material'] if head_part else profile['body_material']
    def signed_shell(u,v,ru,rv):
        outer=(abs(u)/ru)**4+(abs(v)/rv)**4 <= 1
        inner=(abs(u)/max(.2,ru-thickness))**4+(abs(v)/max(.2,rv-thickness))**4 < 1
        return outer, inner
    # Sample at sub-block spacing, then voxelise once. All shape parts share a
    # common BNG frame; a global footprint extrusion would erase the arch.
    for h in np.arange(.25,height+.01,.5):
        if h <= body_sections[-1,0]:
            ru=np.interp(h,body_sections[:,0],body_sections[:,1])
            rv=np.interp(h,body_sections[:,0],body_sections[:,2])
            cap=h>=body_sections[-1,0]-.65
            for u in np.arange(-ru,ru+.01,.5):
                for v in np.arange(-rv,rv+.01,.5):
                    outer,inner=signed_shell(u,v,ru,rv)
                    arch=abs(u)<=profile['front_arch_half_width_m'] and h < profile['arch_spring_height_m']+profile['arch_rise_m']*math.sqrt(max(0,1-(u/profile['front_arch_half_width_m'])**2))
                    if outer and (not inner or cap) and not arch:
                        result[world(u,v,h)]=material(u,v,h)
        if h >= head_sections[0,0]:
            ru=np.interp(h,head_sections[:,0],head_sections[:,1])
            rv=np.interp(h,head_sections[:,0],head_sections[:,2])
            for u in np.arange(-ru,ru+.01,.45):
                for v in np.arange(-rv,rv+.01,.45):
                    outer,inner=signed_shell(u,v,ru,rv)
                    if outer and (not inner or h>height-1):
                        result[world(head_uv[0]+u,head_uv[1]+v,h)]=material(u,v,h,True)
    # Tapered ram muzzle on the plaza-facing side.
    for h in np.arange(11.3,15.5,.4):
        width=np.interp(h,[11.3,12.5,15.5],[.45,1.0,2.3])
        nose=head_uv[1]+2.1+(15.5-h)*.32
        for u in np.arange(-width,width+.01,.4):
            for v in np.arange(head_uv[1]+1.8,nose+.1,.4):
                result[world(head_uv[0]+u,v,h)]=profile['head_material']
    # Human brow, nose, cheek/beard and dark eye/mouth recesses on the reverse.
    for h in np.arange(11.5,16.4,.4):
        face=head_uv[1]-2.05-(h-13.0)*.15
        for u in np.arange(-2.0,2.01,.4):
            result[world(head_uv[0]+u,face,h)]=profile['head_material']
        if 12.7<=h<=15.1:
            for u in (-.35,0,.35):
                result[world(head_uv[0]+u,face-.6,h)]=profile['rib_material']
    for u in (-1.25,1.25):
        for v in np.arange(2.0,3.35,.3):
            result[world(head_uv[0]+u,head_uv[1]-v,15.1)]=profile['head_material']
            result[world(head_uv[0]+u,head_uv[1]+v,14.7)]=profile['head_material']
        result[world(head_uv[0]+u,head_uv[1]-3.25,15.1)]='black_concrete'
        result[world(head_uv[0]+u,head_uv[1]+3.25,14.7)]='black_concrete'
    for u in (-.6,0,.6):
        result[world(head_uv[0]+u,head_uv[1]-2.9,12.2)]=profile['recess_material']
    # Curled horns: retain both their opening and raised tips.
    path=np.asarray(profile['ram_horn_control_points_u_v_height_m'],float)
    for sign in (-1,1):
        control=path.copy();control[:,0]*=sign;control[:,:2]+=head_uv
        for a,b in zip(control,control[1:]):
            for t in np.linspace(0,1,max(3,int(np.linalg.norm(b-a)*8))):
                u,v,h=a+t*(b-a)
                for du,dv,dh in [(0,0,0),(.35,0,0),(-.35,0,0),(0,.35,0),(0,-.35,0),(0,0,.35),(0,0,-.35)]:
                    result[world(u+du,v+dv,h+dh)]=profile['rib_material']
    if profile.get('minecraft_style'):
        minecraft_finish(result,profile,world,head_uv,side,front,body,base,offset)
    cap=base+height+offset
    for key in result:
        if key[1] < cap < key[1]+1 and abs(cap-key[1]-.5)<1e-6:
            result[key]='oak_slab'
    return result


def minecraft_finish(result,profile,world,head_uv,side,front,body,base,offset):
    """Apply the user's stepped Minecraft blockwork to the connected sculpture."""
    style=profile['minecraft_style']
    def facing(direction):
        dx,dz=direction[0],-direction[1]
        return ('east' if dx>0 else 'west') if abs(dx)>=abs(dz) else ('south' if dz>0 else 'north')
    forward,back=facing(front),facing(-front)
    # Break up broad flat walls with warm infill and vertical/horizontal timber
    # strips. All edits are on the owned sculpture, never on ride/support blocks.
    for key,m in list(result.items()):
        # Native cell centres transformed back into the same local frame.
        origin=np.asarray(world(0,0,.25))
        delta=np.array([key[0]-origin[0],-(key[2]-origin[2])],float)
        u,v=delta@side,delta@front
        h=key[1]-(base+offset)+.5
        if m==profile['body_material'] and 1<h<9.5:
            if (int(math.floor(u))+int(math.floor(h))*2)%5==0:
                result[key]=style['body_infill']
            elif int(math.floor(h))%3==0:
                result[key]='spruce_stairs_'+(forward if v>=0 else back)
    # Door plates and sparse posts give the vertical woven/boarded appearance in
    # the closeups, with open areas beneath the shoulder line.
    for sign in (-1,1):
        direction=forward if sign>0 else back
        for h in (2.5,4.5,7.5,9.5):
            for u in (-4.6,-3.6,3.6,4.6):
                key=world(u,sign*3.35,h)
                if key in result:result[key]='oak_trapdoor_'+direction
        for u in (-5.0,5.0):
            key=world(u,sign*1.5,10.9)
            result[key]='oak_fence'
    # Pale collar beneath the two-faced head; horizontal slabs contrast with
    # the darker neck and shoulders just as in the user's Minecraft reference.
    for u in np.arange(-2.7,2.71,.4):
        for v in (-2.35,2.35):
            result[world(head_uv[0]+u,head_uv[1]+v,10.5)]=style['pale_collar']
    for v in np.arange(-2.35,2.36,.4):
        for u in (-2.7,2.7):
            result[world(head_uv[0]+u,head_uv[1]+v,10.5)]=style['pale_collar']
    # Stepped jaw/forehead and narrow trapdoor eye panels replace a square,
    # opaque eye band. Their orientation follows the two opposite faces.
    for sign,direction in ((1,forward),(-1,back)):
        for u in (-1.25,1.25):
            result[world(head_uv[0]+u,head_uv[1]+sign*3.25,14.7 if sign>0 else 15.1)]='dark_oak_trapdoor_'+direction
        for u in np.arange(-1.6,1.61,.4):
            result[world(head_uv[0]+u,head_uv[1]+sign*2.55,12.0)]='oak_stairs_'+direction
            result[world(head_uv[0]+u,head_uv[1]+sign*2.1,16.5)]='oak_stairs_'+direction
    # Dark C-shaped horns retain the previous centre curve and receive stairs
    # along the turning direction, with half-slab tips.
    if style.get('dark_horns'):
        path=np.asarray(profile['ram_horn_control_points_u_v_height_m'],float)
        for sign in (-1,1):
            control=path.copy();control[:,0]*=sign;control[:,:2]+=head_uv
            for j,(a,b) in enumerate(zip(control,control[1:])):
                d=side*(b[0]-a[0])+front*(b[1]-a[1]);direction=facing(d)
                for t in np.linspace(0,1,max(3,int(np.linalg.norm(b-a)*8))):
                    u,v,h=a+t*(b-a)
                    for du,dv,dh in [(0,0,0),(.35,0,0),(-.35,0,0),(0,.35,0),(0,-.35,0),(0,0,.35),(0,0,-.35)]:
                        result[world(u+du,v+dv,h+dh)]='dark_oak_stairs_'+direction if j%2 else 'dark_oak_planks'
            u,v,h=control[-1];result[world(u,v,h)]='dark_oak_slab'
    if style.get('shoulder_campfires'):
        for side_sign in (-1,1):
            for v in (-1.3,0,1.3):
                key=world(side_sign*4.8,v,10.9)
                # A full timber pad remains directly beneath every emitter.
                result[key[0],key[1]-1,key[2]]=profile['body_material']
                result[key]='campfire'


def complete_effigy(scene, feature, geometry):
    p=scene.structure_profile['big_bob'];l=scene.l
    proposed=effigy_model(p,l.e0,l.n0,l.offset)
    mask_proposal=proposed
    if scene.structure_profile.get('track_interactions'):
        from .wicker_track_interactions import fit_figure
        proposed=fit_figure(scene,proposed,scene.structure_profile)
    used=0;skipped=Counter()
    for (x,y,z),material in sorted(proposed.items()):
        r=z+l.height
        if not(0<=x<l.width and 0<=r<l.height) or y<=l.ground[r,x]:
            skipped['terrain']+=1;continue
        if (x,y,z) in scene.old_air or (x,y,z) in scene.air:
            skipped['running_passage']+=1;continue
        if (x,y,z) in scene.old_solid:
            skipped['retained_structure']+=1;continue
        used+=scene.add(x,y,z,material,feature['id'])
    xy=np.array([[l.e0+x+.5,l.n0-z-.5] for x,y,z in mask_proposal])
    footprint=MultiPoint(xy).convex_hull.buffer(scene.structure_profile['vegetation']['figure_horizontal_margin_m'])
    footprint=footprint.union(geometry.buffer(.75))
    preceding=scene.structure_profile['vegetation'].get('preceding_figure_volume_bng_ring')
    if preceding:footprint=footprint.union(Polygon(preceding))
    volume(scene,footprint,math.ceil(p['base_odn_m']+p['height_m']+l.offset+
        scene.structure_profile['vegetation']['figure_upper_margin_m']))
    # All original route visits remain separate. No XY crossing joins them.
    visits=[]
    for i,(xy,top) in enumerate(zip(scene.track_xy,scene.track_top)):
        if footprint.covers(Point(xy)):
            station=scene.track_samples[i]['station_m']
            if not visits or station-visits[-1][-1][0]>4:visits.append([])
            visits[-1].append((station,float(top)))
    xyz,codes,ground=scene.load_cloud()
    from shapely import contains_xy
    inside=contains_xy(geometry,xyz[:,0],xyz[:,1])&(xyz[:,2]>ground+1)
    scene.records.append({'id':feature['id'],'role':'reference_assisted_complete_effigy',
        'native_blocks':int(used),'proposed_blocks':len(proposed),'withheld':dict(skipped),
        'body':'Stepped woven plank torso, raised chest ribbons, arched opening and inset panels' if p.get('mesh') else 'Hollow ribbed torso with arched lower opening, shoulders and neck',
        'heads':'Opposite ram muzzle/curled horns and human brow/nose/eyes/beard',
        'base_odn_m':p['base_odn_m'],'top_odn_m':p['base_odn_m']+p['height_m'],
        'retained_track_visits':[{'station_min_max_m':[v[0][0],v[-1][0]],'top_odn_min_max_m':[min(x[1] for x in v),max(x[1] for x in v)]} for v in visits],
        'raw_theming_context_returns':int(inside.sum()),
        'source_class_counts':dict(Counter(map(str,codes[inside].tolist()))),
        'shape_references':p['shape_references'],
        'minecraft_style':p.get('minecraft_style'),
        'interpretation':p['interpolation_authority'],'physical_detail_accuracy_verified':False,
        'source_returns_called_a_complete_measured_surface':False})


def report_vegetation(scene):
    l=scene.l
    if not hasattr(l,'structural_vegetation_min'):return
    leaf=l.cloud['leaf_voxels'];ids=(leaf&((1<<22)-1)).astype(np.int64)
    rr,cc=ids//l.width,ids%l.width;yy=(leaf>>22).astype(np.int64)-512+l.offset
    blocked=blocked_vegetation(l,rr,cc,yy)
    scene.records.append({'id':'wicker-structural-vegetation-mask','role':'bounded_semantic_override',
        'structural_columns':int((l.structural_vegetation_max>-32768).sum()),
        'observed_leaf_cells_rejected_from_structural_volumes':int(blocked.sum()),
        'source_survey_classes_modified':False,'surrounding_woodland_globally_cleared':False,
        'vertical_policy':'Exclude only ground-to-member/figure caps; source canopy above and outside remains eligible'})
