"""Complementary source-contrast fascia evidence and conditional observed-face strips."""
import copy
import json
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
from rasterio.features import rasterize
from . import pyramidal_roof_evidence as parent_pass
from . import source_gradient_fascia as fascia
from .automatic_opening_links import bounded_work
from .generation_cycles import atomic_json,file_hash
from .reconstruction_evidence_queue import digest

VERSION='conditional-source-contrast-pyramid-fascia-v1'


def stability(models,charge):
    keys=('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation');groups={};coverage=[];checks=[]
    for model in models:groups.setdefault(tuple(model[k] for k in keys),[]).append(model)
    for key,entries in groups.items():
        charge();configurations={f'{t}/{c}':[m['id'] for m in entries if (m['source_ink_threshold'],m['source_gradient_contrast'])==(t,c)] for t in (220,235) for c in (32,64)}
        for i,a in enumerate(entries):
            for b in entries[i+1:]:
                if (a['source_ink_threshold'],a['source_gradient_contrast'])==(b['source_ink_threshold'],b['source_gradient_contrast']):continue
                charge();height_errors=np.abs(np.array(a['mesh']['vertices'])[:,2]-np.array(b['mesh']['vertices'])[:,2])
                depth_errors=np.abs(np.array(a['observed_fascia_mesh']['observed_corner_depths_nominal_m'])-b['observed_fascia_mesh']['observed_corner_depths_nominal_m']) if a.get('observed_fascia_mesh') and b.get('observed_fascia_mesh') else None
                row={'source_model_ids':[a['id'],b['id']],'roof_vertex_height_differences_nominal_m':height_errors.tolist(),
                    'fascia_depth_differences_nominal_m':None if depth_errors is None else depth_errors.tolist(),
                    'status':'source_contrast_measurements_agree' if max(height_errors)<=4*a['nominal_metres_per_pixel'] and depth_errors is not None and max(depth_errors)<=4*a['nominal_metres_per_pixel'] else 'source_contrast_measurements_held',
                    'shared_source_pixels_are_not_independent_controls':True}
                row['id']=digest([VERSION,row]);checks.append(row)
                if len(checks)>8192:raise OverflowError('fascia_stability_comparison_budget')
        group_checks=[c for c in checks if c['source_model_ids'][0] in {m['id'] for m in entries}]
        row=dict(zip(keys,key));row.update(source_models_by_configuration=configurations,
            status='four_source_configurations_support_inspection' if all(configurations.values()) and group_checks and all(c['status']=='source_contrast_measurements_agree' for c in group_checks) else 'source_configuration_support_held',
            missing_configurations=[k for k,v in configurations.items() if not v],physical_acceptance_authorized=False)
        row['id']=digest([VERSION,row]);coverage.append(row)
    return coverage,checks


def open_joins(parent,models,graphs,junctions,charge):
    return parent_pass.join_checks(parent,models,graphs,junctions,charge)


def build(pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output,*,max_checks=100000):
    bounded_work(max_checks)
    pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output=map(Path,
        (pyramid,preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output))
    parent_path=pyramid/'pyramidal-roof-evidence.json';parent=json.loads(parent_path.read_text());parent_pin=file_hash(parent_path)
    parent_args=(preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs)
    def replay():
        with tempfile.TemporaryDirectory() as temp:
            fresh=parent_pass.build(*parent_args,temp,max_checks=parent['contract']['max_checks']);fresh.pop('directory')
            if digest(fresh)!=digest(parent):raise ValueError('Original pyramid source replay changed')
    replay()
    if parent['status']!='conditional_pyramidal_roof_evidence_only':raise ValueError('Complete original pyramid review required')
    ppath=preshow/'preshow-level-geometry.json';old=json.loads(ppath.read_text());pins={parent_path:parent_pin,ppath:parent['contract']['source_preshow_sha256']}
    for view in parent['new_source_views']:pins[references/view['png']]=view['png_sha256']
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (fascia,parent_pass)},
        'source_pyramid_sha256':parent_pin,'source_preshow_sha256':pins[ppath],'max_checks':max_checks,
        'configurations':[[t,c] for t in (220,235) for c in (32,64)]}
    fields=('edge_views','observed_faces','primary_silhouettes','source_corner_checks','source_corner_edge_checks','endcap_checks','cross_view_checks','models','configuration_coverage','stability_checks','open_join_checks','shared_cap_face_checks')
    result={k:[] for k in fields};result.update(contract=contract,status='conditional_source_gradient_fascia_only',checks=0,accepted_physical_components=0,world_geometry_additions=0,training_labels_generated=0,
        previous_source_holds_overridden=False,previous_roof_models_changed=False,wall_closure_authorized=False)
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('source_gradient_fascia_work_budget')
    try:
        bindings=[b for page in old['level_pages'] for b in page['marker_bindings'] if b['status']=='unverified_source_level_marker_binding']
        for context in parent['source_contexts']:
            if context['status']!='conditional_pyramid_source_view_context':continue
            target=context['target_candidates'][0];view=next((v for v in parent['new_source_views'] if v['view_id']==target['view_id']),None)
            if view is None:continue
            graph=next(g for g in parent['plan_graphs'] if g['view_id']==context['roof_view_id']);candidate=next(c for c in graph['candidates'] if c['id']==context['candidate_id'])
            face=fascia.observed_edges(candidate,context,graph['original_lines'],charge);face.update(context_id=context['id'],candidate_id=candidate['id']);face['id']=digest([VERSION,face]);result['observed_faces'].append(face)
            with Image.open(references/view['png']) as image:gray=np.asarray(image.convert('L')).copy()
            records=view['source_exclusions']['records'];mask=rasterize([(r['geometry_pixels'],1) for r in records],out_shape=gray.shape,all_touched=True)>0 if records else np.zeros_like(gray,bool)
            own=[b for b in bindings if b['view_key_candidate']==target['view_key_candidate']]
            relative=[c for p in old['level_pages'] for c in p['relative_checks'] if c['view_key_candidate']==target['view_key_candidate']]
            for threshold,contrast in contract['configurations']:
                edge=fascia.columns(gray,mask,threshold,contrast,charge);source_scan=next(s for s in view['variants'] if s['threshold']==threshold)
                scan={**source_scan,**edge};edge_view={k:copy.deepcopy(v) for k,v in view.items() if k!='variants'};edge_view['variants']=[scan];result['edge_views'].append(edge_view)
                silhouettes,ends,corners,edge_checks=parent_pass.silhouettes(candidate,context,edge_view,own,graph['nominal_metres_per_pdf_point'],charge)
                for check in edge_checks:
                    check['source_gradient_contrast']=contrast;check.pop('id');check['id']=digest([VERSION,check])
                result['endcap_checks'].extend(ends);result['source_corner_checks'].extend(corners);result['source_corner_edge_checks'].extend(edge_checks)
                for silhouette in silhouettes:
                    silhouette['source_gradient_contrast']=contrast;silhouette['source_recipe']='whole_original_horizontal_neighbour_contrast_columns';silhouette.pop('id');silhouette['id']=digest([VERSION,silhouette])
                result['primary_silhouettes'].extend(silhouettes)
                supplemental=[s for s in parent['supplemental_silhouettes'] if s['context_id']==context['id']]
                comparisons=parent_pass.comparisons(silhouettes,supplemental,charge);result['cross_view_checks'].extend(comparisons)
                for silhouette in silhouettes:
                    agreeing=[c['id'] for c in comparisons if c['source_silhouette_ids'][0]==silhouette['id'] and c['status']=='conditional_cross_view_pyramid_heights_agree']
                    if not agreeing or not relative or any(c['status']!='source_relative_level_scale_agrees' for c in relative):continue
                    model={**silhouette,'source_silhouette_id':silhouette['id'],'source_agreeing_cross_view_check_ids':agreeing,
                        'mesh':parent_pass.mesh(candidate,{**silhouette,'plan_unit':graph['nominal_metres_per_pdf_point']}),
                        'status':'conditional_roof_and_observed_fascia_inspection_only','observed_fascia_mesh':None}
                    end=next(c for c in ends if c['id']==model['source_endcap_check_id']);binding=next(b for b in own if b['id']==model['source_level_binding_id']);matrix=view['pixel_to_display_matrix']
                    if face['status']=='conditional_original_observed_edge':
                        model['observed_fascia_mesh']=fascia.fascia_mesh(candidate,model,{**silhouette,'source_level_pixel':(binding['datum_y_display_points']-matrix[5])/matrix[3]},end,scan['source_fascia_columns'],face['first_edge_candidates'][0]['source_edge_index'],graph['nominal_metres_per_pdf_point'])
                    model.pop('id');model['id']=digest([VERSION,model]);result['models'].append(model)
                    if len(result['models'])>256:raise OverflowError('source_fascia_model_budget')
        result['configuration_coverage'],result['stability_checks']=stability(result['models'],charge)
        result['open_join_checks']=open_joins(old,result['models'],parent['plan_graphs'],parent['source_junctions'],charge)
        for face in result['observed_faces']:
            for junction in parent['source_junctions']:
                if face['candidate_id']!=junction['pyramid_candidate_id']:continue
                charge();edge_ids={i for c in face['first_edge_candidates'] for i in c['source_perimeter_ids']}
                row={'source_observed_face_id':face['id'],'source_junction_id':junction['id'],
                    'observed_source_edge_ids':sorted(edge_ids),'shared_cap_source_id':junction['shared_original_cap_source_id'],
                    'observed_fascia_edge_is_shared_cap':junction['shared_original_cap_source_id'] in edge_ids,
                    'status':'shared_cap_fascia_evidence_still_required' if junction['shared_original_cap_source_id'] not in edge_ids else 'source_edge_matches_but_physical_closure_still_unverified',
                    'depth_transferred_to_shared_cap':False,'wall_or_join_mesh':None,'closure_authorized':False}
                row['id']=digest([VERSION,row]);result['shared_cap_face_checks'].append(row)
    except OverflowError as error:
        result.update({k:[] for k in fields});result.update(status='source_gradient_fascia_budget_withheld',reason=str(error))
    for path,pin in pins.items():
        if file_hash(path)!=pin:raise ValueError('Original fascia source changed during build')
    replay()
    result['counts']={k:len(result[k]) for k in fields};result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>64000000:raise ValueError('Source fascia output budget exceeded')
    root=output/digest(contract);path=root/'pyramid-fascia-evidence.json'
    if path.exists():
        if digest(json.loads(path.read_text()))!=digest(result):raise ValueError('Saved source fascia evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
