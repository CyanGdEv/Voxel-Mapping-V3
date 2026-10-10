"""Deterministic bounded plane patches from native XYZ; never surveyed edges."""
import hashlib
import numpy as np
from shapely.geometry import MultiPoint, LineString, mapping
from .roof_candidates import components


def plane_patches(xyz, point_indices, *, tolerance_m=.12, trials=768, min_points=30,
                  max_planes=12, seed=19, connectivity_radius_m=1.5):
    xyz=np.asarray(xyz,dtype=float);indices=np.asarray(point_indices)
    if xyz.ndim!=2 or xyz.shape[1]!=3 or len(xyz)>20_000 or not np.isfinite(xyz).all():
        raise ValueError('Finite bounded native XYZ required')
    if indices.shape!=(len(xyz),) or indices.dtype.kind not in 'iu' or np.any(indices<0) or len(np.unique(indices))!=len(indices):
        raise ValueError('Unique nonnegative original point indices required')
    if not np.isfinite(tolerance_m) or not .01<=tolerance_m<=.5 or type(trials)!=int or not 1<=trials<=4096:
        raise ValueError('Bounded plane tolerance and trial count required')
    if type(min_points)!=int or min_points<6 or type(max_planes)!=int or not 1<=max_planes<=24:
        raise ValueError('Bounded minimum support and plane count required')
    if not np.isfinite(connectivity_radius_m) or not .1<=connectivity_radius_m<=5:
        raise ValueError('Bounded patch connectivity radius required')
    if len(xyz)*trials*max_planes>200_000_000:
        raise ValueError('Plane comparison budget exceeded')
    origin=xyz[:,:2].mean(axis=0) if len(xyz) else np.zeros(2)
    design=np.column_stack((xyz[:,:2]-origin,np.ones(len(xyz))))
    remaining=np.arange(len(xyz));rng=np.random.default_rng(seed);models=[]
    for _ in range(max_planes):
        if len(remaining)<min_points:break
        best=None
        for _ in range(trials):
            chosen=rng.choice(remaining,3,replace=False);a=design[chosen]
            if abs(np.linalg.det(a))<.3:continue  # twice sampled XY triangle area
            coeff=np.linalg.solve(a,xyz[chosen,2])
            if np.linalg.norm(coeff[:2])>np.tan(np.deg2rad(75)):continue
            residual=np.abs(design[remaining]@coeff-xyz[remaining,2]);inside=remaining[residual<=tolerance_m]
            if len(inside)<min_points:continue
            score=(len(inside),-float(np.median(residual[residual<=tolerance_m])))
            if best is None or score>best[0]:best=(score,inside)
        if best is None:break
        inside=best[1]
        for _ in range(3):
            coeff,_,rank,_=np.linalg.lstsq(design[inside],xyz[inside,2],rcond=None)
            if rank!=3:break
            updated=remaining[np.abs(design[remaining]@coeff-xyz[remaining,2])<=tolerance_m]
            if len(updated)<min_points:break
            if np.array_equal(updated,inside):break
            inside=updated
        if rank!=3 or len(inside)<min_points:break
        coeff,_,rank,_=np.linalg.lstsq(design[inside],xyz[inside,2],rcond=None)
        if rank!=3 or np.linalg.norm(coeff[:2])>np.tan(np.deg2rad(75)):break
        models.append(coeff);remaining=remaining[~np.isin(remaining,inside)]
    if not models:
        return {'status':'insufficient_plane_support','origin_bng_m':origin.tolist(),'patches':[],
                'creases':[],'unassigned_point_indices':indices.tolist(),'ambiguous_point_indices':[],
                'vertical_residual_tolerance_m':tolerance_m,'retained_plane_models':0,'plane_budget_reached':False,'plane_models':[],
                'physical_edges_verified':False,'native_edge_uncertainty_m':None}
    models=np.asarray(models)
    distances=np.abs(design@models.T-xyz[:,2,None]);eligible=distances<=tolerance_m
    # Points fitting multiple retained planes are excluded from patch boundaries.
    # This deliberately leaves unresolved intersections rather than selecting
    # whichever plane happened to be peeled first.
    ambiguous=eligible.sum(axis=1)>1;assignments=np.argmin(distances,axis=1)
    patches=[];supported=np.zeros(len(xyz),dtype=bool)
    for model_number,coeff in enumerate(models):
        ids=np.flatnonzero((assignments==model_number)&(eligible.sum(axis=1)==1))
        groups,_=components(xyz[ids],connectivity_radius_m,5)
        for group in groups:
            members=ids[group]
            if len(members)<min_points:continue
            hull=MultiPoint(xyz[members,:2]).convex_hull
            if hull.geom_type!='Polygon' or hull.area<5:continue
            residual=design[members]@coeff-xyz[members,2]
            native=indices[members];supported[members]=True
            patches.append({'patch_id':hashlib.sha256(np.asarray(native,dtype='<u8').tobytes()).hexdigest(),
                'model_index':model_number,'original_crop_point_indices':native.tolist(),
                'point_count':len(members),'slope_xy':coeff[:2].tolist(),'height_at_origin_odn_m':float(coeff[2]),
                'slope_degrees':float(np.rad2deg(np.arctan(np.linalg.norm(coeff[:2])))),
                'support_geometry':mapping(hull),'residual_vertical_m':{'median_absolute':float(np.median(np.abs(residual))),
                    'p95_absolute':float(np.quantile(np.abs(residual),.95))},
                'physical_roof_identity_verified':False})
    creases=[]
    for i,a in enumerate(patches):
        pa=MultiPoint(xyz[np.isin(indices,a['original_crop_point_indices']),:2]).convex_hull
        for j,b in enumerate(patches[i+1:],i+1):
            if a['model_index']==b['model_index']:continue
            pb=MultiPoint(xyz[np.isin(indices,b['original_crop_point_indices']),:2]).convex_hull
            ca,cb=models[a['model_index']],models[b['model_index']];normal=ca[:2]-cb[:2];length=np.linalg.norm(normal)
            if length<.05:continue
            local=-(ca[2]-cb[2])*normal/(length*length);centre=origin+local;direction=np.array([-normal[1],normal[0]])/length
            # 0.75 m is a contact search margin, not a positional error bound.
            line=LineString([centre-direction*100,centre+direction*100]).intersection(pa.buffer(.75)).intersection(pb.buffer(.75))
            if line.is_empty or line.length<1:continue
            geom_parts=[line] if line.geom_type=='LineString' else list(line.geoms) if line.geom_type=='MultiLineString' else []
            for segment in geom_parts:
                if segment.length<1:continue
                xy=np.asarray(segment.coords);heights=(xy-origin)@ca[:2]+ca[2]
                signs=[]
                for poly,coeff in [(pa,ca),(pb,cb)]:
                    centroid=np.asarray(poly.centroid.coords[0])-origin
                    projected=centroid-normal*((centroid-local)@normal)/(length*length)
                    signs.append(float((centroid-projected)@coeff[:2]))
                kind='ridge_like' if max(signs)<0 else 'valley_like' if min(signs)>0 else 'unclassified_crease'
                creases.append({'patch_ids':[a['patch_id'],b['patch_id']],'type':kind,
                    'candidate_xyz_odn_m':np.column_stack((xy,heights)).tolist(),'contact_search_margin_m':.75,
                    'physical_edge_verified':False})
    return {'status':'native_plane_patch_hypotheses','origin_bng_m':origin.tolist(),'vertical_residual_tolerance_m':tolerance_m,
            'ransac_trials_per_plane':trials,'rng_seed':seed,'retained_plane_models':len(models),
            'plane_models':[{'model_index':i,'slope_xy':c[:2].tolist(),'height_at_origin_odn_m':float(c[2])} for i,c in enumerate(models)],
            'plane_budget_reached':len(models)==max_planes,'patches':patches,'creases':creases,
            'unassigned_point_indices':indices[~supported&~ambiguous].tolist(),
            'ambiguous_point_indices':indices[ambiguous].tolist(),
            'physical_edges_verified':False,'native_edge_uncertainty_m':None,
            'limitations':['Plane residual is vertical fitting error, not survey positional accuracy.',
                           'Convex support envelopes can bridge holes; they are not surveyed eaves.',
                           'Plane intersections and contact margins do not establish physical ridges.',
                           'Model order and tolerance can change partitions; independent review remains required.']}
