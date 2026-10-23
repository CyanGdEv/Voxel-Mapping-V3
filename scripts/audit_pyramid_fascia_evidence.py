"""Fresh replay and independent neighbour-pixel, observed-face and strip checks."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
from rasterio.features import rasterize
from shapely.geometry import LineString,Point,Polygon
from voxel_mapper.pyramid_fascia_evidence import build
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from scripts.audit_pyramidal_roof_evidence import audit as audit_parent


def audit(evidence,pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output):
    evidence,pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output=map(Path,
        (evidence,pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output))
    path=evidence/'pyramid-fascia-evidence.json';r=json.loads(path.read_text());checked=Counter()
    args=(pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs)
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(*args,temp,max_checks=r['contract']['max_checks']);fresh.pop('directory');assert digest(fresh)==digest(r)
        prior=audit_parent(pyramid,*args[1:],Path(temp)/'parent.json')
    assert r['status']=='conditional_source_gradient_fascia_only'
    parent=json.loads((pyramid/'pyramidal-roof-evidence.json').read_text());old=json.loads((preshow/'preshow-level-geometry.json').read_text())
    candidates={c['id']:(g,c) for g in parent['plan_graphs'] for c in g['candidates']};contexts={c['id']:c for c in parent['source_contexts']};bindings={b['id']:b for p in old['level_pages'] for b in p['marker_bindings']}
    columns={};pairs={};view_by_id={v['view_id']:v for v in parent['new_source_views']}
    for view in r['edge_views']:
        assert file_hash(references/view['png'])==view['png_sha256']
        with Image.open(references/view['png']) as im:gray=np.asarray(im.convert('L'))
        records=view['source_exclusions']['records'];mask=rasterize([(v['geometry_pixels'],1) for v in records],out_shape=gray.shape,all_touched=True)>0 if records else np.zeros_like(gray,bool)
        for scan in view['variants']:
            assert hashlib.sha256(gray.tobytes()).hexdigest()==scan['source_gray_sha256'];assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==scan['source_mask_sha256']
            expected=set();returned={(c['x'],*c['source_y_interval_pixels']):c for c in scan['source_fascia_columns']}
            for x in range(1,gray.shape[1]-1):
                center=gray[:,x].astype(int);left=gray[:,x-1].astype(int);right=gray[:,x+1].astype(int);diff=np.maximum(left,right)-center
                yy=np.flatnonzero((center<scan['threshold'])&~mask[:,x]&~mask[:,x-1]&~mask[:,x+1]&(diff>=scan['source_gradient_contrast']))
                for group in np.split(yy,np.flatnonzero(np.diff(yy)>2)+1):
                    if len(group)<16 or group[-1]-group[0]<16 or group[-1]-group[0]>=64 or group[0]==0 or group[-1]==gray.shape[0]-1:continue
                    key=(x,int(group[0]),int(group[-1]));expected.add(key);c=returned[key]
                    assert [p['y'] for p in c['source_pixels']]==group.tolist()
                    for p in c['source_pixels']:
                        y=p['y'];assert p['x']==x and p['gray']==int(gray[y,x]) and p['left_original_gray']==int(gray[y,x-1]) and p['right_original_gray']==int(gray[y,x+1])
                        assert p['maximum_original_neighbour_difference']==int(max(gray[y,x-1],gray[y,x+1]))-int(gray[y,x]);checked['original_neighbour_pixel_triplets']+=1
                    assert not c['source_gaps_filled'] and not c['source_pixels_clipped_to_prediction'];columns[c['id']]=c;checked['whole_original_contrast_columns']+=1
            assert expected==set(returned);checked['complete_source_configuration_indices']+=1
            pairs.update({p['id']:p for p in scan['gable_intersections']})
    faces={f['id']:f for f in r['observed_faces']}
    for face in faces.values():
        context=contexts[face['context_id']];_,candidate=candidates[face['candidate_id']];segment=LineString(context['diagnostic_aim_segment_pdf_native']);corners=candidate['source_corners_pdf_native'];hits=[]
        for i in range(4):
            point=segment.intersection(LineString([corners[i],corners[(i+1)%4]]))
            if point.geom_type=='Point':hits.append((segment.project(point,normalized=True),i,point))
        hits.sort(key=lambda a:(a[0],a[1]));first=[h for h in hits if abs(h[0]-hits[0][0])<=1e-9] if hits else []
        start_inside=Polygon(corners).covers(Point(context['diagnostic_aim_segment_pdf_native'][0]))
        passed=not start_inside and len(first)==1 and 1e-6<LineString([corners[first[0][1]],corners[(first[0][1]+1)%4]]).project(first[0][2],normalized=True)<1-1e-6
        assert (face['status']=='conditional_original_observed_edge')==passed
        for row,hit in zip(face['intersections'],hits):
            assert row['source_edge_index']==hit[1] and abs(row['diagnostic_segment_fraction']-hit[0])<1e-9;assert np.allclose(row['diagnostic_entry_point_pdf_native'],list(hit[2].coords)[0],rtol=0,atol=1e-8)
            assert row['source_perimeter_ids']==candidate['source_perimeter_ids_per_edge'][hit[1]];checked['independent_original_edge_intersections']+=1
        assert not face['diagnostic_reach_changed']
    ends={c['id']:c for c in r['endcap_checks']};silhouettes={s['id']:s for s in r['primary_silhouettes']};supplements={s['id']:s for s in parent['supplemental_silhouettes']}
    for c in r['source_corner_checks']:
        cap=columns[c['source_fascia_column_id']];error=np.array([cap['x'],cap['source_y_interval_pixels'][0]])-c['predicted_corner_pixel'];assert np.allclose(error,c['source_corner_error_pixels'],atol=1e-9,rtol=0)
        assert (c['status']=='source_corner_within_pixel_tolerance')==(np.max(abs(error))<=4);checked['independent_local_corner_checks']+=1
    for s in silhouettes.values():
        graph,candidate=candidates[s['candidate_id']];context=contexts[s['context_id']];view=view_by_id[s['view_id']];matrix=view['pixel_to_display_matrix'];binding=bindings[s['source_level_binding_id']];level=(binding['datum_y_display_points']-matrix[5])/matrix[3];pair=pairs[s['source_pair_id']];mpp=view['nominal_metres_per_pixel']
        assert abs(s['apex_above_printed_level_nominal_m']-(level-pair['inferred_ridge_pixel'][1])*mpp)<1e-10
        axis=np.array(context['source_horizontal_axis_pdf_native']);stations=(np.array(candidate['source_corners_pdf_native'])-candidate['source_apex_pdf_native'])@axis*graph['nominal_metres_per_pdf_point'];runs=[-min(stations),max(stations)]
        for key,points in zip(s['source_endcap_check_ids'],s['source_eave_top_pixel_alternatives']):
            end=ends[key];actual=[[columns[c]['x'],columns[c]['source_y_interval_pixels'][0]] for c in end['source_fascia_column_ids']];assert actual==points
            rr=runs[::s['image_left_to_native_orientation']];x,y=pair['inferred_ridge_pixel'];predicted=[[x-rr[0]/mpp,y+math.tan(math.radians(pair['left_pitch_degrees']))*rr[0]/mpp],[x+rr[1]/mpp,y+math.tan(math.radians(pair['right_pitch_degrees']))*rr[1]/mpp]]
            assert np.max(np.abs(np.array(actual)-predicted))<=4;assert np.allclose([(level-p[1])*mpp for p in actual],s['image_eaves_above_printed_level_nominal_m'],atol=1e-10,rtol=0);checked['independent_supported_endcap_witnesses']+=1
    for check in r['cross_view_checks']:
        a=silhouettes[check['source_silhouette_ids'][0]];b=supplements[check['source_silhouette_ids'][1]];offset=a['source_level_value_m_candidate']-b['source_level_value_m_candidate'];errors=[a['apex_above_printed_level_nominal_m']-b['apex_above_printed_level_nominal_m']+offset,*[x-y+offset for x,y in zip(a['image_eaves_above_printed_level_nominal_m'],b['image_eaves_above_printed_level_nominal_m'][::check['supplemental_image_side_orientation']])]]
        assert np.allclose(errors,[check['apex_difference_nominal_m'],*check['eave_differences_nominal_m']],rtol=0,atol=1e-10);assert (check['status']=='conditional_cross_view_pyramid_heights_agree')==(max(abs(v) for v in errors)<=.25);checked['independent_cross_view_checks']+=1
    models={m['id']:m for m in r['models']}
    for model in models.values():
        s=silhouettes[model['source_silhouette_id']];graph,candidate=candidates[model['candidate_id']];context=contexts[model['context_id']];unit=graph['nominal_metres_per_pdf_point'];xy=(np.array(candidate['source_corners_pdf_native'])-candidate['source_apex_pdf_native'])*unit;axis=context['source_horizontal_axis_pdf_native'];stations=xy@axis;alpha=(stations-min(stations))/(max(stations)-min(stations));eaves=s['image_eaves_above_printed_level_nominal_m'][::s['image_left_to_native_orientation']];tops=eaves[0]+alpha*(eaves[1]-eaves[0])
        assert np.allclose(np.c_[xy,tops],model['mesh']['vertices'][:4],atol=1e-10,rtol=0);assert model['mesh']['vertices'][4]==[0.,0.,s['apex_above_printed_level_nominal_m']];checked['independent_roof_meshes']+=1
        strip=model['observed_fascia_mesh']
        if strip:
            face=next(f for f in faces.values() if f['context_id']==model['context_id']);edge=face['first_edge_candidates'][0]['source_edge_index'];assert strip['original_plan_edge_index']==edge
            view=view_by_id[s['view_id']];matrix=view['pixel_to_display_matrix'];level=(bindings[s['source_level_binding_id']]['datum_y_display_points']-matrix[5])/matrix[3];end=ends[s['source_endcap_check_id']];bottom_y=[columns[key]['source_y_interval_pixels'][1] for key in end['source_fascia_column_ids']];bottoms=[(level-y)*s['nominal_metres_per_pixel'] for y in bottom_y][::s['image_left_to_native_orientation']];bottom_plane=bottoms[0]+alpha*(bottoms[1]-bottoms[0]);a,b=edge,(edge+1)%4
            expected=[[*xy[a],tops[a]],[*xy[a],bottom_plane[a]],[*xy[b],bottom_plane[b]],[*xy[b],tops[b]]];assert np.allclose(expected,strip['vertices'],atol=1e-10,rtol=0);assert strip['triangles']==[[0,1,2],[0,2,3]]
            assert not strip['depth_transferred_to_other_edges'] and strip['wall_mesh'] is None;checked['independent_observed_face_strips']+=1
    for c in r['stability_checks']:
        a,b=[models[key] for key in c['source_model_ids']];errors=np.abs(np.array(a['mesh']['vertices'])[:,2]-np.array(b['mesh']['vertices'])[:,2]);depths=np.abs(np.array(a['observed_fascia_mesh']['observed_corner_depths_nominal_m'])-b['observed_fascia_mesh']['observed_corner_depths_nominal_m'])
        assert np.allclose(errors,c['roof_vertex_height_differences_nominal_m'],atol=1e-10,rtol=0) and np.allclose(depths,c['fascia_depth_differences_nominal_m'],atol=1e-10,rtol=0)
        assert (c['status']=='source_contrast_measurements_agree')==(max(*errors,*depths)<=4*a['nominal_metres_per_pixel']);checked['independent_configuration_comparisons']+=1
    for coverage in r['configuration_coverage']:
        group=[m for m in models.values() if all(m[k]==coverage[k] for k in ('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation'))];configurations={f'{t}/{c}':[m['id'] for m in group if (m['source_ink_threshold'],m['source_gradient_contrast'])==(t,c)] for t in (220,235) for c in (32,64)}
        assert configurations==coverage['source_models_by_configuration'];assert coverage['missing_configurations']==[k for k,v in configurations.items() if not v];assert not coverage['physical_acceptance_authorized'];checked['independent_four_configuration_coverage']+=1
    low_models={m['id']:m for m in old['conditional_roof_patches']};joins={j['id']:j for j in parent['source_junctions']}
    for check in r['open_join_checks']:
        high=models[check['source_pyramid_model_id']];low=low_models[check['source_gable_model_id']];j=joins[check['source_junction_id']];_,candidate=candidates[j['pyramid_candidate_id']];i=next(i for i,ids in enumerate(candidate['source_perimeter_ids_per_edge']) if j['shared_original_cap_source_id'] in ids);a,b=candidate['source_corners_pdf_native'][i],candidate['source_corners_pdf_native'][(i+1)%4];heights=high['mesh']['source_corner_heights_nominal_m'];indices=[0,2,4] if j['ridge_endpoint_index']==0 else [1,3,5]
        for sample,index in zip(check['samples'],indices):
            t=math.dist(a,sample['original_point_pdf_native'])/math.dist(a,b);gap=(1-t)*heights[i]+t*heights[(i+1)%4]+high['source_level_value_m_candidate']-low['mesh']['vertices'][index][2]-low['source_level_value_m_candidate'];assert abs(gap-sample['signed_vertical_gap_nominal_m'])<1e-9;checked['independent_open_join_samples']+=1
        assert not check['gap_filled'] and check['join_mesh'] is None
    for c in r['shared_cap_face_checks']:
        face=faces[c['source_observed_face_id']];j=joins[c['source_junction_id']];ids={key for edge in face['first_edge_candidates'] for key in edge['source_perimeter_ids']};assert c['observed_fascia_edge_is_shared_cap']==(j['shared_original_cap_source_id'] in ids)
        assert not c['depth_transferred_to_shared_cap'] and not c['closure_authorized'] and c['wall_or_join_mesh'] is None;checked['independent_shared_cap_transfer_holds']+=1
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_pyramid_sha256':file_hash(pyramid/'pyramidal-roof-evidence.json'),'parent_audit':prior,'checked':dict(checked)}
    atomic_json(output,receipt);return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','pyramid','preshow','references','topology-source','gradient','components','views','corpus','source-catalogue','additional-pdfs','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
