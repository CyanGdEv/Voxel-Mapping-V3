"""Named-label containment checks, distinct from surveyed landmark verification."""
import re
import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint, Point, shape
from shapely.ops import transform


def normalise_name(name):
    return re.sub(r'^the\s+','',name.strip(),flags=re.I).casefold()


def inspect_named_landmarks(controls, named_labels, features, metric_crs_hypothesis):
    report={'status':'no_comparable_landmarks','checks':[], 'registration_verified':False,
            'independent_accuracy':'not_verified','world_geometry_additions':0,
            'crs_hypothesis':str(metric_crs_hypothesis),
            'limitations':['Named text origins are not surveyed physical corners',
                           'Containment under an assumed CRS does not validate absolute alignment',
                           'Reference source independence and positional uncertainty remain unknown']}
    if len(controls)>64 or len(named_labels)>64 or len(features)>5000:
        return {**report,'status':'landmark_budget_exceeded'}
    array=np.asarray(controls,dtype=float)
    if array.ndim!=2 or array.shape[1]!=4 or len(array)<4 or not np.all(np.isfinite(array)):
        return {**report,'status':'insufficient_landmark_transform'}
    pixels=array[:,:2];centre=pixels.mean(axis=0)
    design=np.column_stack((pixels-centre,np.ones(len(pixels))))
    if np.linalg.matrix_rank(design)!=3:return {**report,'status':'degenerate_landmark_transform'}
    fit=np.linalg.lstsq(design,array[:,2:],rcond=None)[0]
    domain=MultiPoint(pixels).convex_hull
    projector=Transformer.from_crs(4326,metric_crs_hypothesis,always_xy=True)
    references={}
    for feature in features:
        props=feature.get('properties',{});name=props.get('name')
        if props.get('kind')=='building' and props.get('source_id')=='osm' and isinstance(name,str):
            references.setdefault(normalise_name(name),[]).append(feature)
    for label in named_labels:
        candidates=references.get(normalise_name(label['text']),[])
        if len(candidates)!=1:continue
        origin=np.asarray(label['origin'],dtype=float)
        if origin.shape!=(2,) or not np.all(np.isfinite(origin)):continue
        entry={'reference_feature_id':candidates[0].get('id'),'source_id':'osm',
               'reference_used_in_fit':False,'reference_uncertainty':'not_provided'}
        if not domain.covers(Point(origin)):
            entry['status']='label_outside_control_hull'
        else:
            geometry=shape(candidates[0]['geometry'])
            if (geometry.geom_type not in ('Polygon','MultiPolygon') or not geometry.is_valid or geometry.is_empty
                    or not (-180<=geometry.bounds[0]<=geometry.bounds[2]<=180 and
                            -90<=geometry.bounds[1]<=geometry.bounds[3]<=90)):
                entry['status']='invalid_reference_footprint'
            else:
                reference=transform(projector.transform,geometry)
                point=Point(np.r_[origin-centre,1]@fit)
                entry['status']='label_inside_reference_footprint' if reference.covers(point) else 'label_outside_reference_footprint'
                entry['distance_to_footprint_coordinate_units']=float(reference.distance(point))
        report['checks'].append(entry)
    if report['checks']:report['status']='named_label_consistency_only'
    return report
