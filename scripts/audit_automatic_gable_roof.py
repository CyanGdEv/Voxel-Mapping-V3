"""Independent original-line, raster-fit, model geometry and source gable audit."""
import argparse
from collections import Counter
import hashlib,json,math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
import pymupdf
from rasterio.features import rasterize
from scipy import ndimage

from voxel_mapper.automatic_gable_roof import build
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json,file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(gable,profile,preview,components,views,corpus,output):
    gable,profile,preview,components,views,corpus,output=map(Path,(gable,profile,preview,components,views,corpus,output))
    evidence=json.loads((gable/'gable-roof-review.json').read_text());checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(profile,preview,components,views,corpus,temp,max_checks=evidence['contract']['max_checks']);fresh.pop('directory')
        assert digest(evidence)==digest(fresh)
    assert evidence['world_geometry_additions']==evidence['accepted_physical_components']==evidence['training_labels_generated']==0
    assert not evidence['world_placement_eligible'] and not evidence['physical_scale_verified'] and not evidence['physical_roof_identity_verified']
    report=json.loads((components/'component-report.json').read_text())
    invs={r['view_id']:json.loads((components/r['file']).read_text()) for r in report['results']}
    buildings=json.loads((components/report['building_facade_links']['file']).read_text())
    artwork=json.loads((components/report['artwork_scale_controls']['file']).read_text())
    source_pairs={p['id']:p for p in artwork['pairs']}
    source_targets={(r['pair_id'],tuple(r['key'])):r for r in json.loads((preview/'facade-preview.json').read_text())['target_marker_checks']}
    previous=json.loads((profile/'facade-profile.json').read_text());profiles={g['id']:g for g in previous['profiles']}
    height_lookup={}
    for row in evidence['long_profile_reviews']:
        group=profiles[row['source_profile_id']]
        for h in row['heights']:
            if h['status']!='source_long_roof_panel_height_hypothesis':continue
            variant=next(v for v in group['variants'] if v['threshold']==h['threshold'])
            cohort=[r for r in variant['roof_source_regions'] if r['label'] in h['source_cohort_region_ids']]
            assert digest(cohort)==h['source_cohort_records_sha256']
            assert all(r['bounds_pixels'][1]==h['source_cohort_bounds_y'][0] and r['bounds_pixels'][3]==h['source_cohort_bounds_y'][1] for r in cohort)
            with Image.open(profile/variant['roof_mask_receipt']['file']) as image:mask=np.asarray(image)>0
            top=int(np.nonzero(mask)[0].min());mpp=group['nominal_metres_per_source_pixel'];level=group['printed_level_pixel']
            assert top==h['source_ridge_grid_y'];assert (level-top)*mpp==h['nominal_ridge_height_m']
            assert (level-h['source_cohort_bounds_y'][1])*mpp==h['nominal_eave_height_m']
            assert not h['physical_roof_edge_roles_verified'];height_lookup[h['id']]=h;checked['source_long_panel_height_witnesses']+=1
    plans={p['id']:p for p in evidence['plan_reviews']};triples={}
    original_cache={}
    for plan in evidence['plan_reviews']:
        inv=invs[plan['source_view_id']];sha=inv['document_sha256'];key=(sha,inv['page'])
        if key not in original_cache:
            path=corpus/'files'/(sha+'.pdf');assert file_hash(path)==sha
            with pymupdf.open(path) as doc:
                page=doc[inv['page']-1];matrix=native_inverse(page);original=[]
                for path in page.get_drawings():
                    if path['type'] not in ('s','fs'):continue
                    for item in path.get('items',[]):
                        if item[0]=='l':original.append([list(p*matrix) for p in item[1:]])
            original_cache[key]=original
        normal=np.array(plan['source_normal_pdf_native']);axis=np.array(plan['source_axis_pdf_native']);unit=inv['nominal_metres_per_pdf_point']
        lookup={r['id']:r for r in plan['lines']}
        for line in plan['lines']:
            component=next(c for c in inv['source_components'] if c['id']==line['source_component_id'])
            assert digest(component)==line['source_component_sha256']
            points=np.array(line['source_endpoints_pdf_native'])
            assert any(np.allclose(points,np.array(p),rtol=0,atol=1e-6) or np.allclose(points,np.array(p)[::-1],rtol=0,atol=1e-6) for p in original_cache[key])
            assert abs(np.linalg.norm(points[1]-points[0])*unit-line['nominal_length_m'])<1e-10
            along=points@axis*unit;cross=points@normal*unit
            assert sorted(along.tolist())==line['along_interval_nominal_m']
            assert cross[np.argmin(along)]==line['cross_at_source_start_nominal_m'];assert not line['source_points_moved']
            checked['original_native_plan_line_receipts']+=1
        for triple in plan['triples']:
            rows=[lookup[k] for k in triple['source_line_ids']];offsets=[r['cross_at_source_start_nominal_m'] for r in rows]
            assert offsets==triple['source_offsets_nominal_m'];assert offsets[1]-offsets[0]==triple['nominal_left_run_m']
            assert offsets[2]-offsets[1]==triple['nominal_right_run_m'];assert not triple['symmetry_forced']
            assert not triple['physical_line_roles_verified'];assert min(triple['nominal_left_run_m'],triple['nominal_right_run_m'])>=1 and abs(triple['nominal_left_run_m']-triple['nominal_right_run_m'])<=.25
            assert max(max(r['along_interval_nominal_m'][i] for r in rows)-min(r['along_interval_nominal_m'][i] for r in rows) for i in (0,1))<=.25
            triples[triple['id']]=triple;checked['independent_parallel_triples']+=1
    source=json.loads((views/'view-candidates.json').read_text());view_lookup={v['id']:v for p in source['pages'] for v in p['views']}
    pairs={}
    for row in evidence['gable_views']:
        view=view_lookup[row['view_id']]
        assert file_hash(views/view['render']['png'])==row['source_png_sha256']
        with Image.open(views/view['render']['png']) as image:gray=np.asarray(image.convert('L'))
        exclusions=row['source_exclusions'];mask=rasterize([(r['geometry_pixels'],1) for r in exclusions['records']],out_shape=gray.shape,all_touched=True)>0 if exclusions['records'] else np.zeros_like(gray,bool)
        assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==exclusions['source_mask_sha256'];assert not exclusions['source_image_changed']
        with pymupdf.open(corpus/'files'/(row['document_sha256']+'.pdf')) as doc:
            traces=doc[row['page']-1].get_texttrace()
            for r in exclusions['records']:
                if 'source_texttrace_index' in r:assert list(traces[r['source_texttrace_index']]['bbox'])==r['source_bbox_unrotated_mupdf']
                else:assert digest(next(c for c in invs[row['view_id']]['source_components'] if c['id']==r['source_component_id']))==r['source_component_sha256']
        for variant in row['variants']:
            dark=gray<variant['threshold'];gx=ndimage.sobel(dark.astype(float),axis=1);gy=ndimage.sobel(dark.astype(float),axis=0)
            orientation=(np.degrees(np.arctan2(-gx,gy))+90)%180-90
            eligible=dark&~mask&(np.abs(orientation)>=15)&(np.abs(orientation)<=65)&(np.hypot(gx,gy)>=1)
            yy,xx=np.nonzero(eligible);angles=orientation[yy,xx]
            assert len(xx)==variant['eligible_source_edge_pixels'];line_lookup={line['id']:line for line in variant['lines']}
            for line in variant['lines']:
                points=line['source_pixels'];x=np.array([p['x'] for p in points]);y=np.array([p['y'] for p in points]);fit=x%2==0;check=~fit
                assert eligible[y,x].all();assert all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in points)
                # Independent covariance solution, without the kernel's least-squares call.
                centered=x[fit]-x[fit].mean();slope=float(centered@(y[fit]-y[fit].mean())/(centered@centered));intercept=float(y[fit].mean()-slope*x[fit].mean())
                assert abs(slope-line['slope'])<1e-10 and abs(intercept-line['intercept'])<1e-8
                residual=np.abs(slope*x+intercept-y)/np.hypot(slope,1.)
                assert abs(residual[fit].max()-line['fit_max_normal_residual_pixels'])<1e-8
                assert abs(residual[check].max()-line['check_max_normal_residual_pixels'])<1e-8
                ids=set((y*gray.shape[1]+x).tolist())
                for seed in line['hough_seeds']:
                    rad=np.deg2rad(seed['angle_degrees']);normal=yy*np.cos(rad)-xx*np.sin(rad)
                    window=np.abs(angles-seed['angle_degrees'])<=12
                    assert int(np.count_nonzero(window&(np.rint(normal)==seed['normal_offset_pixels'])))==seed['votes']
                    members=window&(np.abs(normal-seed['normal_offset_pixels'])<=1.5)
                    assert set((yy[members]*gray.shape[1]+xx[members]).tolist())==ids;checked['original_hough_seed_receipts']+=1
                assert not line['source_gaps_filled'] and not line['physical_roof_edge_verified']
                checked['original_slope_pixels']+=len(points);checked['source_line_fit_and_check_solutions']+=1
            for pair in variant['gable_pairs']:
                a=line_lookup[pair['left_line_id']];b=line_lookup[pair['right_line_id']]
                x,y=np.linalg.solve(np.array([[-a['slope'],1.],[-b['slope'],1.]]),[a['intercept'],b['intercept']])
                assert np.allclose([x,y],pair['inferred_ridge_pixel'],rtol=0,atol=1e-9)
                assert abs((row['printed_level_pixel']-y)*row['nominal_metres_per_pixel']-pair['nominal_ridge_height_m'])<1e-9
                assert not pair['ridge_is_original_source_vertex'] and pair['ridge_is_line_intersection_hypothesis']
                assert pair['independent_depth_measurement_m'] is None;pairs[(row['view_id'],variant['threshold'],pair['id'])]=pair
                checked['independent_gable_intersections']+=1
    models={m['id']:m for m in evidence['models']}
    for model in evidence['models']:
        h=height_lookup[model['source_height_review_id']];triple=triples[model['source_plan_triple_id']];mesh=model['mesh']
        length=h['nominal_length_m'];a=triple['nominal_left_run_m'];b=triple['nominal_right_run_m'];depth=a+b;y0=-depth/2;yr=y0+a;eave=h['nominal_eave_height_m'];ridge=h['nominal_ridge_height_m']
        original_frame=next(f for r in buildings['frames'] if r['target_elevation_view_ids']==[model['source_long_view_id']] for f in r['frame_review']['frames'] if f['id']==model['source_long_frame_id'])
        assert original_frame['diagnostic_axis']==model['source_long_frame_axis_pdf_native']
        original_pair=source_pairs[model['fixed_artwork_pair_id']]
        direction=np.array(original_frame['diagnostic_axis'])@np.linalg.inv(np.array(original_pair['reference_to_subject_linear_row_matrix']));direction/=np.linalg.norm(direction)
        assert np.allclose(direction,plans[model['source_plan_review_id']]['source_axis_pdf_native'],rtol=0,atol=1e-12)
        assert abs(model['source_nominal_depth_m']-depth)<1e-12
        expected=[[-length/2,y0,eave],[length/2,y0,eave],[-length/2,yr,ridge],[length/2,yr,ridge],[-length/2,depth/2,eave],[length/2,depth/2,eave]]
        assert np.allclose(expected,mesh['vertices'],rtol=0,atol=1e-12)
        assert abs(math.tan(math.radians(mesh['left_pitch_degrees']))-(ridge-eave)/a)<1e-12
        assert abs(math.tan(math.radians(mesh['right_pitch_degrees']))-(ridge-eave)/b)<1e-12
        assert mesh['triangles']==[[0,1,3],[0,3,2],[2,3,5],[2,5,4]]
        assert mesh['continuous_roof_planes_are_assumed'] and not mesh['source_mask_holes_incorporated']
        assert mesh['wall_mesh'] is mesh['fascia_mesh'] is None and mesh['openings_carved']==0 and not mesh['world_placement_eligible']
        checked['conditional_pitched_roof_models']+=1;checked['pitched_roof_triangles']+=4
    for check in evidence['gable_checks']:
        model=models[check['model_id']];mesh=model['mesh'];pair=pairs[(check['view_id'],check['threshold'],check['source_gable_pair_id'])]
        difference=pair['nominal_ridge_height_m']-mesh['vertices'][2][2]
        errors=[abs(pair['left_pitch_degrees']-mesh['left_pitch_degrees']),abs(pair['right_pitch_degrees']-mesh['right_pitch_degrees'])]
        assert abs(difference-check['ridge_difference_nominal_m'])<1e-10 and np.allclose(errors,check['pitch_differences_degrees'],rtol=0,atol=1e-10)
        passed=abs(difference)<=.25 and max(errors)<=1.
        assert (check['status']=='independent_source_gable_heights_and_pitches_agree')==passed
        assert not check['model_refitted_to_gable'] and not check['physical_correspondence_verified']
        frames=[f['id'] for r in buildings['frames'] if r['target_elevation_view_ids']==[check['view_id']] and r['target_view_key_candidate'][:2]==model['source_project_sheet_key']
            for f in r['frame_review']['frames'] if abs(float(np.array(f['diagnostic_axis'])@model['source_long_frame_axis_pdf_native']))<=math.sin(math.radians(5))]
        targets=[source_targets.get((model['fixed_artwork_pair_id'],tuple(r['target_view_key_candidate']))) for r in buildings['frames'] if r['target_elevation_view_ids']==[check['view_id']]]
        target_ok=any(t and t['status']=='fixed_non_target_layout_agrees_at_target_annotation' for t in targets)
        assert frames==check['source_perpendicular_frame_ids'] and target_ok==check['target_annotation_check_passed']
        assert check['source_gable_orientation_link_supported']==(bool(frames) and target_ok)
        checked['independent_gable_model_checks']+=1
    for model in evidence['models']:
        supports=[c for c in evidence['gable_checks'] if c['model_id']==model['id'] and c['status']=='independent_source_gable_heights_and_pitches_agree']
        assert model['independent_gable_checks_passed']==all(any(c['threshold']==t and c['source_gable_orientation_link_supported'] for c in supports) for t in (220,235))
    result={'version':'automatic-gable-roof-audit-v1','status':'passed','fresh_replay_identical':True,
        'source_review_sha256':file_hash(gable/'gable-roof-review.json'),'counts':evidence['counts'],'checked':dict(checked),
        'world_geometry_additions':0,'scope':'Conditional source-plan/long-view roof, checked against separate end-elevation fits; no physical identity, as-built, registration or full-building acceptance.'}
    atomic_json(output,result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('gable','profile','preview','components','views','corpus','output'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();print(json.dumps(audit(a.gable,a.profile,a.preview,a.components,a.views,a.corpus,a.output)))
