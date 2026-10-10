"""Bounded native-return connectivity diagnostics; no physical wall inference."""
import hashlib
from itertools import product

import numpy as np
from shapely import intersects_xy
from shapely.geometry import MultiPoint,mapping


def components(xyz, radius_m, height_step_m, max_comparisons=2_000_000):
    """Connected XY neighbours with a bounded vertical step, using spatial bins."""
    if not np.isfinite([radius_m,height_step_m]).all() or not 0<radius_m<=5 or not 0<height_step_m<=5:
        raise ValueError('Positive bounded connectivity distances required')
    if xyz.ndim!=2 or xyz.shape[1]!=3 or len(xyz)>20_000 or not np.isfinite(xyz).all():
        raise ValueError('Finite bounded native XYZ array required')
    bins={};parents=list(range(len(xyz)));comparisons=0
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,p in enumerate(xyz):
        cell=tuple(np.floor(p[:2]/radius_m).astype(np.int64))
        for dx,dy in product((-1,0,1),repeat=2):
            neighbours=bins.get((cell[0]+dx,cell[1]+dy),[])
            comparisons+=len(neighbours)
            if comparisons>max_comparisons:raise ValueError('Connectivity comparison budget exceeded')
            if not neighbours:continue
            q=xyz[neighbours]
            close=(np.sum((q[:,:2]-p[:2])**2,axis=1)<=radius_m**2)&(np.abs(q[:,2]-p[2])<=height_step_m)
            for j in np.asarray(neighbours)[close]:
                a,b=root(i),root(int(j))
                if a!=b:parents[max(a,b)]=min(a,b)
        bins.setdefault(cell,[]).append(i)
    groups={}
    for i in range(len(xyz)):groups.setdefault(root(i),[]).append(i)
    return [np.asarray(v,dtype=np.int64) for v in groups.values()],comparisons


def roof_candidates(xyz,point_indices,reference,crop_bounds,
                    radii=(1,1.5,2),height_steps=(.5,1,2)):
    """Sweep components seeded by an outline, without clipping to that outline.

    Convex hulls enclose observed returns; they are candidate envelopes and may
    bridge concavities. Minimum rectangles are estimates, never surveyed corners.
    """
    xyz=np.asarray(xyz,dtype=float);indices=np.asarray(point_indices)
    if indices.shape!=(len(xyz),) or len(set(indices.tolist()))!=len(indices) or indices.dtype.kind not in 'iu' or np.any(indices<0):
        raise ValueError('Unique nonnegative original point indices required')
    if reference.geom_type not in ('Polygon','MultiPolygon') or reference.is_empty or not reference.is_valid:
        raise ValueError('Valid polygon comparison required')
    bounds=np.asarray(crop_bounds,dtype=float)
    if bounds.shape!=(4,) or not np.isfinite(bounds).all() or not (bounds[0]<bounds[2] and bounds[1]<bounds[3]):
        raise ValueError('Finite native crop bounds required')
    if not 1<=len(radii)<=4 or not 1<=len(height_steps)<=4 or len(set(radii))!=len(radii) or len(set(height_steps))!=len(height_steps):
        raise ValueError('Distinct bounded connectivity sweep required')
    # Validate before querying geometry, including the empty-array case.
    components(xyz,radii[0],height_steps[0])
    if len(xyz) and not ((xyz[:,0]>=bounds[0])&(xyz[:,0]<=bounds[2])&(xyz[:,1]>=bounds[1])&(xyz[:,1]<=bounds[3])).all():
        raise ValueError('Returns must lie inside declared native crop bounds')
    seed=intersects_xy(reference,xyz[:,0],xyz[:,1]);rows=[];hulls=[]
    for radius,step in product(radii,height_steps):
        groups,cost=components(xyz,radius,step)
        ranked=sorted(((int(np.count_nonzero(seed[g])),g) for g in groups),key=lambda r:(-r[0],int(r[1][0])))
        row={'radius_m':radius,'height_step_m':step,'comparison_count':cost,'status':'no_seeded_component'}
        if ranked and ranked[0][0]>0:
            hits,g=ranked[0];pts=xyz[g];hull=MultiPoint(pts[:,:2]).convex_hull
            row.update(status='insufficient_2d_support',point_count=len(g),seed_point_count=hits,
                equally_seeded_components=sum(n==hits for n,_ in ranked),
                original_crop_point_indices=indices[g].tolist(),
                membership_sha256=hashlib.sha256(np.asarray(indices[g],dtype='<u8').tobytes()).hexdigest(),
                observed_z_odn_m={'min':float(pts[:,2].min()),'median':float(np.median(pts[:,2])),'max':float(pts[:,2].max())})
            if hull.geom_type=='Polygon':
                hb=hull.bounds;touch=hb[0]-bounds[0]<=radius or hb[1]-bounds[1]<=radius or bounds[2]-hb[2]<=radius or bounds[3]-hb[3]<=radius
                row.update(status='observed_return_envelope',geometry=mapping(hull),area_m2=hull.area,
                    estimated_rectangle=mapping(hull.minimum_rotated_rectangle),
                    crop_edge_within_connectivity_radius=bool(touch),
                    comparison_outline_iou=hull.intersection(reference).area/hull.union(reference).area)
                hulls.append(hull)
        rows.append(row)
    spread=max((a.boundary.hausdorff_distance(b.boundary) for a,b in product(hulls,hulls)),default=None)
    envelopes={}
    for row in rows:
        if row['status']!='observed_return_envelope':continue
        key=row['membership_sha256']
        entry=envelopes.setdefault(key,{'membership_sha256':key,'point_count':row['point_count'],
            'seed_point_count':row['seed_point_count'],'geometry':row['geometry'],
            'observed_z_odn_m':row['observed_z_odn_m'],'parameter_combinations':[]})
        entry['parameter_combinations'].append({'radius_m':row['radius_m'],'height_step_m':row['height_step_m']})
    differences=[];lookup={int(i):xyz[n] for n,i in enumerate(indices)}
    for a,b in product(envelopes,envelopes):
        if a==b:continue
        ar=next(r for r in rows if r.get('membership_sha256')==a)
        br=next(r for r in rows if r.get('membership_sha256')==b)
        ai,bi=set(ar['original_crop_point_indices']),set(br['original_crop_point_indices'])
        if ai < bi:
            added=np.asarray([lookup[i] for i in sorted(bi-ai)])
            differences.append({'smaller_membership_sha256':a,'larger_membership_sha256':b,
                'added_point_count':len(added),'added_z_odn_m':{'min':float(added[:,2].min()),
                    'median':float(np.median(added[:,2])),'max':float(added[:,2].max())},
                'added_physical_identity':'unverified'})
    return {'status':'unverified_roof_envelopes','eligible_class_6_points':len(xyz),
        'comparison_seed_points':int(np.count_nonzero(seed)),'candidates':rows,
        'distinct_observed_envelopes':list(envelopes.values()),'component_expansions':differences,
        'maximum_connectivity_boundary_spread_m':spread,
        'native_edge_uncertainty_m':None,'roof_to_wall_offset_m':None,
        'physical_identity_verified':False,'accepted_controls':0,'accepted_checkpoints':0,
        'world_geometry_additions':0,'limitations':[
            'Connectivity sensitivity is not survey positional error',
            'Classification and outline overlap do not prove physical roof or wall identity',
            'Convex envelopes bridge concavities and do not infer roof interiors',
            'Rectangle estimates are not exact surveyed attachment points']}
