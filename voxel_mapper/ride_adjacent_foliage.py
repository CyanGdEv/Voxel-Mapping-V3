"""User-directed leaf-to-fence interpretation near the wooden ride deck."""
from collections import Counter,defaultdict
import math

import numpy as np
from scipy.spatial import cKDTree


def deck_boxes(decks,include_supports=False):
    keys=[];low=[];high=[]
    for (x,y,z),m in decks.items():
        fence=include_supports and m=='dark_oak_fence'
        if not fence and m not in ('oak_planks','spruce_planks','oak_slab','spruce_slab','oak_slab_top','spruce_slab_top'):continue
        keys.append((x,y,z));low.append((x,y+(.5 if m.endswith('_slab_top') else 0),z))
        high.append((x+1,y+(1.5 if fence else .5 if m.endswith('_slab') else 1),z+1))
    return np.asarray(low,float),np.asarray(high,float)


def nearby_cells(cells,decks,distance=2,include_supports=False):
    """Exact AABB gaps within the radius; broad-phase misses return infinity."""
    low,high=deck_boxes(decks,include_supports)
    if not len(low):raise ValueError('Actual wooden track deck geometry required')
    centres=(low+high)/2;tree=cKDTree(centres)
    cells=np.asarray(cells,float);result=np.full(len(cells),np.inf)
    # Two unit boxes contribute at most sqrt(3) to centre-to-centre radius.
    groups=tree.query_ball_point(cells+.5,distance+np.sqrt(3.5625 if include_supports else 3)+1e-7)
    for i,indices in enumerate(groups):
        if not indices:continue
        gap=np.maximum(np.maximum(low[indices]-(cells[i]+1),cells[i]-high[indices]),0)
        result[i]=np.sqrt(np.min(np.sum(gap*gap,axis=1)))
    return result


def apply(l,settings):
    material=settings['material'];distance=float(settings['distance_blocks'])
    if material!='dark_oak_fence' or distance!=2:raise ValueError('Explicit two-block dark-oak rule required')
    decks=l.wicker_track_native_decks
    members={}
    if settings.get('include_retained_support_members'):
        members={(cx*16+x,y,cz*16+z):m for (cx,cz),values in l.detail.items()
                 for x,y,z,m in values if m=='dark_oak_fence'}
    targets={**decks,**members};lo,hi=deck_boxes(targets,bool(members))
    leaf=l.cloud['leaf_voxels'];ids=(leaf&((1<<22)-1)).astype(np.int64)
    rows,cols=ids//l.width,ids%l.width;yy=(leaf>>22).astype(np.int64)-512+l.offset
    # Broad phase is conservative; the final test uses full 3-D solid bounds.
    broad=(cols>=lo[:,0].min()-3)&(cols<=hi[:,0].max()+2)&(rows-l.height>=lo[:,2].min()-3)&(rows-l.height<=hi[:,2].max()+2)
    broad&=(yy>=lo[:,1].min()-3)&(yy<=hi[:,1].max()+2)
    rr,cc,ys=rows[broad],cols[broad],yy[broad]
    cells=np.column_stack([cc,ys,rr-l.height]);d=nearby_cells(cells,targets,distance,bool(members))
    choose=d<=distance+1e-8;rr,cc,ys,cells,d=rr[choose],cc[choose],ys[choose],cells[choose],d[choose]
    l.ride_wood_candidate_cells=[tuple(map(int,k)) for k in cells]
    occupied={(cx*16+x,y,cz*16+z):m for source in (l.detail,getattr(l,'reference_detail',{}),getattr(l,'lidar_detail',{}))
              for (cx,cz),values in source.items() for x,y,z,m in values}
    protected={(cx*16+x,y,cz*16+z) for source in (l.clear,getattr(l,'reference_air',{})) for (cx,cz),values in source.items() for x,y,z in values}
    fences=defaultdict(list);clear=defaultdict(list);held=Counter();accepted=[]
    aperture=getattr(l,'wicker_aperture_intersects',lambda k,m:False)
    riding=defaultdict(list)
    for sample in getattr(l,'wicker_native_samples',()):
        x,floor,z=sample['xyz'];riding[math.floor(x),math.floor(z)].append((floor,floor+3))
    for r,c,y,key,gap in zip(rr,cc,ys,cells,d):
        key=tuple(map(int,key));x,y,z=key
        if y<=l.ground[r,c] or l.footprints[r,c] or l.water[r,c]>-32768:held['ground_building_water']+=1;continue
        if l.family[r,c]>0 and y<=l.ground[r,c]+4:held['walking_surface_headroom']+=1;continue
        if key in occupied:held['existing_structure']+=1;continue
        reason=None
        if (key in protected or (x,y+1,z) in protected or aperture(key,material) or
            any(y+1.5>low+.01 and y<high-.01 for low,high in riding.get((x,z),()))):reason='running_opening'
        above=(x,y+1,z)
        if above in occupied:
            m=decks.get(above)
            # A fence may bear into the underside, but cannot protrude above
            # the retained running surface or penetrate unrelated architecture.
            allowed=m and y+1.5<=above[1]+(.5 if m.endswith('_slab') else 1)+1e-8
            if not allowed:reason='fence_height_collision'
        group=x//16,z//16
        if reason:
            held[reason]+=1;clear[group].append((x%16,y,z%16));continue
        fences[group].append((x%16,y,z%16,material));accepted.append((key,float(gap)))
    l.ride_wood_fences=dict(fences);l.ride_wood_clear=dict(clear)
    l.ride_wood_source_cells={k:d for k,d in accepted}
    l.audit['ride_adjacent_foliage']={'scope':'retained Wicker Man deck and brown-footprint support members' if members else 'retained Wicker Man wooden track','material':material,
        'distance_blocks':distance,'distance_metric':'Euclidean 3-D separation of source leaf cell and actual deck/support bounds' if members else 'Euclidean 3-D separation of source leaf cell and actual solid deck bounds',
        'eligible_source_cells_within_distance':len(cells),'fence_cells':len(accepted),'withheld':dict(held),
        'clearance_cells':sum(map(len,clear.values())),'maximum_accepted_distance_blocks':max((d for _,d in accepted),default=0),
        'source_cell_positions_moved':False,'raw_survey_classifications_modified':False,
        'policy_authority':'User explicitly requested leaf cells within two blocks of a track section be converted to fences; keep track and running openings clear.'}
    if members:
        deck_distance=nearby_cells(np.asarray(list(l.ride_wood_source_cells)),decks,distance)
        l.audit['ride_adjacent_foliage'].update(support_member_cells_used=len(members),
            fence_cells_beyond_deck_rule=int((deck_distance>distance+1e-8).sum()),
            structure_extension_authority='User reports remaining support fences misclassified as leaves, with mapped screenshots of supports well below the deck. Extend the same two-block 3-D rule to retained support members.')
