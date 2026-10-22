"""Fresh replay plus separate original graph, raster, surface and join arithmetic."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
import pymupdf
from rasterio.features import rasterize
from scipy import ndimage
from voxel_mapper.pyramidal_roof_evidence import build
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest
from scripts.audit_preshow_level_geometry import audit as audit_parent
from scripts.audit_roof_reference_evidence import clipped_length


def audit(evidence,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output):
    evidence,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output=map(Path,
        (evidence,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output))
    path=evidence/'pyramidal-roof-evidence.json';r=json.loads(path.read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,temp,max_checks=r['contract']['max_checks']);fresh.pop('directory');assert digest(fresh)==digest(r)
        parent_receipt=audit_parent(preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,Path(temp)/'parent-audit.json')
    assert r['status']=='conditional_pyramidal_roof_evidence_only'
    parent=json.loads((preshow/'preshow-level-geometry.json').read_text());reference=json.loads((references/'roof-reference-evidence.json').read_text())
    candidates={};graph_by_candidate={};original_lines={}
    for graph in r['plan_graphs']:
        original=corpus/'files'/(graph['document_sha256']+'.pdf');assert file_hash(original)==graph['document_sha256']
        with pymupdf.open(original) as doc:
            page=doc[graph['page']-1];matrix=native_inverse(page);strokes=set()
            for paint in page.get_drawings():
                if paint['type']!='s' or len(paint['items'])!=1 or paint['items'][0][0]!='l':continue
                points=[tuple(p*matrix) for p in paint['items'][0][1:]];strokes.add(tuple(sorted(points)))
        lines={l['source_component_id']:l for l in graph['original_lines']};original_lines.update(lines)
        for c in graph['candidates']:
            center=c['source_apex_pdf_native'];corners=c['source_corners_pdf_native']
            for i in range(4):
                for source_id in c['source_spoke_ids_per_corner'][i]:
                    points=lines[source_id]['source_endpoints_pdf_native'];assert tuple(sorted(map(tuple,points))) in strokes
                    assert sorted(points)==sorted([center,corners[i]]);checked['original_spoke_witnesses']+=1
                for source_id in c['source_perimeter_ids_per_edge'][i]:
                    points=lines[source_id]['source_endpoints_pdf_native'];assert tuple(sorted(map(tuple,points))) in strokes
                    assert sorted(points)==sorted([corners[i],corners[(i+1)%4]]);checked['original_perimeter_witnesses']+=1
                a,b=np.array(corners[i]),np.array(corners[(i+1)%4]);assert abs(np.linalg.norm(b-a)*graph['nominal_metres_per_pdf_point']-c['nominal_edge_lengths_m'][i])<1e-10
            assert not c['source_endpoints_snapped'] and not c['source_closure_inferred'];candidates[c['id']]=c;graph_by_candidate[c['id']]=graph
    for j in r['source_junctions']:
        c=candidates[j['pyramid_candidate_id']];perimeter={key for group in c['source_perimeter_ids_per_edge'] for key in group}
        assert j['shared_original_cap_source_id'] in perimeter
        unit=graph_by_candidate[c['id']]['nominal_metres_per_pdf_point']
        for tail in j['rail_tail_relations']:
            whole=original_lines[tail['rail_source_id']]['source_endpoints_pdf_native'];assert whole==tail['whole_source_endpoints_pdf_native']
            end=whole[tail['original_rail_endpoint_index']];start=tail['original_cap_endpoint_pdf_native'];length=math.dist(start,end)
            assert end==tail['original_tail_endpoint_pdf_native']
            for overlap in tail['boundary_overlaps']:
                a,b=map(np.array,original_lines[overlap['source_perimeter_id']]['source_endpoints_pdf_native']);axis=(b-a)/np.linalg.norm(b-a)
                p,q=np.array(start),np.array(end);assert max(abs(axis[0]*(p-a)[1]-axis[1]*(p-a)[0]),abs(axis[0]*(q-a)[1]-axis[1]*(q-a)[0]))<1e-8
                interval=sorted([float((p-a)@axis),float((q-a)@axis)]);shared=max(0.,min(np.linalg.norm(b-a),interval[1])-max(0.,interval[0]))
                unit=graph_by_candidate[c['id']]['nominal_metres_per_pdf_point'];assert abs(shared*unit-overlap['coincident_original_interval_nominal_m'])<1e-9
            assert abs(length*unit-tail['source_tail_length_nominal_m'])<1e-9 and not tail['whole_rail_trimmed'];checked['original_untrimmed_boundary_tail_intervals']+=1
        assert not j['physical_roof_join_verified'] and j['new_join_mesh'] is None
    context_by_id={c['id']:c for c in r['source_contexts']}
    links={l['id']:l for l in reference['target_links']}
    for c in r['source_contexts']:
        polygon=[*candidates[c['candidate_id']]['source_corners_pdf_native']];length=clipped_length(c['diagnostic_aim_segment_pdf_native'],[*polygon,polygon[0]])
        assert abs(length-c['positive_intersection_length_pdf_points'])<1e-8
        direction=np.array(c['diagnostic_aim_segment_pdf_native'][1])-c['diagnostic_aim_segment_pdf_native'][0];direction/=np.linalg.norm(direction)
        assert np.allclose(direction,c['source_view_direction_pdf_native'],atol=1e-12,rtol=0)
        corners=np.array(polygon);edges=np.roll(corners,-1,axis=0)-corners;alignment=max(abs(float(direction@v/np.linalg.norm(v))) for v in edges)
        link=links[c['source_target_link_id']];passed=length>0 and alignment>=math.cos(math.radians(5)) and link['status']=='unique_source_view_reference_candidate'
        assert (c['status']=='conditional_pyramid_source_view_context')==passed
        assert not c['source_visibility_hold_overridden'] and not c['diagnostic_reach_changed'];checked['independent_finite_symbol_contexts']+=1
    for view in r['new_source_views']:
        assert file_hash(references/view['png'])==view['png_sha256']
        with Image.open(references/view['png']) as im:gray=np.asarray(im.convert('L'))
        records=view['source_exclusions']['records'];mask=rasterize([(r['geometry_pixels'],1) for r in records],out_shape=gray.shape,all_touched=True)>0 if records else np.zeros_like(gray,bool)
        assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==view['source_exclusions']['source_mask_sha256']
        for scan in view['variants']:
            ink=gray<scan['threshold'];gx=ndimage.sobel(ink.astype(float),axis=1);gy=ndimage.sobel(ink.astype(float),axis=0)
            angle=(np.degrees(np.arctan2(-gx,gy))+90)%180-90;eligible=ink&~mask&(abs(angle)>=15)&(abs(angle)<=65)&(np.hypot(gx,gy)>=1)
            yy,xx=np.nonzero(eligible);angles=angle[yy,xx]
            for line in scan['lines']:
                x=np.array([p['x'] for p in line['source_pixels']]);y=np.array([p['y'] for p in line['source_pixels']]);fit=x%2==0
                assert eligible[y,x].all() and all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in line['source_pixels'])
                dx=x[fit]-x[fit].mean();slope=float(dx@(y[fit]-y[fit].mean())/(dx@dx));intercept=float(y[fit].mean()-slope*x[fit].mean())
                assert abs(slope-line['slope'])<1e-10 and abs(intercept-line['intercept'])<1e-8
                for seed in line['hough_seeds']:
                    rad=math.radians(seed['angle_degrees']);normal=yy*math.cos(rad)-xx*math.sin(rad)
                    ids=np.flatnonzero((abs(angles-seed['angle_degrees'])<=12)&(abs(normal-seed['normal_offset_pixels'])<=1.5));ids=ids[np.lexsort((yy[ids],xx[ids]))]
                    assert np.array_equal(x,xx[ids]) and np.array_equal(y,yy[ids]);checked['whole_original_hough_groups']+=1
                checked['original_slope_pixel_memberships']+=len(x)
            for cap in scan['source_fascia_columns']:
                x=cap['x'];y=np.array([p['y'] for p in cap['source_pixels']]);assert all(p['x']==x and p['gray']==gray[p['y'],x] for p in cap['source_pixels'])
                all_y=np.flatnonzero(ink[:,x]&~mask[:,x]);groups=np.split(all_y,np.flatnonzero(np.diff(all_y)>2)+1);matches=[g for g in groups if len(g) and [int(g[0]),int(g[-1])]==cap['source_y_interval_pixels']]
                assert len(matches)==1 and np.array_equal(y,matches[0]);assert not cap['source_gaps_filled'];checked['whole_literal_columns']+=1;checked['original_column_pixel_memberships']+=len(y)
    views_by_id={v['view_id']:v for v in [*r['new_source_views'],*parent['gable_views']]};pairs={};caps={}
    for view in views_by_id.values():
        for scan in view['variants']:
            lines={l['id']:l for l in scan['lines']};caps.update({c['id']:c for c in scan['source_fascia_columns']})
            for pair in scan['gable_intersections']:
                a,b=[lines[pair[key]] for key in ('left_line_id','right_line_id')];point=np.linalg.solve([[-a['slope'],1],[-b['slope'],1]],[a['intercept'],b['intercept']]);assert np.allclose(point,pair['inferred_ridge_pixel'],rtol=0,atol=1e-9);pairs[pair['id']]=pair;checked['independent_slope_intersections']+=1
    silhouettes={s['id']:s for s in [*r['primary_silhouettes'],*r['supplemental_silhouettes']]};projections={s['projection']['id']:s['projection'] for s in silhouettes.values()}
    ends={c['id']:c for c in r['endcap_checks']};bindings={b['id']:b for p in parent['level_pages'] for b in p['marker_bindings']}
    for c in r['source_corner_checks']:
        cap=caps[c['source_fascia_column_id']];actual=[cap['x'],cap['source_y_interval_pixels'][0]];errors=np.array(actual)-c['predicted_corner_pixel']
        assert np.allclose(errors,c['source_corner_error_pixels'],rtol=0,atol=1e-9)
        assert (c['status']=='source_corner_within_pixel_tolerance')==(max(abs(v) for v in errors)<=4);checked['independent_corner_failures_and_supports']+=1
    for c in r['source_corner_edge_checks']:
        view=views_by_id[c['view_id']];lines={l['id']:l for scan in view['variants'] for l in scan['lines']}
        for key,point,pixels in zip(c['source_line_ids'],c['predicted_corner_pixels'],c['original_slope_corner_support_pixels']):
            expected=[p for p in lines[key]['source_pixels'] if abs(p['x']-point[0])<=4 and abs(p['y']-point[1])<=4]
            assert expected==pixels
        assert (c['status']=='original_slope_pixels_support_corners')==all(c['original_slope_corner_support_pixels'])
        assert c['whole_hough_groups_retained'];checked['independent_original_corner_edge_supports']+=1
    for end in r['endcap_checks']:
        if end['source_cap_variant_id'] in projections:projection=projections[end['source_cap_variant_id']]
        else:
            # Unsuccessful pairs can have no silhouette. Reconstruct this context projection separately.
            candidate=candidates[end['candidate_id']];context=next(c for c in r['source_contexts'] if c['candidate_id']==candidate['id'] and c['status']=='conditional_pyramid_source_view_context')
            points=np.array(candidate['source_corners_pdf_native']);unit=graph_by_candidate[candidate['id']]['nominal_metres_per_pdf_point'];stations=(points-candidate['source_apex_pdf_native'])@context['source_horizontal_axis_pdf_native']*unit;projection={'native_runs_m':[-float(stations.min()),float(stations.max())]}
        pair=pairs[end['source_pair_id']];x,y=pair['inferred_ridge_pixel'];runs=projection['native_runs_m'][::end['image_left_to_native_rail_orientation']];mpp=views_by_id[end['view_id']]['nominal_metres_per_pixel']
        predicted=[[x-runs[0]/mpp,y+math.tan(math.radians(pair['left_pitch_degrees']))*runs[0]/mpp],[x+runs[1]/mpp,y+math.tan(math.radians(pair['right_pitch_degrees']))*runs[1]/mpp]]
        actual=[[caps[key]['x'],caps[key]['source_y_interval_pixels'][0]] for key in end['source_fascia_column_ids']];errors=np.array(actual)-predicted
        assert np.allclose(errors,end['source_corner_error_pixels'],atol=1e-9,rtol=0)
        passed=np.max(np.abs(errors))<=4 and abs(pair['left_pitch_degrees']-pair['right_pitch_degrees'])<=2
        assert (end['status']=='conditional_source_endcaps_agree')==passed;checked['independent_endcap_checks']+=1
    for s in silhouettes.values():
        view=views_by_id[s['view_id']];binding=bindings[s['source_level_binding_id']];matrix=view['pixel_to_display_matrix'];level=(binding['datum_y_display_points']-matrix[5])/matrix[3];mpp=view['nominal_metres_per_pixel'];pair=pairs[s['source_pair_id']]
        assert abs((level-pair['inferred_ridge_pixel'][1])*mpp-s['apex_above_printed_level_nominal_m'])<1e-10
        for end_id,points in zip(s['source_endcap_check_ids'],s['source_eave_top_pixel_alternatives']):
            end=ends[end_id];assert end['status']=='conditional_source_endcaps_agree' and end['source_eave_top_pixels']==points
            assert np.allclose([(level-p[1])*mpp for p in points],s['image_eaves_above_printed_level_nominal_m'],rtol=0,atol=1e-10);checked['equivalent_height_original_witnesses']+=1
        checked['source_silhouettes']+=1
    for c in r['cross_view_checks']:
        a,b=[silhouettes[key] for key in c['source_silhouette_ids']];offset=a['source_level_value_m_candidate']-b['source_level_value_m_candidate']
        errors=[a['apex_above_printed_level_nominal_m']-b['apex_above_printed_level_nominal_m']+offset,*[x-y+offset for x,y in zip(a['image_eaves_above_printed_level_nominal_m'],b['image_eaves_above_printed_level_nominal_m'][::c['supplemental_image_side_orientation']])]]
        assert np.allclose(errors,[c['apex_difference_nominal_m'],*c['eave_differences_nominal_m']],rtol=0,atol=1e-10)
        assert (c['status']=='conditional_cross_view_pyramid_heights_agree')==(max(abs(v) for v in errors)<=.25);checked['independent_cross_view_checks']+=1
    models={m['id']:m for m in r['conditional_pyramid_models']}
    for m in models.values():
        s=silhouettes[m['source_silhouette_id']];candidate=candidates[m['candidate_id']];unit=graph_by_candidate[candidate['id']]['nominal_metres_per_pdf_point'];points=np.array(candidate['source_corners_pdf_native']);axis=context_by_id[m['context_id']]['source_horizontal_axis_pdf_native'];stations=(points-candidate['source_apex_pdf_native'])@axis*unit
        left,right=s['image_eaves_above_printed_level_nominal_m'][::s['image_left_to_native_orientation']];heights=left+(stations-stations.min())/(stations.max()-stations.min())*(right-left)
        expected=np.column_stack([(points-candidate['source_apex_pdf_native'])*unit,heights]);assert np.allclose(expected,m['mesh']['vertices'][:4],rtol=0,atol=1e-10)
        assert m['mesh']['vertices'][4]==[0.,0.,s['apex_above_printed_level_nominal_m']]
        assert m['mesh']['triangles']==[[0,1,4],[1,2,4],[2,3,4],[3,0,4]] and not m['mesh']['world_placement_eligible'];checked['independent_conditional_pyramid_meshes']+=1
    low_models={m['id']:m for m in parent['conditional_roof_patches']};joins={j['id']:j for j in r['source_junctions']}
    for c in r['open_join_checks']:
        high=models[c['source_pyramid_model_id']];low=low_models[c['source_gable_model_id']];j=joins[c['source_junction_id']];candidate=candidates[j['pyramid_candidate_id']];index=next(i for i,ids in enumerate(candidate['source_perimeter_ids_per_edge']) if j['shared_original_cap_source_id'] in ids);a,b=[np.array(candidate['source_corners_pdf_native'][i%4]) for i in (index,index+1)]
        low_indices=[0,2,4] if j['ridge_endpoint_index']==0 else [1,3,5];values=high['mesh']['source_corner_heights_nominal_m'];gaps=[]
        for sample,low_index in zip(c['samples'],low_indices):
            point=np.array(sample['original_point_pdf_native']);fraction=math.dist(a,point)/math.dist(a,b);height=(1-fraction)*values[index]+fraction*values[(index+1)%4]+high['source_level_value_m_candidate'];low_height=low['mesh']['vertices'][low_index][2]+low['source_level_value_m_candidate'];gap=height-low_height;gaps.append(gap)
            assert abs(gap-sample['signed_vertical_gap_nominal_m'])<1e-9;checked['independent_open_join_samples']+=1
        assert abs(min(gaps)-c['minimum_signed_vertical_gap_nominal_m'])<1e-9
        assert (c['status']=='conditional_open_vertical_join_requires_wall_evidence')==all(v>0 for v in gaps);assert not c['gap_filled'] and c['join_mesh'] is None;checked['independent_open_join_checks']+=1
    for c in r['threshold_checks']:
        a,b=[models[key] for key in c['source_model_ids']];differences=np.abs(np.array(a['mesh']['vertices'])[:,2]-np.array(b['mesh']['vertices'])[:,2]);assert np.allclose(differences,c['vertex_height_differences_nominal_m'],atol=1e-10,rtol=0)
        assert (c['status']=='pyramid_threshold_heights_agree')==(max(differences)<=4*a['nominal_metres_per_pixel']);checked['independent_threshold_checks']+=1
    for c in r['threshold_coverage']:
        matching=[m for m in models.values() if all(m[k]==c[k] for k in ('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation'))]
        expected={str(t):[m['id'] for m in matching if m['source_ink_threshold']==t] for t in (220,235)}
        assert expected==c['source_model_ids_by_threshold'];assert c['missing_source_thresholds']==[t for t in (220,235) if not expected[str(t)]]
        assert (c['status']=='pyramid_cross_threshold_support_missing')==(not all(expected.values()))
        assert not c['physical_acceptance_authorized'];checked['independent_missing_threshold_holds']+=1
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_preshow_sha256':file_hash(preshow/'preshow-level-geometry.json'),'parent_audit':parent_receipt,'checked':dict(checked)}
    atomic_json(output,receipt);return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','preshow','references','topology-source','gradient','components','views','corpus','source-catalogue','additional-pdfs','output'):parser.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(parser.parse_args()))))
