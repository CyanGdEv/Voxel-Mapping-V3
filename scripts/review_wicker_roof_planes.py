"""Compare native plane pairs with frozen plan outlines, without refitting."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union


def review(planes_path,site_path):
    planes=json.loads(Path(planes_path).read_text());site=json.loads(Path(site_path).read_text())
    if hashlib.sha256(Path(site_path).read_bytes()).hexdigest()!=planes['input_sha256']['review']:
        raise ValueError('Exact frozen site comparison required')
    if site['input_sha256']['cloud']!=planes['input_sha256']['cloud']:raise ValueError('Matched native cloud required')
    primary=next(s for s in planes['sweeps'] if s['vertical_residual_tolerance_m']==.12)
    patches={p['patch_id']:p for p in primary['patches']};pairs=[]
    for crease in primary['creases']:
        if crease['type']!='ridge_like':continue
        a,b=[patches[i] for i in crease['patch_ids']];envelope=unary_union([shape(a['support_geometry']),shape(b['support_geometry'])]).convex_hull
        xyz=np.asarray(crease['candidate_xyz_odn_m'])
        pairs.append({'patch_ids':crease['patch_ids'],'points':a['point_count']+b['point_count'],
                      'support_envelope':envelope.__geo_interface__,
                      'candidate_ridge_xyz_odn_m':xyz.tolist(),
                      'candidate_ridge_height_range_odn_m':[float(xyz[:,2].min()),float(xyz[:,2].max())],
                      'convex_pair_envelope_is_not_surveyed_eave':True})
    frozen=site['frozen_hypotheses'][0];buildings=[]
    for name in ['station','maintenance']:
        polygon=shape(frozen['placed_building_geometries'][name]);ranked=[]
        for number,pair in enumerate(pairs):
            native=shape(pair['support_envelope'])
            ranked.append({'pair_index':number,'frozen_outline_iou':native.intersection(polygon).area/native.union(polygon).area,
                           'boundary_hausdorff_metres':native.boundary.hausdorff_distance(polygon.boundary)})
        ranked.sort(key=lambda row:-row['frozen_outline_iou'])
        buildings.append({'planning_label':name,'ranked_native_pair_comparisons':ranked,'physical_identity_verified':False})
    stability=[]
    for patch in primary['patches']:
        members=set(patch['original_crop_point_indices']);comparisons=[]
        for sweep in planes['sweeps']:
            if sweep is primary:continue
            candidates=[]
            for other in sweep['patches']:
                ids=set(other['original_crop_point_indices']);jaccard=len(members&ids)/len(members|ids)
                candidates.append((jaccard,other))
            if not candidates:continue
            score,other=max(candidates,key=lambda row:row[0])
            comparisons.append({'tolerance_metres':sweep['vertical_residual_tolerance_m'],
                'membership_jaccard':score,'matched_patch_id':other['patch_id'],
                'support_boundary_difference_metres':shape(patch['support_geometry']).boundary.hausdorff_distance(shape(other['support_geometry']).boundary),
                'slope_difference_degrees':abs(patch['slope_degrees']-other['slope_degrees'])})
        stability.append({'primary_patch_id':patch['patch_id'],'comparisons':comparisons})
    return {'status':'plane_pair_correspondence_candidates_only','primary_tolerance_metres':.12,
            'input_sha256':{'planes':hashlib.sha256(Path(planes_path).read_bytes()).hexdigest(),'site':planes['input_sha256']['review']},
            'ridge_pairs':pairs,'building_comparisons':buildings,'patch_stability':stability,
            'physical_edges_verified':False,'native_edge_uncertainty_metres':None,
            'limitations':['Plan outlines were not used in plane extraction; subsequent overlap ranking is still a correspondence hypothesis.',
                           'Pair envelopes bridge gaps and do not establish full eave boundaries.',
                           'Tolerance boundary spread is algorithm sensitivity, not a positional accuracy bound.',
                           'All plane and ridge observations use the same survey; independent checkpoints are still missing.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['planes','site','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=review(a.planes,a.site);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(r['building_comparisons'],indent=2))

if __name__=='__main__':main()
