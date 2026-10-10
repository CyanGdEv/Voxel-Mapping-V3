"""Extract native plane patches from the retained shared roof component."""
import argparse,base64,hashlib,json,sys,zlib
from pathlib import Path
import laspy,numpy as np
from shapely.geometry import MultiPoint,shape
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.roof_planes import plane_patches


def extract(cloud_path,review_path):
    review=json.loads(Path(review_path).read_text());data=Path(cloud_path).read_bytes()
    if hashlib.sha256(data).hexdigest()!=review['input_sha256']['cloud']:raise ValueError('Pinned expanded cloud required')
    row=next(r for r in review['sweep_results'] if r['hypothesis_index']==0 and r['radius_metres']==1.5 and r['height_step_metres']==.5)
    if not row['station_maintenance_share_component']:raise ValueError('Retained shared component required')
    membership=row['building_comparisons']['station']['membership_sha256']
    component=next(c for c in review['distinct_native_components'] if c['membership_sha256']==membership)
    decoder=zlib.decompressobj();raw=decoder.decompress(base64.b64decode(component['original_expanded_crop_point_indices_zlib_base64'],validate=True),20_000*8+1)
    if len(raw)>20_000*8 or len(raw)%8 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Bounded complete membership encoding required')
    if hashlib.sha256(raw).hexdigest()!=membership:raise ValueError('Native membership checksum mismatch')
    ids=np.frombuffer(raw,dtype='<u8');cloud=laspy.read(cloud_path)
    if len(ids)!=component['point_count'] or len(np.unique(ids))!=len(ids) or ids.max()>=len(cloud):raise ValueError('Native point indices required')
    pts=cloud[ids]
    if not np.all(np.asarray(pts.classification)==6) or np.any(pts.withheld) or np.any(pts.synthetic):raise ValueError('Eligible native building returns required')
    xyz=np.column_stack((pts.x,pts.y,pts.z))
    if not MultiPoint(xyz[:,:2]).convex_hull.equals_exact(shape(component['geometry']),0,normalize=True):raise ValueError('Shared envelope does not reproduce')
    sweeps=[plane_patches(xyz,ids,tolerance_m=t) for t in [.08,.12,.18]]
    return {'status':'unverified_native_roof_planes','input_sha256':{'cloud':review['input_sha256']['cloud'],'review':hashlib.sha256(Path(review_path).read_bytes()).hexdigest()},
            'shared_component_membership_sha256':membership,'input_points':len(ids),'survey':review['survey'],'sweeps':sweeps,
            'planning_outlines_used_to_fit_planes':False,'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['cloud','review','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=extract(a.cloud,a.review);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps([{'tolerance':s['vertical_residual_tolerance_m'],'patches':len(s['patches']),'creases':len(s['creases']),'assigned':sum(p['point_count'] for p in s['patches']),'ambiguous':len(s['ambiguous_point_indices']),'unassigned':len(s['unassigned_point_indices'])} for s in r['sweeps']]))

if __name__=='__main__':main()
