"""Test frozen shop-fit transforms against additional site-plan outlines."""
import argparse, base64, hashlib, json, sys, zlib
from pathlib import Path
import laspy, numpy as np, fitz
from shapely import intersects_xy
from shapely.affinity import affine_transform
from shapely.geometry import MultiPoint, shape
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.drawing_geometry import extract_page
from voxel_mapper.linework_boundaries import recover_page
from voxel_mapper.point_cloud import is_bng
from voxel_mapper.roof_candidates import components

PDF='3a8a18eb3959a39e7559309046b0815469b9f9baa52a5d1364a0cc4aa2cbb279'
FIT='792f0448b81cfa398f1ce8e552d88e9f3bf2cda2f8b95a4a0b2811deaed6d17c'
IDS={'shop':'0cd1b42547140df906c3b7315497b88f97b78cdb975bff5a03ccc8dd952c5954',
     'station':'2cbdfcfa8c126fc5bf349a113a6eb03eab6f5d10dcf9d62765460eff8f9dd211',
     'maintenance':'46f22e9840f0dc79e562936fff89269509fefd0bc13fd9e1f94a36b2bd122975'}


def compare(pdf, cloud_path, crop_path, fit_path):
    if file_hash(pdf)!=PDF or file_hash(fit_path)!=FIT:raise ValueError('Pinned revised site plan and shop fit required')
    crop=json.loads(Path(crop_path).read_text());fit=json.loads(Path(fit_path).read_text())
    if file_hash(cloud_path)!=crop['sha256']:raise ValueError('Extended native cloud checksum mismatch')
    if crop['survey']['survey_id']!='P_10682' or crop['survey']['survey_start']!='20220105' or fit['survey']!=crop['survey']:
        raise ValueError('Exact survey identity required')
    with fitz.open(pdf) as document:
        raw,extraction=extract_page(document[0],PDF,1);candidates,recovery=recover_page(raw)
    selected={name:next((c for c in candidates if c['id']==ident),None) for name,ident in IDS.items()}
    if any(c is None for c in selected.values()):raise ValueError('Source building candidates did not reproduce')
    if not shape(selected['shop']['geometry']).equals_exact(shape(fit['source_candidate']['geometry']),0,normalize=True):
        raise ValueError('Prior fit shop outline differs from revised source')
    hypotheses=next(e for e in fit['envelopes'] if e['point_count']==505)['printed_scale_edge_review']['equivalent_orientations']
    if len(hypotheses)!=2:raise ValueError('Both frozen shop orientations required')
    cloud=laspy.read(cloud_path)
    if not is_bng(cloud.header.parse_crs()) or len(cloud)!=crop['retained_points']:raise ValueError('Native BNG point count mismatch')
    xyz=np.column_stack((cloud.x,cloud.y,cloud.z));mask=(np.asarray(cloud.classification)==6)&(~np.asarray(cloud.withheld,dtype=bool))&(~np.asarray(cloud.synthetic,dtype=bool))&np.isfinite(xyz).all(axis=1)
    indices=np.flatnonzero(mask);xyz=xyz[mask]
    if len(xyz)>20_000:raise ValueError('Building connectivity point budget exceeded')
    placed=[]
    for h in hypotheses:
        m=h['matrix'];t=h['translation_m']
        placed.append({name:affine_transform(shape(c['geometry']),[*m[0],*m[1],*t]) for name,c in selected.items()})
    rows=[];envelopes={}
    for radius in [1,1.5,2]:
        for step in [.5,1,2]:
            groups,cost=components(xyz,radius,step)
            for number,polygons in enumerate(placed):
                matches={}
                for name,polygon in polygons.items():
                    seed=intersects_xy(polygon,xyz[:,0],xyz[:,1])
                    positive=[(int(np.count_nonzero(seed[g])),g) for g in groups if np.any(seed[g])]
                    if not positive:
                        matches[name]={'status':'no_building_returns_in_hypothesis','seed_return_count':0};continue
                    positive.sort(key=lambda v:(-v[0],int(v[1][0])));hits,g=positive[0]
                    native_ids=indices[g]; membership=hashlib.sha256(np.asarray(native_ids,dtype='<u8').tobytes()).hexdigest()
                    hull=MultiPoint(xyz[g,:2]).convex_hull
                    if hull.geom_type!='Polygon':
                        matches[name]={'status':'insufficient_polygon_support','seed_return_count':hits};continue
                    bounds=hull.bounds;b=crop['bounds']
                    edge=min(bounds[0]-b[0],bounds[1]-b[1],b[2]-bounds[2],b[3]-bounds[3])<=radius
                    envelopes.setdefault(membership,{'membership_sha256':membership,'point_indices_encoding':'zlib-base64 little-endian uint64 in expanded-crop order',
                        'original_expanded_crop_point_indices_zlib_base64':base64.b64encode(zlib.compress(np.asarray(native_ids,dtype='<u8').tobytes())).decode(),
                        'point_count':len(g),'geometry':hull.__geo_interface__,'max_z_odn_m':float(xyz[g,2].max())})
                    matches[name]={'status':'native_component_comparison','membership_sha256':membership,
                        'seed_return_count':hits,'point_count':len(g),'crop_edge_within_connectivity_radius':bool(edge),
                        'frozen_outline_iou':polygon.intersection(hull).area/polygon.union(hull).area,
                        'frozen_boundary_hausdorff_metres':polygon.boundary.hausdorff_distance(hull.boundary),
                        'projected_window_max_z_odn_m':float(xyz[seed,2].max()),
                        'window_maximum_is_not_independent_roof_vertex':True}
                a,b=matches['station'],matches['maintenance']
                shared=a.get('membership_sha256') is not None and a.get('membership_sha256')==b.get('membership_sha256')
                rows.append({'radius_metres':radius,'height_step_metres':step,'comparison_cost':cost,
                    'hypothesis_index':number,'rotation_degrees':hypotheses[number]['rotation_degrees'],
                    'building_comparisons':matches,'station_maintenance_share_component':shared})
    return {'status':'frozen_transform_cross_building_review_only','document_sha256':PDF,
            'source_candidates':selected,'extraction_status':extraction['status'],'recovery_status':recovery['status'],
            'frozen_hypotheses':[{'rotation_degrees':h['rotation_degrees'],'matrix':h['matrix'],'translation_m':h['translation_m'],
                'placed_building_geometries':{name:p.__geo_interface__ for name,p in polygons.items()}}
                for h,polygons in zip(hypotheses,placed)],
            'sweep_results':rows,'distinct_native_components':list(envelopes.values()),
            'survey':crop['survey'],'extended_crop_bounds':crop['bounds'],
            'input_sha256':{k:file_hash(p) for k,p in [('pdf',pdf),('cloud',cloud_path),('crop',crop_path),('shop_fit',fit_path)]},
            'additional_buildings_used_to_refit_transform':False,
            'limitations':['Source candidates are drawing outlines; exact roof/wall line roles remain unverified.',
                           'Station and maintenance can share one component; they cannot be counted as independent roofs from that envelope.',
                           'Projected-window heights reuse the hypothesis and are not surveyed roof vertices.',
                           'Connectivity sensitivity is not positional uncertainty.',
                           'All observed returns come from one survey; these comparisons are not separately sourced checkpoints.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['pdf','cloud','crop','shop-fit','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args();r=compare(a.pdf,a.cloud,a.crop,a.shop_fit);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    for row in r['sweep_results']:
        if row['radius_metres']==1.5 and row['height_step_metres']==.5:
            print(json.dumps(row))

if __name__=='__main__':main()
