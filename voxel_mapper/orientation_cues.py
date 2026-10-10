"""Inspect asymmetric context without promoting it to physical registration."""
import numpy as np
from shapely import points,distance
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,LineString,mapping


def northing_direction(labels,orientations):
    """Rank hypotheses by increasing labelled local northing, not position checks."""
    if not 2<=len(labels)<=32 or len({r['northing'] for r in labels})!=len(labels):raise ValueError('Distinct bounded northing labels required')
    rows=sorted(labels,key=lambda r:r['northing'])
    coords=np.asarray([r['native_centre'] for r in rows],float);values=np.asarray([r['northing'] for r in rows],float)
    if coords.shape!=(len(rows),2) or not np.isfinite(coords).all() or not np.isfinite(values).all():raise ValueError('Finite native northing labels required')
    delta=coords[-1]-coords[0];length=np.linalg.norm(delta)
    if length<=0:raise ValueError('Northing labels need native spatial extent')
    direction=delta/length;results=[]
    for f in orientations:
        m=np.asarray(f['matrix'],float)
        if m.shape!=(2,2) or not np.isfinite(m).all():raise ValueError('Finite hypothesis matrix required')
        mapped=m@direction;n=np.linalg.norm(mapped)
        if n<=0:raise ValueError('Nondegenerate mapped north direction required')
        results.append({'rotation_degrees':f['rotation_degrees'],'mapped_increasing_local_north_unit_vector':(mapped/n).tolist(),
            'north_half_plane_consistent':bool(mapped[1]>0),
            'physical_registration_verified':False})
    return {'status':'local_north_direction_consistency_only','source_labels':rows,
        'increasing_local_north_native_vector':direction.tolist(),
        'label_interval_metres_per_pdf_point':float((values[-1]-values[0])/length),
        'orientation_comparisons':results,'north_consistent_hypothesis_count':sum(r['north_half_plane_consistent'] for r in results),
        'accepted_checkpoints':0,'limitations':['Local northing direction constrains orientation, not absolute placement',
            'Exact relationship of the local site grid to BNG/true north remains unverified',
            'Label centres are document context, not physical attachment points']}


def compare_cues(outline,projection,interior_line,roof_xyz,lower_envelope,orientations):
    xyz=np.asarray(roof_xyz,dtype=float)
    if xyz.ndim!=2 or xyz.shape[1]!=3 or not 3<=len(xyz)<=20_000 or not np.isfinite(xyz).all():raise ValueError('Finite bounded roof returns required')
    for g,kind in ((outline,Polygon),(projection,Polygon),(interior_line,LineString),(lower_envelope,Polygon)):
        if not isinstance(g,kind) or g.is_empty or not g.is_valid or not np.isfinite(g.bounds).all():raise ValueError('Valid finite cue geometry required')
    if not 1<=len(orientations)<=16:raise ValueError('Bounded orientation hypotheses required')
    rows=[]
    for f in orientations:
        m=np.asarray(f['matrix'],float);t=np.asarray(f['translation_m'],float)
        if m.shape!=(2,2) or t.shape!=(2,) or not np.isfinite(m).all() or not np.isfinite(t).all() or np.linalg.det(m)<=0:raise ValueError('Finite orientation-preserving hypothesis required')
        coeff=[*m[0],*m[1],*t]
        p=affine_transform(projection,coeff);line=affine_transform(interior_line,coeff)
        bands=[]
        for quantile in (.8,.9,.95):
            z=float(np.quantile(xyz[:,2],quantile));subset=xyz[xyz[:,2]>=z]
            d=distance(points(subset[:,0],subset[:,1]),line)
            bands.append({'height_quantile':quantile,'threshold_z_odn_m':z,'point_count':len(subset),
                'distance_to_interior_line_m':{'median':float(np.median(d)),'p95':float(np.quantile(d,.95)),'max':float(d.max())},
                'physical_ridge_identity_verified':False})
        rows.append({'rotation_degrees':f['rotation_degrees'],'projection_geometry_bng':mapping(p),
            'interior_line_geometry_bng':mapping(line),'projection_to_lower_envelope':{
                'centroid_distance_m':p.centroid.distance(lower_envelope.centroid),
                'intersection_area_m2':p.intersection(lower_envelope).area,
                'projection_area_m2':p.area,'physical_correspondence_verified':False},
            'high_return_line_comparisons':bands})
    # A centred unoriented line cannot label the two ends of a symmetric footprint.
    source_offset=interior_line.interpolate(.5,normalized=True).distance(outline.centroid)
    return {'status':'orientation_cues_unverified','source_interior_line_midpoint_offset_pdf_points':source_offset,
        'orientation_comparisons':rows,'selected_orientation':None,'registration_verified':False,
        'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
        'limitations':['Interior line role and high-return ridge identity are not established',
            'A nearly centred unoriented line cannot by itself distinguish a 180-degree reversal',
            'A nearby lower cluster is not the planned projection solely because it is nearby',
            'These cues reuse the fitted cloud and are not independent checkpoints']}
