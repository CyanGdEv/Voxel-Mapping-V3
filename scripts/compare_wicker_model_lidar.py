"""Compare proposed roof/canopy hypotheses with native dated LiDAR; no registration acceptance."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import laspy,numpy as np
from shapely.geometry import Polygon,MultiPoint,Point,shape,mapping
from shapely.affinity import affine_transform
from voxel_mapper.roof_plan_review import fixed_scale_edges
from voxel_mapper.point_cloud import is_bng


def compare(model_path,cloud_path,roof_report,crop_receipt):
    def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    model=json.loads(Path(model_path).read_text());report=json.loads(Path(roof_report).read_text());crop=json.loads(Path(crop_receipt).read_text())
    if digest(cloud_path)!=crop['sha256'] or report['input_sha256']['cloud']!=crop['sha256'] or report['input_sha256']['crop_receipt']!=digest(crop_receipt):raise ValueError('Cloud evidence binding mismatch')
    if any(report['survey'][k]!=crop['survey'][k] for k in ['survey_id','survey_start','survey_end']):raise ValueError('Survey mismatch')
    cloud=laspy.read(cloud_path)
    if len(cloud)>15_000_000 or len(cloud)!=crop['retained_points'] or not is_bng(cloud.header.parse_crs()):raise ValueError('Bounded native BNG crop required')
    vertices=np.array(model['roof_mesh']['vertices']);main=Polygon(vertices[[0,1,5,4],:2]);projection=Polygon(np.array(model['projection_mesh']['vertices'])[:4,:2])
    factor=100*.0254/72;local_pdf=Polygon(np.array(main.exterior.coords)/factor)
    eave=vertices[0,2];ridge=vertices[2,2];halfwidth=max(abs(vertices[:,1]))
    canopy=model['projection_mesh']['vertices'];rear_x=canopy[0][0];front_x=canopy[2][0];rear_z=canopy[0][2];front_z=canopy[2][2]
    rows=[]
    for envelope in report['distinct_observed_envelopes']:
        candidate=next(c for c in report['candidates'] if c.get('membership_sha256')==envelope['membership_sha256'])
        raw=candidate['original_crop_point_indices']
        if any(type(i)!=int for i in raw) or len(raw)!=len(set(raw)):raise ValueError('Distinct integer original indices required')
        ids=np.array(raw,dtype=np.int64)
        if not len(ids) or len(ids)>20000 or ids.min()<0 or ids.max()>=len(cloud):raise ValueError('Bounded indices required')
        if hashlib.sha256(np.asarray(ids,dtype='<u8').tobytes()).hexdigest()!=envelope['membership_sha256']:raise ValueError('Membership hash mismatch')
        pts=cloud[ids]
        if not ((np.array(pts.classification)==6)&(~np.array(pts.synthetic,dtype=bool))&(~np.array(pts.withheld,dtype=bool))).all():raise ValueError('Eligible native building returns required')
        xyz=np.column_stack([pts.x,pts.y,pts.z]);native=MultiPoint(xyz[:,:2]).convex_hull
        if not native.equals_exact(shape(envelope['geometry']),0,normalize=True):raise ValueError('Native envelope mismatch')
        fits=fixed_scale_edges(local_pdf,native,100);hypotheses=[]
        for fit in fits['equivalent_orientations']:
            matrix=np.array(fit['matrix'])/factor;translation=np.array(fit['translation_m']);local=(xyz[:,:2]-translation)@np.linalg.inv(matrix).T
            main_ids=[];canopy_ids=[];outside=[];offsets=[];main_offsets=[];canopy_offsets=[]
            for index,point,z in zip(ids,local,xyz[:,2]):
                if main.covers(Point(point)):
                    height=ridge-(ridge-eave)*abs(point[1])/halfwidth;main_ids.append(int(index));main_offsets.append(float(z-height))
                elif projection.covers(Point(point)):
                    t=(point[0]-rear_x)/(front_x-rear_x);height=rear_z+t*(front_z-rear_z);canopy_ids.append(int(index));canopy_offsets.append(float(z-height))
                else:outside.append(int(index));continue
                offsets.append(float(z-height))
            if not offsets:raise ValueError('No profile comparison returns')
            off=np.array(offsets);median=float(np.median(main_offsets))
            canopy_residuals=np.array(canopy_offsets)-median
            canopy_summary=None if not len(canopy_residuals) else {'count':len(canopy_residuals),'median_m':float(np.median(canopy_residuals)),'p05_m':float(np.quantile(canopy_residuals,.05)),'p95_m':float(np.quantile(canopy_residuals,.95))}
            hypotheses.append({'rotation_degrees':fit['rotation_degrees'],'local_metres_to_bng_matrix':matrix.tolist(),'translation_bng_m':translation.tolist(),
                'placed_main_roof_geometry':fit['placed_geometry'],'placed_canopy_geometry':mapping(affine_transform(projection,[*matrix[0],*matrix[1],*translation])),
                'main_roof_iou':fit['intersection_over_union'],'main_roof_boundary_hausdorff_m':fit['boundary_hausdorff_m'],
                'main_roof_return_indices':main_ids,'canopy_only_return_indices':canopy_ids,'outside_combined_roof_return_indices':outside,
                'implied_floor_offset_odn_m':{'median':median,'p05':float(np.quantile(off,.05)),'p95':float(np.quantile(off,.95))},
                'vertical_residual_after_self_fit_floor_m':{'median_abs':float(np.median(abs(off-median))),'p95_abs':float(np.quantile(abs(off-median),.95))},
                'floor_fit_uses_main_roof_returns_only':True,'canopy_vertical_residual_using_main_roof_floor_m':canopy_summary,
                'median_offset_minus_proposed_182_50_m':median-182.5,'floor_datum_verified':False,'registration_verified':False})
        rows.append({'membership_sha256':envelope['membership_sha256'],'point_count':len(ids),'native_envelope_reproduced':True,
                     'observed_envelope_geometry':mapping(native),'boundary_review_flags':fits['review_flags'],'hypotheses':hypotheses})
    return {'status':'proposed_roof_lidar_hypotheses_only','survey':crop['survey'],'model_main_roof_area_metres_squared':main.area,
            'model_canopy_only_area_metres_squared':projection.difference(main).area,'envelopes':rows,
            'input_sha256':{str(p):digest(p) for p in [model_path,cloud_path,roof_report,crop_receipt]},
            'limitations':['Horizontal transform is boundary self-fit, not independent registration.','Vertical floor offset is self-fit to the same returns; it does not establish an ODN floor datum.','2016 proposed geometry and 2022 returns can differ physically.','Canopy-only return counts do not identify a physical canopy or prove an orientation.','Convex envelopes and sparse return coverage do not supply independently surveyed roof corners.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['model','cloud','roof-report','crop-receipt','output']:p.add_argument('--'+k,required=True)
    a=p.parse_args();r=compare(a.model,a.cloud,a.roof_report,a.crop_receipt);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps([{'points':e['point_count'],'hypotheses':[{'angle':h['rotation_degrees'],'iou':h['main_roof_iou'],'canopy_returns':len(h['canopy_only_return_indices']),'floor_offset':h['implied_floor_offset_odn_m']['median']} for h in e['hypotheses']]} for e in r['envelopes']]))

if __name__=='__main__':main()
