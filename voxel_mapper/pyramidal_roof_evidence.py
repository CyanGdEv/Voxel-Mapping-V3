"""Original four-spoke roof evidence, conditional surfaces and open joins."""
import json
import hashlib
import math
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
import pymupdf
from shapely.geometry import LineString, Polygon
from . import preshow_level_geometry as previous
from . import pyramidal_roof_topology as topology
from . import preshow_roof_patches as patches
from . import automatic_gable_roof as roof
from . import drawing_components
from .automatic_opening_links import bounded_work
from .drawing_page_tools import native_inverse
from .generation_cycles import atomic_json, file_hash
from .reconstruction_evidence_queue import digest

VERSION = 'conditional-pyramidal-roof-junction-evidence-v1'


def source_contexts(parent, graphs, charge):
    links = {link['source_reference_id']: link for link in parent['target_links']}
    unique = {}
    roof_views={c['id']:t['view_id'] for t in parent['source_topologies'] for c in t['candidates']}
    for check in parent['aim_checks']:
        key = (roof_views[check['candidate_id']],check['source_reference_id'],check['head_alternative_index'])
        if key in unique and unique[key]['diagnostic_aim_segment_pdf_native'] != check['diagnostic_aim_segment_pdf_native']:
            raise ValueError('Matching original symbol diagnostics required')
        unique[key] = check
    rows = []
    for graph in graphs:
        for candidate in graph['candidates']:
            polygon = Polygon(candidate['source_corners_pdf_native'])
            for key, source in sorted(unique.items()):
                charge()
                if key[0]!=graph['view_id']:continue
                link = links[key[1]]; segment = source['diagnostic_aim_segment_pdf_native']
                vector = np.array(segment[1])-segment[0]; vector /= np.linalg.norm(vector)
                normal = np.array([-vector[1],vector[0]])
                corners = np.array(candidate['source_corners_pdf_native']); edges = np.roll(corners,-1,axis=0)-corners
                parallel = max(abs(float(vector @ edge/np.linalg.norm(edge))) for edge in edges)
                length = LineString(segment).intersection(polygon).length
                unique_target = link['status']=='unique_source_view_reference_candidate'
                row = {'candidate_id':candidate['id'],'roof_view_id':graph['view_id'],
                    'source_reference_id':key[1], 'head_alternative_index':key[2],
                    'source_target_link_id':link['id'], 'source_reference_status':source['source_reference_status'],
                    'diagnostic_aim_segment_pdf_native':segment,'positive_intersection_length_pdf_points':length,
                    'source_view_direction_pdf_native':vector.tolist(),'source_horizontal_axis_pdf_native':normal.tolist(),
                    'source_direction_to_perimeter_alignment':parallel,
                    'target_candidates':link['target_candidates'],
                    'status':'conditional_pyramid_source_view_context' if unique_target and length>0 and parallel>=math.cos(math.radians(5))
                        else 'pyramid_source_view_context_held',
                    'source_visibility_hold_overridden':False,'physical_correspondence_verified':False,
                    'orthographic_projection_assumed':True,'diagnostic_reach_changed':False}
                row['id']=digest([VERSION,row]);rows.append(row)
    return rows


def cap_projection(candidate, context, unit):
    points = np.array(candidate['source_corners_pdf_native']); center = np.array(candidate['source_apex_pdf_native'])
    values = (points-center) @ context['source_horizontal_axis_pdf_native'] * unit
    return {'id':digest([VERSION,candidate['id'],context['id'],'cap-projection']),
        'native_runs_m':[-float(values.min()),float(values.max())],
        'corner_horizontal_stations_nominal_m':values.tolist()}


def literal_columns(gray, excluded, threshold, charge):
    """Same literal ink recipe, with a bounded index for the denser east crop.

    The preceding small-view extractor and its 2,048-column cap are unchanged.
    Every whole run is retained here; predictions never select source pixels.
    """
    if (gray.dtype!=np.uint8 or gray.ndim!=2 or gray.size>6000000 or max(gray.shape)>3000
            or excluded.shape!=gray.shape or excluded.dtype!=bool or threshold not in (220,235)):
        raise ValueError('Bounded original raster and mask required')
    rows=[];gray_sha=hashlib.sha256(gray.tobytes()).hexdigest()
    for x in range(gray.shape[1]):
        charge();yy=np.flatnonzero((gray[:,x]<threshold)&~excluded[:,x])
        for group in np.split(yy,np.flatnonzero(np.diff(yy)>2)+1):
            charge()
            if len(group)<16 or not 16<=group[-1]-group[0]<64:continue
            row={'x':x,'source_y_interval_pixels':[int(group[0]),int(group[-1])],
                'source_pixels':[{'x':x,'y':int(y),'gray':int(gray[y,x])} for y in group],
                'unsupported_row_intervals':[[int(a+1),int(b)] for a,b in zip(group[:-1],group[1:]) if b>a+1],
                'source_gaps_filled':False,'physical_fascia_role_verified':False}
            row['id']=digest([VERSION,'literal-column',threshold,gray_sha,row]);rows.append(row)
            if len(rows)>8192:raise OverflowError('pyramid_literal_column_budget')
    return rows


def indexed_endcaps(pair, columns, projection, mpp, charge, *, orientations=(1,-1)):
    """Retain each local corner failure once; expand only supported side pairs.

    A Cartesian product containing a failed side is held by that original side
    receipt. It need not be materialized repeatedly for every opposite column.
    """
    indexed={}
    for column in columns:indexed.setdefault(column['x'],[]).append(column)
    ends=[];corners=[];x,y=pair['inferred_ridge_pixel']
    for orientation in orientations:
        runs=projection['native_runs_m'][::orientation]
        predicted=[[x-runs[0]/mpp,y+math.tan(math.radians(pair['left_pitch_degrees']))*runs[0]/mpp],
            [x+runs[1]/mpp,y+math.tan(math.radians(pair['right_pitch_degrees']))*runs[1]/mpp]]
        sides=[]
        for side,point in enumerate(predicted):
            supported=[]
            for column_x in range(math.ceil(point[0]-4),math.floor(point[0]+4)+1):
                charge()
                for cap in indexed.get(column_x,[]):
                    charge();errors=[cap['x']-point[0],cap['source_y_interval_pixels'][0]-point[1]]
                    row={'source_pair_id':pair['id'],'source_cap_variant_id':projection['id'],
                        'image_left_to_native_rail_orientation':orientation,'image_side_index':side,
                        'source_fascia_column_id':cap['id'],'predicted_corner_pixel':point,
                        'source_corner_pixel':[cap['x'],cap['source_y_interval_pixels'][0]],
                        'source_corner_error_pixels':errors,
                        'status':'source_corner_within_pixel_tolerance' if max(abs(v) for v in errors)<=4 else 'source_corner_held'}
                    row['id']=digest([VERSION,'corner',row]);corners.append(row)
                    if row['status']=='source_corner_within_pixel_tolerance':supported.append(row)
            sides.append(supported)
        from itertools import product
        for a,b in product(*sides):
            charge();row={'source_pair_id':pair['id'],'source_cap_variant_id':projection['id'],
                'image_left_to_native_rail_orientation':orientation,
                'source_fascia_column_ids':[a['source_fascia_column_id'],b['source_fascia_column_id']],
                'source_corner_check_ids':[a['id'],b['id']], 'predicted_corner_pixels':predicted,
                'source_corner_error_pixels':[a['source_corner_error_pixels'],b['source_corner_error_pixels']],
                'source_eave_top_pixels':[a['source_corner_pixel'],b['source_corner_pixel']],
                'status':'conditional_source_endcaps_agree' if abs(pair['left_pitch_degrees']-pair['right_pitch_degrees'])<=2 else 'source_endcap_check_held',
                'source_points_moved':False,'physical_eave_role_verified':False}
            row['id']=digest([VERSION,'endcaps',row]);ends.append(row)
            if len(ends)>4096:raise OverflowError('pyramid_endcap_combination_budget')
    return ends,corners


def silhouettes(candidate, context, view, bindings, unit, charge):
    rows=[]; checks=[]; corner_checks=[]; extent_checks=[]; projection=cap_projection(candidate,context,unit);mpp=view['nominal_metres_per_pixel']
    for scan in view['variants']:
        for pair in scan['gable_intersections']:
            lines={line['id']:line for line in scan['lines']};allowed=[]
            for orientation in (1,-1):
                charge();runs=projection['native_runs_m'][::orientation];x=pair['inferred_ridge_pixel'][0]
                apex_y=pair['inferred_ridge_pixel'][1]
                predicted=[[x-runs[0]/mpp,apex_y+math.tan(math.radians(pair['left_pitch_degrees']))*runs[0]/mpp],
                    [x+runs[1]/mpp,apex_y+math.tan(math.radians(pair['right_pitch_degrees']))*runs[1]/mpp]]
                line_ids=[pair['left_line_id'],pair['right_line_id']]
                witnesses=[[p for p in lines[key]['source_pixels'] if max(abs(p['x']-point[0]),abs(p['y']-point[1]))<=4]
                    for key,point in zip(line_ids,predicted)]
                extent={'view_id':view['view_id'],'candidate_id':candidate['id'],'context_id':context['id'],
                    'source_pair_id':pair['id'],'image_left_to_native_orientation':orientation,
                    'source_line_ids':line_ids,'predicted_corner_pixels':predicted,
                    'original_slope_corner_support_pixels':witnesses,
                    'whole_hough_groups_retained':True,
                    'status':'original_slope_pixels_support_corners' if all(witnesses) else 'original_slope_corner_support_held'}
                extent['id']=digest([VERSION,extent]);extent_checks.append(extent)
                if extent['status']=='original_slope_pixels_support_corners':allowed.append(orientation)
            ends,corners=indexed_endcaps(pair,scan['source_fascia_columns'],projection,mpp,charge,orientations=allowed)
            corner_checks.extend({'view_id':view['view_id'],'candidate_id':candidate['id'],**c} for c in corners)
            for end in ends:checks.append({'view_id':view['view_id'],'candidate_id':candidate['id'],**end})
            equivalent={}
            for end in ends:
                if end['status']!='conditional_source_endcaps_agree':continue
                key=(end['image_left_to_native_rail_orientation'],tuple(p[1] for p in end['source_eave_top_pixels']))
                equivalent.setdefault(key,[]).append(end)
            for witnesses in equivalent.values():
                end=witnesses[0]  # Display witness only; every equivalent original column remains.
                for binding in bindings:
                    charge();matrix=view['pixel_to_display_matrix'];level_pixel=(binding['datum_y_display_points']-matrix[5])/matrix[3]
                    eaves=[(level_pixel-p[1])*mpp for p in end['source_eave_top_pixels']]
                    apex=(level_pixel-pair['inferred_ridge_pixel'][1])*mpp
                    if min(apex-h for h in eaves)<=0:continue
                    row={'candidate_id':candidate['id'],'context_id':context['id'],'view_id':view['view_id'],
                        'source_pair_id':pair['id'],'source_ink_threshold':scan['threshold'],
                        'source_endcap_check_id':end['id'],
                        'source_endcap_check_ids':[e['id'] for e in witnesses],
                        'source_eave_top_pixel_alternatives':[e['source_eave_top_pixels'] for e in witnesses],
                        'equal_height_witnesses_grouped_without_averaging':True,
                        'source_level_binding_id':binding['id'],
                        'source_level_label':binding['label']['level_label_candidate'],
                        'source_level_value_m_candidate':binding['label']['value_m_candidate'],
                        'image_left_to_native_orientation':end['image_left_to_native_rail_orientation'],
                        'source_apex_pixel':pair['inferred_ridge_pixel'],'source_eave_top_pixels':end['source_eave_top_pixels'],
                        'apex_above_printed_level_nominal_m':apex,
                        'image_eaves_above_printed_level_nominal_m':eaves,
                        'nominal_metres_per_pixel':mpp,'projection':projection,
                        'status':'unassigned_source_pyramid_silhouette_hypothesis',
                        'physical_roof_identity_verified':False}
                    row['id']=digest([VERSION,row]);rows.append(row)
                    if len(rows)>512:raise OverflowError('pyramid_silhouette_budget')
    return rows,checks,corner_checks,extent_checks


def comparisons(primary, supplemental, charge):
    rows=[]
    for a in primary:
        for b in supplemental:
            charge();offset=a['source_level_value_m_candidate']-b['source_level_value_m_candidate']
            errors=[a['apex_above_printed_level_nominal_m']-b['apex_above_printed_level_nominal_m']+offset]
            # Both side assignments survive. No mirror or residual-ranked winner.
            for orientation in (1,-1):
                eaves=b['image_eaves_above_printed_level_nominal_m'][::orientation]
                eave_errors=[x-y+offset for x,y in zip(a['image_eaves_above_printed_level_nominal_m'],eaves)]
                row={'source_silhouette_ids':[a['id'],b['id']],'supplemental_image_side_orientation':orientation,
                    'apex_difference_nominal_m':errors[0],'eave_differences_nominal_m':eave_errors,
                    'status':'conditional_cross_view_pyramid_heights_agree' if max(abs(v) for v in [*errors,*eave_errors])<=.25 else 'cross_view_pyramid_heights_held',
                    'shared_printed_datum_assumed':True,'supplemental_physical_correspondence_assumed':True,
                    'independent_survey_controls':False,'physical_identity_accepted':False}
                row['id']=digest([VERSION,row]);rows.append(row)
                if len(rows)>8192:raise OverflowError('pyramid_cross_view_comparison_budget')
    return rows


def mesh(candidate,silhouette):
    projection=silhouette['projection'];left,right=projection['native_runs_m']
    eaves=silhouette['image_eaves_above_printed_level_nominal_m'][::silhouette['image_left_to_native_orientation']]
    heights=[eaves[0]+(s+left)/(left+right)*(eaves[1]-eaves[0]) for s in projection['corner_horizontal_stations_nominal_m']]
    center=np.array(candidate['source_apex_pdf_native']);points=np.array(candidate['source_corners_pdf_native'])
    # No horizontal averaging or fitting. Original apex is the local origin.
    unit=silhouette['plan_unit'];xy=(points-center)*unit
    return {'vertices':[[*p,h] for p,h in zip(xy.tolist(),heights)]+[[0.,0.,silhouette['apex_above_printed_level_nominal_m']]],
        'triangles':[[0,1,4],[1,2,4],[2,3,4],[3,0,4]],
        'source_corner_heights_nominal_m':heights,'source_apex_height_nominal_m':silhouette['apex_above_printed_level_nominal_m'],
        'coordinate_frame':'original plan axes, local apex XY origin, nominal metres, Z relative to selected printed level',
        'source_horizontal_vertices_moved':False,'linear_eave_height_plane_assumed':True,
        'continuous_triangular_surfaces_assumed':True,'physical_roof_roles_verified':False,
        'closed_building':False,'world_placement_eligible':False}


def join_checks(parent,models,graphs,junctions,charge):
    candidates={c['id']:c for g in graphs for c in g['candidates']};rows=[]
    for junction in junctions:
        pyramid=candidates[junction['pyramid_candidate_id']]
        edge_ids=pyramid['source_perimeter_ids_per_edge'];edge_index=next(i for i,ids in enumerate(edge_ids) if junction['shared_original_cap_source_id'] in ids)
        a,b=[np.array(pyramid['source_corners_pdf_native'][i%4]) for i in (edge_index,edge_index+1)];delta=b-a
        for low in parent['conditional_roof_patches']:
            context=next(c for c in parent['contexts'] if c['id']==low['context_id'])
            if context['candidate_id']!=junction['gable_candidate_id']:continue
            cap=next(v for v in parent['source_cap_variants'] if v['id']==low['source_cap_variant_id'])
            indices=[0,2,4] if junction['ridge_endpoint_index']==0 else [1,3,5]
            for model in models:
                if model['candidate_id']!=junction['pyramid_candidate_id']:continue
                charge();corners=model['mesh']['source_corner_heights_nominal_m'];samples=[]
                for index in indices:
                    point=np.array(cap['source_vertices_pdf_native'][index]);station=float((point-a)@delta/(delta@delta))
                    if np.linalg.norm(point-(a+station*delta))>1e-6 or not -1e-9<=station<=1+1e-9:raise ValueError('Original shared cap sample required')
                    high=(1-station)*corners[edge_index]+station*corners[(edge_index+1)%4]+model['source_level_value_m_candidate']
                    low_height=low['mesh']['vertices'][index][2]+low['source_level_value_m_candidate']
                    samples.append({'original_point_pdf_native':point.tolist(),'shared_cap_station_fraction':station,
                        'pyramid_edge_height_printed_datum_candidate_m':high,'gable_height_printed_datum_candidate_m':low_height,
                        'signed_vertical_gap_nominal_m':high-low_height})
                row={'source_junction_id':junction['id'],'source_gable_model_id':low['id'],'source_pyramid_model_id':model['id'],
                    'samples':samples,'minimum_signed_vertical_gap_nominal_m':min(s['signed_vertical_gap_nominal_m'] for s in samples),
                    'status':'conditional_open_vertical_join_requires_wall_evidence' if all(s['signed_vertical_gap_nominal_m']>0 for s in samples)
                        else 'conditional_join_overlap_or_crossing_held',
                    'common_printed_datum_assumed':True,'physical_join_verified':False,'gap_filled':False,'join_mesh':None}
                row['id']=digest([VERSION,row]);rows.append(row)
                if len(rows)>8192:raise OverflowError('pyramid_open_join_budget')
    return rows


def threshold_checks(models,charge):
    rows=[]
    for a in models:
        if a['source_ink_threshold']!=220:continue
        for b in models:
            if b['source_ink_threshold']!=235 or any(a[k]!=b[k] for k in ('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation')):continue
            charge();errors=np.abs(np.array(a['mesh']['vertices'])[:,2]-np.array(b['mesh']['vertices'])[:,2])
            row={'source_model_ids':[a['id'],b['id']],'vertex_height_differences_nominal_m':errors.tolist(),
                'status':'pyramid_threshold_heights_agree' if max(errors)<=4*a['nominal_metres_per_pixel'] else 'pyramid_threshold_heights_held',
                'shared_pixels_are_not_independent_controls':True}
            row['id']=digest([VERSION,row]);rows.append(row)
            if len(rows)>8192:raise OverflowError('pyramid_threshold_comparison_budget')
    return rows


def threshold_coverage(models,charge):
    groups={};rows=[]
    for model in models:
        key=tuple(model[k] for k in ('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation'))
        groups.setdefault(key,[]).append(model)
    for key,entries in groups.items():
        charge();by_threshold={str(t):[m['id'] for m in entries if m['source_ink_threshold']==t] for t in (220,235)}
        row=dict(zip(('candidate_id','context_id','source_level_binding_id','image_left_to_native_orientation'),key))
        row.update(source_model_ids_by_threshold=by_threshold,
            status='both_source_thresholds_have_conditional_pyramid_support' if all(by_threshold.values()) else 'pyramid_cross_threshold_support_missing',
            missing_source_thresholds=[t for t in (220,235) if not by_threshold[str(t)]],
            conditional_inspection_models_only=True,physical_acceptance_authorized=False)
        row['id']=digest([VERSION,row]);rows.append(row)
    return rows


def build(preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output,*,max_checks=100000):
    bounded_work(max_checks)
    preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output=map(Path,
        (preshow,references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,output))
    parent_path=preshow/'preshow-level-geometry.json';parent=json.loads(parent_path.read_text())
    def replay():
        with tempfile.TemporaryDirectory() as temp:
            fresh=previous.build(references,topology_source,gradient,components,views,corpus,source_catalogue,additional_pdfs,temp,max_checks=parent['contract']['max_checks']);fresh.pop('directory')
            if digest(fresh)!=digest(parent):raise ValueError('Original preshow geometry replay changed')
    replay()
    if parent['status']!='conditional_preshow_level_geometry_only':raise ValueError('Complete original preshow evidence required')
    reference_path=references/'roof-reference-evidence.json';source=json.loads(reference_path.read_text())
    pins={parent_path:file_hash(parent_path),reference_path:file_hash(reference_path)}
    pins.update({references/name:pin for name,pin in source['output_artifact_sha256'].items()})
    if pins[reference_path]!=parent['contract']['source_reference_sha256']:raise ValueError('Matching original source reference required')
    contract={'version':VERSION,'implementation_sha256':file_hash(Path(__file__)),
        'kernel_sha256':{m.__name__:file_hash(Path(m.__file__)) for m in (topology,previous,patches,roof,drawing_components)},
        'source_preshow_sha256':pins[parent_path],'source_reference_sha256':pins[reference_path],'max_checks':max_checks,
        'cross_view_height_tolerance_nominal_m':.25,'source_endpoint_recipe':'exact_original_endpoint_identity'}
    fields=('plan_graphs','source_contexts','source_junctions','new_source_views','primary_silhouettes','supplemental_silhouettes','source_corner_checks','source_corner_edge_checks','endcap_checks','cross_view_checks','conditional_pyramid_models','open_join_checks','threshold_checks','threshold_coverage')
    result={k:[] for k in fields};result.update(contract=contract,status='conditional_pyramidal_roof_evidence_only',checks=0,
        accepted_physical_components=0,world_geometry_additions=0,training_labels_generated=0,
        previous_source_holds_overridden=False,previous_roof_models_changed=False)
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('pyramidal_roof_work_budget')
    try:
        supported={c['candidate_id'] for c in parent['contexts'] if c['status']=='conditional_face_on_gable_source_context'}
        for t in source['source_topologies']:
            graph=topology.discover(t,charge);result['plan_graphs'].append(graph)
            result['source_junctions'].extend(topology.junctions(t,graph['candidates'],supported,charge))
        result['source_contexts']=source_contexts(source,result['plan_graphs'],charge)
        bindings=[b for p in parent['level_pages'] for b in p['marker_bindings'] if b['status']=='unverified_source_level_marker_binding']
        available={target['view_id']:target for p in source['additional_pages'] for target in p['targets']}
        cached={v['view_id']:v for v in parent['gable_views']}
        for context in result['source_contexts']:
            if context['status']!='conditional_pyramid_source_view_context':continue
            target=context['target_candidates'][0]
            if target['view_id'] not in available:continue
            graph=next(g for g in result['plan_graphs'] if g['view_id']==context['roof_view_id'])
            candidate=next(c for c in graph['candidates'] if c['id']==context['candidate_id'])
            view_id=target['view_id']
            if view_id not in cached:
                original=next(p for p in source['additional_pages'] if any(t['view_id']==view_id for t in p['targets']))
                path=additional_pdfs/(original['document_sha256']+'.pdf');pins[path]=original['document_sha256']
                with pymupdf.open(path) as doc:
                    page=doc[original['page']-1];native_display=~native_inverse(page)*page.rotation_matrix
                    record=next(v for v in source['rendered_views'] if v['view_id']==view_id)
                    receipt=json.loads((references/record['receipt']).read_text());pixel_native=pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix']);matrix=pixel_native*native_display
                    if min(matrix.a,matrix.d)<=0 or max(abs(matrix.b),abs(matrix.c),abs(matrix.a-matrix.d))>1e-6:raise ValueError('Aligned square original pixels required')
                    view=next(v for v in original['view_candidates']['views'] if v['id']==view_id);mpp=matrix.a*view['nominal_metres_per_pdf_point']
                    with Image.open(references/record['png']) as image:gray=np.asarray(image.convert('L')).copy();size=image.size
                    mask,exclusion=roof.exclusion_mask({'source_components':drawing_components.split_page(original['source_geometry'])},page,pixel_native,size,charge)
                    row={**record,'nominal_metres_per_pixel':mpp,'pixel_to_display_matrix':list(matrix),'source_exclusions':exclusion,'variants':[]}
                    for threshold in (220,235):
                        scan=roof.slope_lines(gray,mask,threshold,charge);pairs=roof.gable_pairs(scan['lines'],mpp,0.,charge)
                        for pair in pairs:
                            pair.pop('nominal_ridge_height_m');pair.pop('id');pair['id']=digest([VERSION,view_id,threshold,pair])
                        scan['gable_intersections']=pairs;scan['source_fascia_columns']=literal_columns(gray,mask,threshold,charge);row['variants'].append(scan)
                    cached[view_id]=row;result['new_source_views'].append(row)
            own_bindings=[b for b in bindings if b['view_key_candidate']==target['view_key_candidate']]
            relative=[c for p in parent['level_pages'] for c in p['relative_checks'] if c['view_key_candidate']==target['view_key_candidate']]
            primary,endchecks,corners,extents=silhouettes(candidate,context,cached[view_id],own_bindings,graph['nominal_metres_per_pdf_point'],charge)
            result['primary_silhouettes'].extend(primary);result['endcap_checks'].extend(endchecks);result['source_corner_checks'].extend(corners);result['source_corner_edge_checks'].extend(extents)
            supplement=[]
            # Other own-source views remain unassigned silhouette comparisons.
            # A height match never changes their original reference visibility.
            for view in parent['gable_views']:
                if view['view_id']==view_id:continue
                target_other=available[view['view_id']]
                other_bindings=[b for b in bindings if b['view_key_candidate']==target_other['view_key_candidate']]
                rows,checks,corners,extents=silhouettes(candidate,context,view,other_bindings,graph['nominal_metres_per_pdf_point'],charge)
                supplement.extend(rows);result['endcap_checks'].extend(checks);result['source_corner_checks'].extend(corners);result['source_corner_edge_checks'].extend(extents)
            result['supplemental_silhouettes'].extend(supplement)
            comparisons_here=comparisons(primary,supplement,charge);result['cross_view_checks'].extend(comparisons_here)
            scale_supported=bool(relative) and all(c['status']=='source_relative_level_scale_agrees' for c in relative)
            for silhouette in primary:
                agrees=[c['id'] for c in comparisons_here if c['source_silhouette_ids'][0]==silhouette['id'] and c['status']=='conditional_cross_view_pyramid_heights_agree']
                if not scale_supported or not agrees:continue
                mesh_input={**silhouette,'plan_unit':graph['nominal_metres_per_pdf_point']}
                row={**silhouette,'source_silhouette_id':silhouette['id'],'source_agreeing_cross_view_check_ids':agrees,
                    'mesh':mesh(candidate,mesh_input),'status':'conditional_unplaced_pyramidal_roof_surface_only'}
                row.pop('id');row['id']=digest([VERSION,row]);result['conditional_pyramid_models'].append(row)
                if len(result['conditional_pyramid_models'])>256:raise OverflowError('pyramid_model_budget')
        result['open_join_checks']=join_checks(parent,result['conditional_pyramid_models'],result['plan_graphs'],result['source_junctions'],charge)
        result['threshold_checks']=threshold_checks(result['conditional_pyramid_models'],charge)
        result['threshold_coverage']=threshold_coverage(result['conditional_pyramid_models'],charge)
    except OverflowError as error:
        result.update({k:[] for k in fields});result.update(status='pyramidal_roof_evidence_budget_withheld',reason=str(error))
    for path,pin in pins.items():
        if file_hash(path)!=pin:raise ValueError('Original pyramidal roof source changed during build')
    replay()
    result['counts']={k:len(result[k]) for k in fields};result['counts']['original_four_spoke_candidates']=sum(len(g['candidates']) for g in result['plan_graphs'])
    result=json.loads(json.dumps(result))
    if len(json.dumps(result).encode())>64000000:raise ValueError('Pyramid evidence output budget exceeded')
    root=output/digest(contract);path=root/'pyramidal-roof-evidence.json'
    if path.exists():
        if digest(json.loads(path.read_text()))!=digest(result):raise ValueError('Saved pyramid evidence changed')
    else:atomic_json(path,result)
    return {**result,'directory':str(root)}
