"""Mapped ride/monorail structures, separate from LiDAR foliage.

OSM layers constrain crossing order, never supply measured metric heights.
Class-6 samples outside building footprints are candidate structural context;
vegetation never supplies a track height. Unsurveyed profiles/supports stay
explicit estimates. Node identities, rather than XY intersections, join ways.
"""
from collections import Counter, defaultdict
import math
import xml.etree.ElementTree as ET

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point


STYLES = {
    'Galactica': {'rail':'white_concrete','support':'light_gray_concrete','clearance':5.,'inverted':True},
    'Nemesis Reborn': {'rail':'red_concrete','support':'black_concrete','clearance':5.,'inverted':True},
    'The Smiler': {'rail':'black_concrete','support':'light_gray_concrete','clearance':4.,'inverted':False},
    'monorail': {'rail':'light_gray_concrete','support':'gray_concrete','clearance':6.,'inverted':False},
}


def mapped_ways(path, project, requested):
    root=ET.parse(path).getroot()
    nodes={n.attrib['id']:(float(n.attrib['lon']),float(n.attrib['lat'])) for n in root.findall('node')}
    candidates={}
    for way in root.findall('way'):
        tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')}
        ids=[n.attrib['ref'] for n in way.findall('nd')]
        if len(ids)<2 or any(n not in nodes for n in ids) or tags.get('disused:roller_coaster'):continue
        if tags.get('roller_coaster')!='track' and tags.get('railway')!='monorail':continue
        candidates[way.attrib['id']]={'id':way.attrib['id'],'nodes':ids,'tags':tags}
    incident=defaultdict(set)
    for id,w in candidates.items():
        if w['tags'].get('roller_coaster')=='track':
            for n in w['nodes']:incident[n].add(id)
    result=[]
    for ride in requested:
        if ride not in STYLES:raise ValueError('Explicit supported ride family required')
        selected={id for id,w in candidates.items() if
                  (w['tags'].get('railway')=='monorail' and w['tags'].get('service') not in ('yard','spur') if ride=='monorail' else w['tags'].get('name')==ride)}
        if ride!='monorail':
            todo=list(selected)
            while todo:
                w=candidates[todo.pop()]
                for n in w['nodes']:
                    for other in incident[n]-selected:
                        name=candidates[other]['tags'].get('name')
                        if name and name!=ride:continue
                        selected.add(other);todo.append(other)
        for id in sorted(selected,key=int):
            w=candidates[id];a=np.array([nodes[n] for n in w['nodes']])
            e,n=project.transform(a[:,0],a[:,1]);line=LineString(np.column_stack([e,n]))
            if line.length>0:result.append({**w,'ride':ride,'line':line})
    return result


def grid_segment(a,b):
    """Bounded supercover: connect integer block centres without diagonal holes."""
    a=np.asarray(a,int);b=np.asarray(b,int);p=a.copy();yield tuple(p)
    delta=b-a;steps=int(np.max(np.abs(delta)))
    for i in range(1,steps+1):
        target=np.rint(a+delta*i/steps).astype(int)
        for axis in np.argsort(-np.abs(delta)):
            while p[axis]!=target[axis]:
                p[axis]+=1 if target[axis]>p[axis] else -1
                yield tuple(p)


def _profile(l,w,struct_tree,struct_z):
    line=w['line']
    vertices=np.asarray(line.coords)
    node_stations=np.r_[0,np.cumsum(np.linalg.norm(np.diff(vertices,axis=0),axis=1))]
    stations=np.unique(np.r_[np.linspace(0,line.length,max(2,math.ceil(line.length)+1)),node_stations])
    xy=np.array([line.interpolate(s).coords[0] for s in stations]);rr=np.floor(l.n1-xy[:,1]).astype(int);cc=np.floor(xy[:,0]-l.e0).astype(int)
    inside=(rr>=0)&(rr<l.height)&(cc>=0)&(cc<l.width)
    r,c=np.clip(rr,0,l.height-1),np.clip(cc,0,l.width-1)
    style=STYLES[w['ride']]
    try:layer=int(w['tags'].get('layer','0'))
    except ValueError:layer=0
    ground=ndi.gaussian_filter1d(l.dtm[r,c].astype(float),3)
    # Relative layer ordering is a heuristic prior until a crossing is constrained.
    prior=ground+max(4.5,style['clearance']+(0 if w['ride']=='monorail' else 3*layer))
    observed=np.full(len(xy),np.nan)
    if struct_tree is not None:
        distance,index=struct_tree.query(xy)
        valid=(distance<=2.25)&inside&(struct_z[index]>ground+style['clearance']-1)&(struct_z[index]<ground+55)
        observed[valid]=struct_z[index[valid]]
    weight=np.isfinite(observed).astype(float)
    smooth_weight=ndi.gaussian_filter1d(weight,5)
    observed_mean=ndi.gaussian_filter1d(np.nan_to_num(observed),5)/np.maximum(smooth_weight,1e-6)
    strength=np.minimum(.85,smooth_weight)
    height=prior*(1-strength)+observed_mean*strength
    minimum=ground+style['clearance']
    upper=np.full(len(xy),np.inf)
    is_tunnel=w['tags'].get('tunnel')=='yes'
    covered=w['tags'].get('covered')=='yes'
    # Explicit mapped underpasses may go below a bridge, never merge with it.
    bridge=l.bridge[r,c]>-32768
    if is_tunnel and bridge.any():
        upper[bridge]=l.bridge[r[bridge],c[bridge]]-l.offset-1
        minimum[bridge]=upper[bridge]-1
    # Fit the complete three-cell train corridor under station roofs, including
    # roof edges beside a centreline. Generic station floors are estimates;
    # where they leave insufficient room, carve only the mapped track passage.
    building=(l.ride_near_roof[r,c]<32000)&inside
    under_building=np.full(len(xy),covered or is_tunnel,dtype=bool)
    if not(covered or is_tunnel):
        for node,s in zip(w['nodes'],node_stations):
            if node in l.ride_station_nodes:under_building|=abs(stations-s)<2
    above_building=building&~under_building
    building &= under_building
    station_cuts=0
    if building.any():
        floor_y=l.ride_near_floor[r[building],c[building]]
        roof_y=l.ride_near_roof[r[building],c[building]]
        min_y=floor_y+(5 if style['inverted'] else 0)
        cap_y=roof_y-(1 if style['inverted'] else 4 if w['ride']=='monorail' else 5)
        station_cuts=int((min_y>cap_y).sum())
        min_y=np.minimum(min_y,cap_y)
        minimum[building]=min_y-l.offset
        upper[building]=cap_y-l.offset+.49
        height[building]=minimum[building]
    if above_building.any():
        # An independently crossing upper track is above a roof, not inside
        # the lower station. Preserve the roof and the suspended-train space.
        roof_y=l.ride_near_roof[r[above_building],c[above_building]]
        minimum[above_building]=roof_y-l.offset+(5 if style['inverted'] else 1)
        height[above_building]=np.maximum(height[above_building],minimum[above_building])
    height=np.minimum(np.maximum(height,minimum),upper)
    return {**w,'s':stations,'xy':xy,'height':height,'minimum':minimum,'upper':upper,
            'inside':inside,'layer':layer,'node_stations':node_stations,'station_floor_cut_samples':station_cuts,'candidate_samples':int(np.isfinite(observed).sum())}


def crossing_constraints(ways):
    constraints=[]
    for a in range(len(ways)):
        for b in range(a+1,len(ways)):
            x,y=ways[a],ways[b]
            if not x['line'].intersects(y['line']):continue
            inter=x['line'].intersection(y['line'])
            points=[inter] if inter.geom_type=='Point' else list(inter.geoms) if inter.geom_type=='MultiPoint' else []
            shared=set(x['nodes'])&set(y['nodes'])
            for p in points:
                # Only shared endpoint identities establish a topological joint.
                if shared and any(p.distance(Point(x['line'].coords[x['nodes'].index(node)]))<.1 for node in shared):continue
                ix=int(np.argmin(abs(x['s']-x['line'].project(p))));iy=int(np.argmin(abs(y['s']-y['line'].project(p))))
                rankx=(x['layer'],x['ride']=='monorail',int(x['id']));ranky=(y['layer'],y['ride']=='monorail',int(y['id']))
                upper,lower=(a,b) if rankx>ranky else (b,a)
                iu,il=(ix,iy) if upper==a else (iy,ix)
                constraints.append({'upper':upper,'lower':lower,'iu':iu,'il':il,'gap':6.,
                    'point_bng':[p.x,p.y],'ordering':'OSM relative layer' if x['layer']!=y['layer'] else 'provisional ordering of distinct passes'})
    return constraints


def resolve_profiles(ways,constraints):
    endpoints=defaultdict(list)
    for i,w in enumerate(ways):
        for node,s in zip(w['nodes'],w['node_stations']):
            endpoints[node].append((i,int(np.argmin(abs(w['s']-s)))))
    for _ in range(160):
        for group in endpoints.values():
            if len(group)<2:continue
            lo=max(ways[i]['minimum'][j] for i,j in group)
            target=max(lo,float(np.mean([ways[i]['height'][j] for i,j in group])))
            for i,j in group:
                w=ways[i];delta=target-w['height'][j]
                taper=np.maximum(0,1-abs(w['s']-w['s'][j])/15)
                w['height']+=delta*taper;w['height'][j]=target
        maximum=0
        for con in constraints:
            u,d=ways[con['upper']],ways[con['lower']];iu,il=con['iu'],con['il']
            need=d['height'][il]+con['gap']-u['height'][iu]
            if need>.02:
                width=45 if u['ride']=='monorail' else 15
                taper=np.exp(-.5*((u['s']-u['s'][iu])/width)**2)
                # Crossing/node topology is explicit; the generic station-floor
                # estimates are a soft prior. Roof cells themselves remain
                # immutable and conflicting new rail cells are withheld.
                u['height']+=need*taper
                maximum=max(maximum,need)
        if maximum<.02:break
    # Reconcile endpoints once more; any remaining crossing is reported/gated.
    joins=[]
    for node,group in endpoints.items():
        if len(group)>1:joins.append(max(ways[i]['height'][j] for i,j in group)-min(ways[i]['height'][j] for i,j in group))
    return max(joins,default=0.)


def build_rides(scene,requested):
    l=scene.l
    raw=mapped_ways(l.work/'inputs/osm/osm.xml',l.project,requested)
    scope=(l.e0,l.n0,l.e1,l.n1)
    raw=[w for w in raw if not(w['line'].bounds[2]<scope[0] or w['line'].bounds[0]>scope[2] or w['line'].bounds[3]<scope[1] or w['line'].bounds[1]>scope[3])]
    # Source class-6 observations, excluding actual building footprints and trees.
    structural=np.isfinite(l.cloud['roof'])&~ndi.binary_dilation(l.footprints,iterations=2)&(l.cloud['roof']>l.dtm+3)
    rr,cc=np.nonzero(structural)
    tree=cKDTree(np.column_stack([l.e0+cc+.5,l.n1-rr-.5])) if len(rr) else None
    heights=l.cloud['roof'][rr,cc]
    roof_y=np.where(l.roof_half%2,l.roof_half//2,l.roof_half//2-1)
    l.ride_near_roof=ndi.minimum_filter(np.where(l.roof_half>-32768,roof_y,32767),size=3)
    l.ride_near_floor=ndi.maximum_filter(l.building_floor,size=3)
    l.ride_station_nodes={node for w in raw if w['tags'].get('covered')=='yes' for node in w['nodes']}
    ways=[_profile(l,w,tree,heights) for w in raw]
    constraints=crossing_constraints(ways);join_error=resolve_profiles(ways,constraints)
    minimum_gap=min((ways[c['upper']]['height'][c['iu']]-ways[c['lower']]['height'][c['il']] for c in constraints),default=6.)
    if minimum_gap<5.8 or join_error>.25:raise ValueError(f'Ride layer crossing/endpoint profile constraints remain unresolved: gap={minimum_gap:.3f}, join={join_error:.3f}, constraints={len(constraints)}')
    rail={};byride=defaultdict(set);support_count=Counter();support_skipped=Counter();covered_roof_conflicts=0
    for w in ways:
        style=STYLES[w['ride']];role=w['ride']+'-track'
        xyz=np.column_stack([w['xy'][:,0]-l.e0,w['height']+l.offset,l.n0-w['xy'][:,1]])
        integer=np.floor(xyz).astype(int)
        for i,(a,b) in enumerate(zip(integer,integer[1:])):
            if not(w['inside'][i] or w['inside'][i+1]):continue
            for x,y,z in grid_segment(a,b):
                if not(0<=x<l.width and -l.height<=z<0):continue
                rail[(x,y,z)]=(style['rail'],role);byride[w['ride']].add((x,y,z))
        # Cross ties at known centreline samples; trains ride above/below by type.
        for i in range(0,len(integer),3):
            if not w['inside'][i]:continue
            a=w['xy'][max(0,i-1)];b=w['xy'][min(len(integer)-1,i+1)];v=b-a
            if np.linalg.norm(v)<.01:continue
            normal=np.array([-v[1],v[0]])/np.linalg.norm(v)
            x,y,z=integer[i]
            if w['ride']!='monorail':
                for side in (-1,1):
                    p=(int(round(x+side*normal[0])),int(y),int(round(z-side*normal[1])))
                    rail[p]=(style['rail'],role);byride[w['ride']].add(p)
        # Exclude misclassified foliage in the actual 3 m track/guideway corridor.
        r,c=scene.cells(w['line'].buffer(1.6));l.protected[r,c]=True
        for i,p in enumerate(integer):
            if not w['inside'][i]:continue
            x,y,z=map(int,p)
            below,above=(4,0) if style['inverted'] else (0,3 if w['ride']=='monorail' else 4)
            for dx in (-1,0,1):
                for dz in (-1,0,1):
                    r=z+dz+l.height;c=x+dx
                    if not(0<=r<l.height and 0<=c<l.width):continue
                    half=int(l.roof_half[r,c]);roof_y=half//2 if half%2 else half//2-1
                    for level in range(y-below,y+above+1):
                        if level==y:continue
                        if half>-32768 and level==roof_y:covered_roof_conflicts+=1;continue
                        scene.clearance(x+dx,level,z+dz)
    # Rail geometry has priority over its own discretised swept-air envelope.
    scene.air.difference_update(rail)
    for p in list(scene.blocks):
        if p in scene.air:
            del scene.blocks[p]
            for cells in scene.roles.values():cells.discard(p)
    withheld_rail=Counter()
    for p,(mat,role) in rail.items():
        if not scene.add(*p,mat,role,respect_air=False):withheld_rail[role]+=1
    for w in ways:
        style=STYLES[w['ride']];stride=20 if w['ride']=='monorail' else 14
        for i in range(stride//2,len(w['s']),stride):
            if not w['inside'][i]:continue
            e,n=w['xy'][i];x,z=math.floor(e-l.e0),math.floor(l.n0-n);y=math.floor(w['height'][i]+l.offset)
            r=z+l.height
            if not(0<=x<l.width and 0<=r<l.height):continue
            v=w['xy'][min(i+1,len(w['s'])-1)]-w['xy'][max(0,i-1)]
            if np.linalg.norm(v)<.1:continue
            normal=np.array([-v[1],v[0]])/np.linalg.norm(v)
            proposed=set()
            if style['inverted']:
                feet=[]
                for side in (-1,1):
                    fx=int(round(x+side*3*normal[0]));fz=int(round(z-side*3*normal[1]));fr=fz+l.height
                    if not(0<=fx<l.width and 0<=fr<l.height):continue
                    feet.append((fx,fz))
                    for level in range(int(l.ground[fr,fx])+1,y+3):proposed.add((fx,level,fz))
                if len(feet)==2:
                    for p in grid_segment((feet[0][0],y+2,feet[0][1]),(feet[1][0],y+2,feet[1][1])):proposed.add(p)
                    proposed.add((x,y+1,z))
            else:
                for level in range(int(l.ground[r,x])+1,y):proposed.add((x,level,z))
            if any(p in scene.air or p in scene.old_air or p in rail or p in scene.old_solid for p in proposed):
                support_skipped[w['ride']]+=1;continue
            for p in proposed:
                support_count[w['ride']]+=scene.add(*p,style['support'],w['ride']+'-supports')
    agreements=[]
    for refkey,label,ride in [('galactica','roller_coaster_track','Galactica'),('galactica','monorail','monorail'),
                              ('towers','monorail','monorail'),('smiler','roller_coaster_track','The Smiler')]:
        if refkey not in scene.references:continue
        points=[p['bng_en'] for p in scene.references[refkey][1]['review_points'] if p['label']==label]
        samples=np.concatenate([w['xy'] for w in ways if w['ride']==ride])
        if points and len(samples):
            distance,_=cKDTree(samples).query(points)
            agreements.append({'reference':refkey,'role':label,'ride':ride,'guide_points':len(points),
                'distance_median_p95_m':np.percentile(distance,[50,95]).tolist(),'geometry_snapped_to_ink':False})
    scene.records.append({'id':'mapped-rides-and-monorail','role':'native_track_and_guideway_geometry',
        'rides':{ride:{'ways':sum(w['ride']==ride for w in ways),'mapped_length_m':float(sum(w['line'].length for w in ways if w['ride']==ride)),
            'rail_cells':len(scene.roles[ride+'-track']),'proposed_rail_cells':len(byride[ride]),
            'withheld_rail_cells':withheld_rail[ride+'-track'],
            'support_cells':len(scene.roles[ride+'-supports']),'withheld_support_bents':support_skipped[ride],
            'structural_candidate_samples':sum(w['candidate_samples'] for w in ways if w['ride']==ride)} for ride in requested},
        'ways':[{'id':w['id'],'ride':w['ride'],'node_endpoints':[w['nodes'][0],w['nodes'][-1]],'tags':w['tags'],
                 'height_odn_min_max_m':[float(w['height'].min()),float(w['height'].max())]} for w in ways],
        'crossings':len(constraints),'minimum_crossing_gap_m':float(minimum_gap),'maximum_shared_node_height_error_m':float(join_error),
        'crossing_order':[{'upper_way':ways[c['upper']]['id'],'lower_way':ways[c['lower']]['id'],'ordering':c['ordering'],'bng_en':c['point_bng']} for c in constraints],
        'guide_agreement':agreements,'roof_air_conflicts_left_solid':covered_roof_conflicts,
        'profile_status':'Provisional inferred profile: class-6 candidates outside buildings, terrain-clearance prior, explicit relative crossing constraints. Conflicting generic station-roof cells stay intact and new rail cells there are withheld.',
        'station_floor_cut_samples':sum(w['station_floor_cut_samples'] for w in ways),
        'monorail_scope':'Main operating loop; depot yard/spur ways withheld from this layout draft',
        'vegetation_used_as_height_truth':False,'inversions_banking_or_trains_reconstructed':False,
        'support_locations_status':'Estimated bents; collision checks exclude all running air, other rail cells and retained structures',
        'xy_crossings_join_networks':False,'native_route_operability_claimed':False})
