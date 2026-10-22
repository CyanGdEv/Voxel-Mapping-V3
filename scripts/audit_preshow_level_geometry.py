"""Fresh replay and independent original glyph, pixel, height and mesh checks."""
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
from scipy.spatial import cKDTree
from voxel_mapper.preshow_level_geometry import build
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence, references, topology, gradient, components, views, corpus, source_catalogue, additional_pdfs, output):
    evidence, references, topology, gradient, components, views, corpus, source_catalogue, additional_pdfs, output = map(Path,
        (evidence,references,topology,gradient,components,views,corpus,source_catalogue,additional_pdfs,output))
    path=evidence/'preshow-level-geometry.json'; result=json.loads(path.read_text()); checked=Counter()
    with tempfile.TemporaryDirectory() as temp:
        fresh=build(references,topology,gradient,components,views,corpus,source_catalogue,additional_pdfs,temp,max_checks=result['contract']['max_checks']); fresh.pop('directory')
        assert digest(fresh)==digest(result)
    assert result['status']=='conditional_preshow_level_geometry_only'
    bindings={}; pairs={}; caps={}; view_by_pair={}; witnesses={w['source_pair_id']:w for w in result['old_source_witnesses']}
    for lp in result['level_pages']:
        original=additional_pdfs/(lp['document_sha256']+'.pdf'); assert file_hash(original)==lp['document_sha256']
        with pymupdf.open(original) as doc:
            page=doc[lp['page']-1]; traces=page.get_texttrace(); paths=page.get_drawings(extended=True)
            fragments={f['id']:f for group in lp['fragments'].values() for f in group}
            for f in fragments.values():
                assert len(f['trace_indices'])==1; trace=traces[f['trace_indices'][0]]; chars=[trace['chars'][i] for i in f['character_indices']]
                assert ''.join(chr(c[0]) for c in chars).strip()==f['text']
                assert [list(c[2]) for c in chars]==f['glyph_origins_page_points']
                rect=pymupdf.Rect(chars[0][3])
                for c in chars[1:]:rect|=pymupdf.Rect(c[3])
                assert np.allclose(list(rect),f['bbox_page_points'],rtol=0,atol=1e-6); checked['original_glyph_fragments']+=1
            for p in lp['split_pairs']:
                assert fragments[p['label_fragment_id']]['text']==p['level_label_candidate']
                assert float(fragments[p['value_fragment_id']]['text'].replace(' ',''))==p['value_m_candidate']
                for d in p['numeric_duplicate_candidates']:
                    expected=int(fragments[d['fragment_id']]['text'])/1000-p['value_m_candidate']
                    assert abs(expected-d['difference_from_decimal_m'])<1e-12 and not d['assumed_numeric_units_verified']
                assert not p['text_fragments_joined_or_moved']; checked['separate_level_fragment_pairs']+=1
            for marker in lp['legacy_marker_review']['records']:
                assert list(paths[marker['source_circle_path_ordinal']]['rect']*page.rotation_matrix)==marker['circle_bbox_display_points']
                for line in marker['datum_line_candidates']:
                    item=paths[line['source_path_ordinal']]['items'][0]; assert item[0]=='l'
                    assert [list(p*page.rotation_matrix) for p in item[1:]]==line['display_endpoints']; checked['original_level_marker_leaders']+=1
        for b in lp['marker_bindings']:
            if b['status']=='unverified_source_level_marker_binding':
                assert len(b['label_candidates'])==len(b['source_datum_line_candidates'])==len(b['view_candidates'])==1
                assert b['label']['glyph_screen_status']=='raster_consistent_candidate'
                assert b['datum_y_display_points']==b['source_datum_line_candidates'][0]['display_endpoints'][0][1]
            assert not b['legacy_marker_record_changed'] and not b['physical_floor_role_verified']; bindings[b['id']]=b
        for c in lp['relative_checks']:
            a,b=[bindings[i] for i in c['source_binding_ids']]
            error=(b['datum_y_display_points']-a['datum_y_display_points'])*a['nominal_metres_per_pdf_point']-a['label']['value_m_candidate']+b['label']['value_m_candidate']
            assert abs(error-c['difference_residual_nominal_m'])<1e-10
            assert (c['status']=='source_relative_level_scale_agrees')==(abs(error)<=.01); checked['independent_relative_level_checks']+=1
    for view in result['gable_views']:
        assert file_hash(references/view['png'])==view['png_sha256']
        with Image.open(references/view['png']) as im:gray=np.asarray(im.convert('L'))
        records=view['source_exclusions']['records']; mask=rasterize([(r['geometry_pixels'],1) for r in records],out_shape=gray.shape,all_touched=True)>0 if records else np.zeros_like(gray,bool)
        assert hashlib.sha256(mask.astype('uint8').tobytes()).hexdigest()==view['source_exclusions']['source_mask_sha256']
        for scan in view['variants']:
            ink=gray<scan['threshold']; gx=ndimage.sobel(ink.astype(float),axis=1); gy=ndimage.sobel(ink.astype(float),axis=0)
            angle=(np.degrees(np.arctan2(-gx,gy))+90)%180-90; eligible=ink&~mask&(abs(angle)>=15)&(abs(angle)<=65)&(np.hypot(gx,gy)>=1)
            yy,xx=np.nonzero(eligible); angles=angle[yy,xx]; lines={l['id']:l for l in scan['lines']}
            for line in lines.values():
                x=np.array([p['x'] for p in line['source_pixels']]); y=np.array([p['y'] for p in line['source_pixels']]); fit=x%2==0
                assert eligible[y,x].all() and all(p['gray']==gray[p['y'],p['x']] and p['role']==('fit' if p['x']%2==0 else 'check') for p in line['source_pixels'])
                dx=x[fit]-x[fit].mean(); slope=float(dx@(y[fit]-y[fit].mean())/(dx@dx)); intercept=float(y[fit].mean()-slope*x[fit].mean())
                assert abs(slope-line['slope'])<1e-10 and abs(intercept-line['intercept'])<1e-8
                for seed in line['hough_seeds']:
                    rad=math.radians(seed['angle_degrees']); normal=yy*math.cos(rad)-xx*math.sin(rad)
                    ids=np.flatnonzero((abs(angles-seed['angle_degrees'])<=12)&(abs(normal-seed['normal_offset_pixels'])<=1.5)); ids=ids[np.lexsort((yy[ids],xx[ids]))]
                    assert np.array_equal(x,xx[ids]) and np.array_equal(y,yy[ids]); checked['whole_hough_source_groups']+=1
                checked['original_slope_pixel_memberships']+=len(x)
            for cap in scan['source_fascia_columns']:
                x=cap['x']; y=np.array([p['y'] for p in cap['source_pixels']]); assert ((gray[y,x]<scan['threshold'])&~mask[y,x]).all()
                assert all(p['x']==x and p['gray']==gray[p['y'],x] for p in cap['source_pixels'])
                all_y=np.flatnonzero(ink[:,x]&~mask[:,x]); groups=np.split(all_y,np.flatnonzero(np.diff(all_y)>2)+1)
                matching=[g for g in groups if len(g) and [int(g[0]),int(g[-1])]==cap['source_y_interval_pixels']]
                assert len(matching)==1 and np.array_equal(y,matching[0]) and not cap['source_gaps_filled']
                caps[cap['id']]=cap; checked['whole_literal_fascia_columns']+=1; checked['original_fascia_pixel_memberships']+=len(y)
            for p in scan['gable_intersections']:
                left,right=[lines[p[k]] for k in ('left_line_id','right_line_id')]
                point=np.linalg.solve([[-left['slope'],1],[-right['slope'],1]],[left['intercept'],right['intercept']])
                assert np.allclose(point,p['inferred_ridge_pixel'],rtol=0,atol=1e-9)
                pairs[p['id']]=p; view_by_pair[p['id']]=view; checked['independent_gable_intersections']+=1
    variants={v['id']:v for v in result['source_cap_variants']}; endchecks={c['id']:c for c in result['endcap_checks']}
    parent=json.loads((references/'roof-reference-evidence.json').read_text())
    for variant in variants.values():
        context=next(c for c in result['contexts'] if c['id']==variant['context_id'])
        top=next(t for t in parent['source_topologies'] if t['view_id']==context['roof_view_id'])
        original=corpus/'files'/(top['document_sha256']+'.pdf'); assert file_hash(original)==top['document_sha256']
        endpoints=[]
        with pymupdf.open(original) as doc:
            page=doc[top['page']-1]; matrix=native_inverse(page)
            for drawing in page.get_drawings():
                for item in drawing['items']:
                    if item[0]=='l':endpoints.extend(list(p*matrix) for p in item[1:])
        native=np.array(variant['source_vertices_pdf_native']); assert max(cKDTree(endpoints).query(native)[0])<=1e-6
        axis=(native[3]-native[2])/np.linalg.norm(native[3]-native[2]); normal=np.array([-axis[1],axis[0]])
        local=np.c_[(native-native[2])@axis,(native-native[2])@normal]*top['nominal_metres_per_pdf_point']
        assert np.allclose(local,variant['local_horizontal_vertices_nominal_m'],rtol=0,atol=1e-10)
        lines={l['source_component_id']:l for l in top['lines']}
        for contact in variant['source_cap_contacts']:
            line=lines[contact['cap_source_id']]
            assert line['source_endpoints_pdf_native'][contact['cap_endpoint_index']]==contact['cap_endpoint_pdf_native']
            assert max(contact['ridge_to_cap_gap_pdf_points'],contact['cap_to_rail_gap_pdf_points'])<=1e-6
        checked['original_native_patch_vertices']+=len(native)
    for c in result['endcap_checks']:
        p=pairs[c['source_pair_id']]; view=view_by_pair[p['id']]; variant=variants[c['source_cap_variant_id']]
        runs=variant['native_runs_m'][::c['image_left_to_native_rail_orientation']]; x,y=p['inferred_ridge_pixel']; mpp=view['nominal_metres_per_pixel']
        predicted=[[x-runs[0]/mpp,y+math.tan(math.radians(p['left_pitch_degrees']))*runs[0]/mpp],[x+runs[1]/mpp,y+math.tan(math.radians(p['right_pitch_degrees']))*runs[1]/mpp]]
        assert np.allclose(predicted,c['predicted_corner_pixels'],rtol=0,atol=1e-9)
        errors=[[caps[i]['x']-q[0],caps[i]['source_y_interval_pixels'][0]-q[1]] for i,q in zip(c['source_fascia_column_ids'],predicted)]
        assert np.allclose(errors,c['source_corner_error_pixels'],rtol=0,atol=1e-9)
        assert (c['status']=='conditional_source_endcaps_agree')==(max(abs(v) for e in errors for v in e)<=4 and abs(p['left_pitch_degrees']-p['right_pitch_degrees'])<=2)
        checked['independent_endcap_comparisons']+=1
    for c in result['inter_sheet_height_checks']:
        p=pairs[c['source_pair_id']]; b=bindings[c['source_level_binding_id']]; view=view_by_pair[p['id']]; pd=view['pixel_to_display_matrix']
        height=((b['datum_y_display_points']-pd[5])/pd[3]-p['inferred_ridge_pixel'][1])*view['nominal_metres_per_pixel']; w=witnesses[c['old_source_pair_id']]
        error=height+b['label']['value_m_candidate']-w['nominal_ridge_height_above_source_level_m']-w['printed_level_value_m_candidate']
        assert abs(error-c['signed_source_ridge_height_difference_nominal_m'])<1e-9
        assert (c['status']=='conditional_inter_sheet_ridge_height_agrees')==(abs(error)<=.25)
        assert c['shared_printed_level_datum_assumed'] and not c['independent_survey_check']; checked['independent_inter_sheet_height_checks']+=1
    for model in result['conditional_roof_patches']:
        p=pairs[model['source_pair_id']]; b=bindings[model['source_level_binding_id']]; view=view_by_pair[p['id']]
        c=endchecks[model['source_endcap_check_id']]; variant=variants[model['source_cap_variant_id']]; pd=view['pixel_to_display_matrix']
        level_pixel=(b['datum_y_display_points']-pd[5])/pd[3]; mpp=view['nominal_metres_per_pixel']; ridge=(level_pixel-p['inferred_ridge_pixel'][1])*mpp
        eaves=[(level_pixel-q[1])*mpp for q in c['source_eave_top_pixels']][::model['image_left_to_native_rail_orientation']]
        expected=[[*q,z] for q,z in zip(variant['local_horizontal_vertices_nominal_m'],[eaves[0],eaves[0],ridge,ridge,eaves[1],eaves[1]])]
        assert np.allclose(expected,model['mesh']['vertices'],rtol=0,atol=1e-10)
        assert model['mesh']['triangles']==[[0,1,3],[0,3,2],[2,3,5],[2,5,4]]
        assert model['mesh']['source_cap_patch_only'] and not model['mesh']['complete_wing_mesh']
        assert model['mesh']['whole_source_rail_tails_left_unmeshed']==variant['source_rail_tails_left_unmeshed']
        assert not model['mesh']['world_placement_eligible']; checked['independent_partial_roof_meshes']+=1
    models={m['id']:m for m in result['conditional_roof_patches']}
    for c in result['threshold_checks']:
        a,b=[models[i] for i in c['source_model_ids']]
        errors=[float(np.linalg.norm(np.array(a['source_ridge_pixel'])-b['source_ridge_pixel'])),*[float(np.linalg.norm(np.array(p)-q)) for p,q in zip(a['source_eave_top_pixels'],b['source_eave_top_pixels'])]]
        assert abs(errors[0]-c['ridge_difference_pixels'])<1e-10 and np.allclose(errors[1:],c['source_endcap_differences_pixels'],rtol=0,atol=1e-10)
        assert (c['status']=='source_threshold_patch_measurements_agree')==(max(errors)<=4); checked['independent_threshold_comparisons']+=1
    receipt={'status':'passed','fresh_replay_identical':True,'review_sha256':file_hash(path),'source_reference_sha256':result['contract']['source_reference_sha256'],'checked':dict(checked)}
    atomic_json(output,receipt); return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('evidence','references','topology','gradient','components','views','corpus','source-catalogue','additional-pdfs','output'):p.add_argument('--'+name,type=Path,required=True)
    print(json.dumps(audit(**vars(p.parse_args()))))
