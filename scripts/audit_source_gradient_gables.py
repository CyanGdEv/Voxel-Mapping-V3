"""Independent original-pixel/plan-stroke audit of grayscale gable evidence."""
import argparse
from collections import Counter,defaultdict
import hashlib,json,math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
import pymupdf
from rasterio.features import rasterize
from scipy import ndimage

from voxel_mapper.source_gradient_gables import build
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(gradient,source_partial,gable,profile,preview,components,views,corpus,output):
    gradient,source_partial,gable,profile,preview,components,views,corpus,output=map(Path,(gradient,source_partial,gable,profile,preview,components,views,corpus,output))
    evidence=json.loads((gradient/'source-gradient-gables.json').read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(source_partial,gable,profile,preview,components,views,corpus,temp,max_checks=evidence['contract']['max_checks']);fresh.pop('directory')
        assert digest(fresh)==digest(evidence)
    parent=json.loads((gable/'gable-roof-review.json').read_text());originals={r['view_id']:r for r in parent['gable_views']}
    sources=json.loads((views/'view-candidates.json').read_text());lookup={v['id']:v for page in sources['pages'] for v in page['views']}
    pairs={}
    for row in evidence['views']:
        original=originals[row['view_id']];assert digest(original['source_exclusions'])==row['source_exclusions_sha256']
        image=views/lookup[row['view_id']]['render']['png'];assert file_hash(image)==row['source_png_sha256']
        with Image.open(image) as im:gray=np.asarray(im.convert('L'))
        records=original['source_exclusions']['records'];mask=rasterize([(r['geometry_pixels'],1) for r in records],out_shape=gray.shape,all_touched=True)>0 if records else np.zeros_like(gray,bool)
        assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==original['source_exclusions']['source_mask_sha256']
        gx=ndimage.sobel(gray.astype(float),axis=1);gy=ndimage.sobel(gray.astype(float),axis=0)
        orientation=(np.degrees(np.arctan2(-gx,gy))+90)%180-90
        for scan in row['variants']:
            eligible=(gray<250)&~mask&(abs(orientation)>=15)&(abs(orientation)<=65)&(np.hypot(gx,gy)>=scan['gradient_cutoff'])
            y,x=np.nonzero(eligible);angles=orientation[y,x];lines={l['id']:l for l in scan['lines']}
            assert len(x)==scan['eligible_source_edge_pixels']
            assert hashlib.sha256(gray.tobytes()).hexdigest()==scan['source_gray_sha256']
            for line in scan['lines']:
                points=line['source_pixels'];xx=np.array([p['x'] for p in points]);yy=np.array([p['y'] for p in points]);fit=xx%2==0
                assert eligible[yy,xx].all();assert all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in points)
                assert 24<=xx.max()-xx.min()<64 and len(xx)>=24 and min(fit.sum(),(~fit).sum())>=8
                columns=np.unique(xx);assert np.diff(columns).max()<=4
                assert line['unsupported_column_intervals']==[[int(a+1),int(b)] for a,b in zip(columns[:-1],columns[1:]) if b>a+1]
                # Separate covariance formula; every original point keeps its original role.
                dx=xx[fit]-xx[fit].mean();slope=float(dx@(yy[fit]-yy[fit].mean())/(dx@dx));intercept=float(yy[fit].mean()-slope*xx[fit].mean())
                assert abs(slope-line['slope'])<1e-10 and abs(intercept-line['intercept'])<1e-8
                residual=abs(slope*xx+intercept-yy)/np.hypot(slope,1)
                assert abs(residual[fit].max()-line['fit_max_normal_residual_pixels'])<1e-8 and abs(residual[~fit].max()-line['check_max_normal_residual_pixels'])<1e-8
                assert residual.max()<=3+1e-9
                for seed in line['hough_seeds']:
                    rad=np.radians(seed['angle_degrees']);normal=y*np.cos(rad)-x*np.sin(rad);window=abs(angles-seed['angle_degrees'])<=12
                    assert np.count_nonzero(window&(np.rint(normal)==seed['normal_offset_pixels']))==seed['votes']
                    ids=np.flatnonzero(window&(abs(normal-seed['normal_offset_pixels'])<=1.5));ids=ids[np.lexsort((y[ids],x[ids]))]
                    assert hashlib.sha256(np.asarray(sorted((y[ids]*gray.shape[1]+x[ids]).tolist()),dtype='<u8').tobytes()).hexdigest()==seed['whole_seed_membership_sha256']
                    groups=[];current=[];last=None
                    for i in ids:
                        if last is not None and x[i]-last>4:groups.append(current);current=[]
                        current.append(int(i));last=x[i]
                    if current:groups.append(current)
                    selected=[g for g in groups if [int(x[g[0]]),int(x[g[-1]])]==seed['local_group_source_x_interval']]
                    assert len(selected)==1
                    assert list(zip(x[selected[0]].tolist(),y[selected[0]].tolist()))==list(zip(xx.tolist(),yy.tolist()))
                    checked['whole_original_hough_groups']+=1
                assert not line['source_gaps_filled'] and line['source_points_removed_after_fit']==0
                checked['original_gradient_source_pixels']+=len(points);checked['separate_covariance_fits']+=1
            for anchor in scan['anchor_reviews']:
                old=next(v for v in original['variants'] if v['threshold']==anchor['source_parent_ink_threshold']);old_lines={l['id']:l for l in old['lines']}
                already={p[k] for p in old['gable_pairs'] for k in ('left_line_id','right_line_id')}
                assert anchor['source_unpaired_long_line_ids']==[l['id'] for l in old['lines'] if l['id'] not in already]
                for p in anchor['pairs']:
                    long=old_lines[p['source_long_line_id']];short=lines[p['source_short_line_id']];assert long['id'] not in already
                    left,right=(long,short) if long['slope']<0 else (short,long)
                    point=np.linalg.solve([[-left['slope'],1.],[-right['slope'],1.]],[left['intercept'],right['intercept']])
                    assert np.allclose(point,p['inferred_ridge_pixel'],rtol=0,atol=1e-9)
                    assert abs((row['printed_level_pixel']-point[1])*row['nominal_metres_per_pixel']-p['nominal_ridge_height_m'])<1e-9
                    ends=[abs(point[0]-left['source_x_interval'][1]),abs(point[0]-right['source_x_interval'][0])]
                    pitch=abs(left['pitch_magnitude_degrees']-right['pitch_magnitude_degrees'])
                    assert np.allclose(ends,p['source_ridge_end_errors_pixels'],rtol=0,atol=1e-9)
                    assert abs(pitch-p['pitch_difference_degrees'])<1e-9
                    assert (p['status']=='conditional_partial_gable_source_support')==(max(ends)<=12 and pitch<=2)
                    assert p['source_parent_ink_threshold']==anchor['source_parent_ink_threshold'] and p['source_gradient_cutoff']==scan['gradient_cutoff']
                    assert p['complete_wing_mesh'] is p['independent_depth_measurement_m'] is None and not p['source_long_line_refitted']
                    pairs[p['id']]=p;checked['independent_partial_intersections']+=1
        for c in row['contrast_checks']+row['anchor_checks']:
            a,b=[pairs[k] for k in c['source_pair_ids']]
            distance=float(np.linalg.norm(np.array(a['inferred_ridge_pixel'])-b['inferred_ridge_pixel']))
            errors=[abs(a[k]-b[k]) for k in ('left_pitch_degrees','right_pitch_degrees')]
            assert abs(distance-c['ridge_distance_source_pixels'])<1e-9 and errors==c['pitch_differences_degrees']
            assert (c['status']=='source_variant_measurements_agree')==(distance<=4 and max(errors)<=2)
            assert c['original_source_pixels_can_be_shared'] and not c['independent_survey_checks'] and not c['lines_refitted']
            checked['source_variant_comparisons']+=1
        supported=all(any(c['source_parent_ink_threshold']==t and c['status']=='source_variant_measurements_agree' for c in row['contrast_checks']) for t in (220,235))
        assert (row['source_contrast_status']=='pairwise_source_contrast_support_with_both_parent_anchors')==supported
    report=json.loads((components/'component-report.json').read_text());invs={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    original_strokes={};directions={}
    for review in evidence['direction_reviews']:
        inv=invs[review['view_id']];key=(inv['document_sha256'],inv['page']);source=corpus/'files'/(key[0]+'.pdf');assert file_hash(source)==key[0]
        if key not in original_strokes:
            index=defaultdict(list)
            with pymupdf.open(source) as doc:
                page=doc[key[1]-1];matrix=native_inverse(page)
                for drawing in page.get_drawings():
                    for item in drawing['items']:
                        if item[0]=='l':edges=[item[1:]]
                        elif item[0]=='re':
                            box=item[1];points=[box.tl,box.tr,box.br,box.bl,box.tl];edges=list(zip(points[:-1],points[1:]))
                        elif item[0]=='qu':
                            q=item[1];points=[q.ul,q.ur,q.lr,q.ll,q.ul];edges=list(zip(points[:-1],points[1:]))
                        else:continue
                        for a,b in edges:
                            pts=np.array([list(a*matrix),list(b*matrix)])
                            for ordered in (pts,pts[::-1]):index[tuple(np.round(ordered.ravel(),4))].append(ordered)
            original_strokes[key]=index
        eligible=set()
        for component in inv['source_components']:
            g=component['geometry']
            if g['type']=='LineString' and len(g['coordinates'])==2 and component['rendering_status']=='supported_straight_unclipped_polyline' and not component['curve_approximation']['cubic_segments']:
                pts=np.array(g['coordinates'])
                if np.linalg.norm(pts[1]-pts[0])*inv['nominal_metres_per_pdf_point']>=1:eligible.add(component['id'])
        recovered=set()
        for cohort in review['cohorts']:
            assert cohort['direction_witness_source_component_id']==min(l['source_component_id'] for l in cohort['lines'])
            witness=next(l for l in cohort['lines'] if l['source_component_id']==cohort['direction_witness_source_component_id'])
            assert witness['source_unit_vector']==cohort['source_direction_unit_vector']
            assert (cohort['status']=='repeated_source_plan_direction')==(len(cohort['lines'])>=3)
            for line in cohort['lines']:
                component=next(c for c in inv['source_components'] if c['id']==line['source_component_id']);assert digest(component)==line['source_component_sha256']
                pts=np.array(line['source_endpoints_pdf_native']);assert component['geometry']['coordinates']==line['source_endpoints_pdf_native']
                assert any(np.allclose(pts,v,rtol=0,atol=1e-6) for v in original_strokes[key][tuple(np.round(pts.ravel(),4))])
                d=pts[1]-pts[0];length=np.linalg.norm(d)
                assert np.allclose(d/length,line['source_unit_vector'],rtol=0,atol=1e-12)
                assert abs(length*inv['nominal_metres_per_pdf_point']-line['nominal_source_length_m'])<1e-10
                angle=math.degrees(math.atan2(d[1],d[0]))%180
                assert int(round(angle))%180==cohort['source_direction_bin_degrees'];assert not line['source_points_moved']
                recovered.add(line['source_component_id']);checked['original_native_plan_lines']+=1
            directions[cohort['id']]=cohort
        assert recovered==eligible
    buildings=json.loads((components/report['building_facade_links']['file']).read_text());artwork=json.loads((components/report['artwork_scale_controls']['file']).read_text())
    artifacts={a['id']:a for a in artwork['pairs']};contexts={c['id']:c for c in evidence['projection_contexts']}
    targets={(t['pair_id'],tuple(t['key'])):t for t in json.loads((preview/'facade-preview.json').read_text())['target_marker_checks']}
    for c in contexts.values():
        record=next(r for r in buildings['frames'] if r['target_elevation_view_ids']==[c['elevation_view_id']] and any(f['id']==c['source_frame_id'] for f in r['frame_review']['frames']))
        frame=next(f for f in record['frame_review']['frames'] if f['id']==c['source_frame_id']);a=artifacts[c['fixed_artwork_pair_id']]
        assert digest(frame)==c['source_frame_sha256'] and digest(a)==c['fixed_artwork_pair_sha256']
        assert targets[(a['id'],tuple(record['target_view_key_candidate']))]['status']=='fixed_non_target_layout_agrees_at_target_annotation'
        axis=np.array(frame['diagnostic_axis'])@np.linalg.inv(np.array(a['reference_to_subject_linear_row_matrix']));axis/=np.linalg.norm(axis)
        assert np.allclose(axis,c['source_view_horizontal_axis_in_roof_pdf'],rtol=0,atol=1e-12)
        assert not c['physical_building_correspondence_verified'] and not c['plan_translation_applied']
        checked['fixed_source_projection_contexts']+=1
    for c in evidence['plan_direction_checks']:
        context=contexts[c['context_id']];a=artifacts[context['fixed_artwork_pair_id']]
        f=np.array(directions[c['floor_direction_id']]['source_direction_unit_vector'])@np.linalg.inv(np.array(a['reference_to_subject_linear_row_matrix']));f/=np.linalg.norm(f)
        r=np.array(directions[c['roof_direction_id']]['source_direction_unit_vector']);difference=math.degrees(math.atan2(abs(float(np.linalg.det(np.array([f,r])))),abs(float(f@r))))
        assert abs(difference-c['axis_difference_degrees'])<1e-6
        assert (c['status']=='source_plan_directions_agree')==(difference<=1)
        assert not c['source_lines_refitted'] and not c['eaves_or_depth_established'];checked['floor_roof_direction_comparisons']+=1
    for p in evidence['pitch_projection_diagnostics']:
        context=contexts[p['context_id']];pair=pairs[p['source_pair_id']];v=np.array(directions[p['roof_direction_id']]['source_direction_unit_vector'])
        axis=np.array(context['source_view_horizontal_axis_in_roof_pdf']);fraction=min(1.,abs(float(v@axis)))
        assert abs(fraction-p['projected_width_fraction'])<1e-12
        expected=[None,None] if fraction<=math.sin(math.radians(5)) else [math.degrees(math.atan2(math.sin(math.radians(pair[k]))*fraction,math.cos(math.radians(pair[k])))) for k in ('left_pitch_degrees','right_pitch_degrees')]
        for a,b in zip(expected,p['conditional_deprojected_pitch_degrees']):
            assert a is b is None or a is not None and b is not None and abs(a-b)<1e-10
        assert (p['status']=='edge_on_direction_pitch_withheld')==(expected[0] is None)
        assert p['wing_depth_m'] is p['eave_endpoints'] is None and not p['true_pitch_verified'] and not p['physical_plan_elevation_match_verified']
        checked['conditional_pitch_projection_diagnostics']+=1
    assert not evidence['previous_binary_threshold_hold_overridden'] and not evidence['parent_models_changed'] and evidence['new_roof_models']==[]
    assert evidence['accepted_physical_components']==evidence['world_geometry_additions']==evidence['training_labels_generated']==0
    result={'version':'source-gradient-gable-audit-v1','status':'passed','fresh_replay_identical':True,
        'source_review_sha256':file_hash(gradient/'source-gradient-gables.json'),'source_partial_sha256':file_hash(source_partial/'partial-gables.json'),
        'source_parent_roof_sha256':file_hash(gable/'gable-roof-review.json'),'counts':evidence['counts'],'checked':dict(checked),
        'scope':'Grayscale source consistency and conditional projection diagnostics, no eave/depth/building match, true pitch or new mesh acceptance.'}
    atomic_json(output,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('gradient','source-partial','gable','profile','preview','components','views','corpus','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit(a.gradient,a.source_partial,a.gable,a.profile,a.preview,a.components,a.views,a.corpus,a.output)))
