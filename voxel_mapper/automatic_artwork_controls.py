"""Held-out non-target artwork references; no physical scale or origin acceptance."""
from collections import defaultdict
import math
import re

import numpy as np
import pymupdf
from shapely.geometry import LineString, MultiPoint, Polygon, shape

from .automatic_opening_links import bounded_work
from .automatic_facade_alignment import compare_extent
from .drawing_page_tools import native_inverse
from .drawing_views import text
from .generation_cycles import file_hash
from .glyph_visibility import screen_architectural_span
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-independent-artwork-controls-v1'


def page_controls(page, source, project, charge):
    traces=page.get_texttrace();paths=page.get_drawings();matrix=native_inverse(page)
    if len(traces)>10000 or len(paths)>100000 or sum(len(t['chars']) for t in traces)>500000:
        raise OverflowError('artwork_source_budget')
    numbers=[(i,t,int(text(t))) for i,t in enumerate(traces) if re.fullmatch(r'\d{1,3}',text(t))]
    if len(numbers)>5000:raise OverflowError('artwork_numeric_budget')
    rows=[];screens={}
    plans=[v for v in source['views'] if v['printed_claim']['view_kind']=='plan']
    if len(plans)>100:raise OverflowError('artwork_source_view_budget')
    for ordinal,path in enumerate(paths):
        charge();items=path.get('items',[])
        if (path['type']!='s' or len(items)!=4 or any(i[0]!='c' for i in items)
                or path.get('layer') or path.get('stroke_opacity')!=1 or path.get('dashes') not in (None,'[] 0')):continue
        rect=path['rect'];radius=(rect.width+rect.height)/4
        if not 3<=radius<=40 or abs(rect.width-rect.height)>.02*radius or math.dist(items[0][1],items[-1][-1])>.3:continue
        inside=[]
        for index,span,value in numbers:
            charge();b=pymupdf.Rect(span['bbox'])
            if rect.contains((b.tl+b.br)*.5):inside.append((index,span,value))
        if len(inside)!=1:continue
        sheet_index,span,sheet=inside[0];center=(rect.tl+rect.br)*.5;outside=[]
        for index,other,value in numbers:
            charge();b=pymupdf.Rect(other['bbox']);c=(b.tl+b.br)*.5
            if (index!=sheet_index and 1<=value<=99 and other['dir']==span['dir']
                    and not rect.intersects(b) and math.dist(center,c)<=3*radius):outside.append((index,other,value))
        row={'source_circle_path_index':ordinal,'source_circle_paint_seqno':path['seqno'],
            'circle_source_beziers':[[list(p) for p in item[1:]] for item in items],
            'circle_bbox_page_points':list(rect),'center_pdf_native':list(center*matrix),
            'radius_page_points':radius,'sheet_trace_index':sheet_index,
            'outside_trace_indices':[i for i,_,_ in outside],
            'status':'unique_outside_reference_number_required','key':None,
            'marker_semantics_verified':False,'marker_clipping_verified':False,'physical_scale_verified':False}
        if len(outside)==1:
            index,other,value=outside[0];row['key']=[project,sheet,value]
            boxes=[rect,pymupdf.Rect(span['bbox']),pymupdf.Rect(other['bbox'])]
            polygons=[Polygon([tuple(p*matrix) for p in (b.tl,b.tr,b.br,b.bl)]) for b in boxes]
            row['whole_plan_view_ids']=[v['id'] for v in plans if all(shape(v['geometry']).covers(p) for p in polygons)]
            for i in (sheet_index,index):
                if i not in screens:screens[i]=screen_architectural_span(page,traces[i])
            row['glyph_screens']=[screens[i] for i in (sheet_index,index)]
            row['font_sizes_points']=[traces[i]['size'] for i in (sheet_index,index)]
            row['status']=('original_numbered_artwork_reference_candidate' if len(row['whole_plan_view_ids'])==1
                and all(s['status']=='raster_consistent_candidate' for s in row['glyph_screens']) else 'whole_visible_unique_plan_reference_required')
        row['id']=digest([VERSION,source['document_sha256'],source['page'],row]);rows.append(row)
        if len(rows)>256:raise OverflowError('artwork_marker_budget')
    return {'document_sha256':source['document_sha256'],'page':source['page'],
        'source_page_views_sha256':digest(source),'markers':rows,'unrotated_mupdf_to_pdf_native_matrix':list(matrix)}


def compare(subject, reference, excluded_sheets, charge):
    """Assign lexical roles before fitting; the target sheet never enters the fit."""
    lookups=[]
    for page in (subject,reference):
        grouped=defaultdict(list)
        for row in page['markers']:
            if row['key'] is not None:grouped[tuple(row['key'])].append(row)
        lookups.append(grouped)
    a,b=lookups;eligible=[];excluded=[]
    for key in sorted(a.keys()&b.keys()):
        charge();left,right=a[key],b[key]
        def occurrence(rows):
            # Coincident repeated paints remain explicit, without averaging or selecting one paint.
            return {(tuple(r['center_pdf_native']),r['sheet_trace_index'],tuple(r['outside_trace_indices'])) for r in rows}
        reason=None
        if tuple(key[:2]) in excluded_sheets:reason='target_facade_sheet_excluded_before_roles'
        elif len(occurrence(left))!=1 or len(occurrence(right))!=1:reason='nonunique_printed_reference_occurrences'
        elif any(r['status']!='original_numbered_artwork_reference_candidate' for r in [*left,*right]):reason='whole_visible_unique_references_required'
        if reason:excluded.append({'key':list(key),'reason':reason});continue
        for marker in [*left,*right]:
            if (not all(type(v) in (int,float) and math.isfinite(v) for v in marker['center_pdf_native'])
                    or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0
                        for v in [*marker['font_sizes_points'],marker['radius_page_points']])):
                raise ValueError('Finite original artwork controls required')
        eligible.append({'key':list(key),'subject_marker_ids':[r['id'] for r in left],
            'reference_marker_ids':[r['id'] for r in right],
            'subject_center':left[0]['center_pdf_native'],'reference_center':right[0]['center_pdf_native'],
            'subject_fonts':left[0]['font_sizes_points'],'reference_fonts':right[0]['font_sizes_points'],
            'subject_radii':[r['radius_page_points'] for r in left],'reference_radii':[r['radius_page_points'] for r in right]})
    result={'status':'five_to_sixty_four_non_target_controls_required','controls':[],'excluded_controls':excluded,
        'physical_scale_verified':False,'target_artwork_application_verified':False,'geometry_correction_applied':False}
    if not 5<=len(eligible)<=64:return result
    if len({tuple(r['key'][:2]) for r in eligible})<2:
        result['status']='two_independent_non_target_reference_sheets_required';return result
    for i,row in enumerate(eligible):row['role']='holdout' if i%2==0 else 'fit'
    result['controls']=eligible;fit=[r for r in eligible if r['role']=='fit'];check=[r for r in eligible if r['role']=='holdout']
    if len(fit)<2 or len(check)<3:raise ValueError('Two fit and three held-out similarity controls required')
    all_reference=np.asarray([r['reference_center'] for r in eligible])
    if np.linalg.matrix_rank(np.c_[all_reference-all_reference.mean(axis=0),np.ones(len(all_reference))])!=3:
        result['status']='noncollinear_artwork_controls_required';return result
    x=np.asarray([r['reference_center'] for r in fit]);y=np.asarray([r['subject_center'] for r in fit])
    xx=x-x.mean(axis=0);yy=y-y.mean(axis=0);denominator=float(np.sum(xx*xx))
    if math.sqrt(denominator/len(fit))<5*max(v for r in fit for v in r['reference_radii']):
        result['status']='well_separated_original_fit_controls_required';return result
    # Four parameters only: uniform scale, rotation and translation. No affine shear/anisotropy.
    a=float(np.sum(xx*yy)/denominator)
    b=float(np.sum(xx[:,0]*yy[:,1]-xx[:,1]*yy[:,0])/denominator)
    linear=np.asarray([[a,b],[-b,a]]);translation=y.mean(axis=0)-x.mean(axis=0)@linear
    determinant=float(np.linalg.det(linear));singular=np.linalg.svd(linear,compute_uv=False)
    result.update(reference_to_subject_linear_row_matrix=linear.tolist(),reference_to_subject_translation=translation.tolist(),
        linear_singular_values=singular.tolist(),determinant=determinant,fit_control_count=len(fit),holdout_control_count=len(check))
    if determinant<=0 or not .5<=min(singular)<=max(singular)<=2:
        result['status']='unsupported_artwork_uniform_scale';return result
    scale=float(np.sqrt(determinant));result['apparent_subject_artwork_scale']=scale
    for row in eligible:
        charge();row['residual_pdf_points']=float(np.linalg.norm(np.asarray(row['reference_center'])@linear+translation-row['subject_center']))
        row['font_ratios']=[s/r for s,r in zip(row['subject_fonts'],row['reference_fonts'])]
        row['radius_ratios']=[s/r for s in row['subject_radii'] for r in row['reference_radii']]
    result.update(fit_max_residual_pdf_points=max(r['residual_pdf_points'] for r in fit),
        holdout_max_residual_pdf_points=max(r['residual_pdf_points'] for r in check))
    if max(r['residual_pdf_points'] for r in eligible)>.25:
        result['status']='original_artwork_fit_or_holdouts_disagree';return result
    if any(abs(ratio/scale-1)>.015 for r in eligible for ratio in [*r['font_ratios'],*r['radius_ratios']]):
        result['status']='original_artwork_font_or_circle_scale_disagrees';return result
    result.update(status='supported_non_target_artwork_layout_only',
        subject_to_reference_linear_row_matrix=np.linalg.inv(linear).tolist(),
        fit_control_hull_pdf_native=MultiPoint(y).convex_hull.__geo_interface__,
        all_control_hull_pdf_native=MultiPoint([r['subject_center'] for r in eligible]).convex_hull.__geo_interface__)
    return result


def run(corpus, source_pages, inventories, buildings, levels, scale, returns, *, max_checks=100000):
    bounded_work(max_checks);lookup={v['view_id']:v for v in inventories};pins={k:digest(v) for k,v in lookup.items()}
    if len(inventories)>32 or len(lookup)!=len(inventories):raise ValueError('Bounded unique artwork inventories required')
    if (buildings['source_inventory_sha256']!=pins or levels['source_inventory_sha256']!=pins
            or scale['source_inventory_sha256']!=pins or returns['source_inventory_sha256']!=pins
            or scale['source_building_links_sha256']!=digest(buildings) or scale['source_level_context_sha256']!=digest(levels)
            or levels['source_building_links_sha256']!=digest(buildings)
            or returns['source_building_links_sha256']!=digest(buildings) or returns['source_level_context_sha256']!=digest(levels)
            or returns['source_facade_alignment_sha256']!=scale['source_facade_alignment_sha256']
            or returns['source_sheet_scale_sha256']!=digest(scale)):
        raise ValueError('Matching original artwork evidence chain required')
    selected=[v for p in source_pages for v in p['views'] if v['id'] in lookup]
    if (len(selected)!=len(lookup) or len({v['id'] for v in selected})!=len(lookup)
            or any(digest(v)!=lookup[v['id']]['source_view_sha256'] for v in selected)):
        raise ValueError('Matching unique original artwork views required')
    excluded=sorted({tuple(r['target_view_key_candidate'][:2]) for r in buildings['frames']})
    result={'version':VERSION,'status':'independent_non_target_artwork_controls_only','pages':[],'pairs':[],'diagnostics':[],
        'source_inventory_sha256':pins,'source_building_links_sha256':digest(buildings),'source_level_context_sha256':digest(levels),
        'source_sheet_scale_sha256':digest(scale),'source_wall_return_corners_sha256':digest(returns),
        'excluded_target_sheet_keys':[list(k) for k in excluded],'checks':0,
        'recipe':{'max_checks':max_checks,'minimum_unique_controls':5,'maximum_unique_controls':64,
            'minimum_fit_controls':2,'minimum_holdout_controls':3,'minimum_non_target_sheets':2,
            'model':'orientation_preserving_similarity_four_parameters_no_affine_shear',
            'minimum_fit_rms_to_marker_radius_ratio':5,
            'role_assignment':'lexical_reference_key_alternating_holdout_fit_before_fit_no_outlier_removal',
            'maximum_fit_and_holdout_residual_pdf_points':.25,'maximum_font_and_radius_ratio_departure':.015},
        'physical_scale_verified':False,'target_artwork_application_verified':False,
        'world_geometry_additions':0,'training_labels_generated':0}
    def charge():
        result['checks']+=1
        if result['checks']>max_checks:raise OverflowError('artwork_control_work_budget')
    def hold(reason):return {**result,'status':'artwork_control_budget_withheld','reason':reason,'pages':[],'pairs':[],'diagnostics':[],'counts':{}}
    sources={(p['document_sha256'],p['page']):p for p in source_pages};prior={(p['document_sha256'],p['page']):p for p in scale['pages']}
    cache={};records={r['id']:r for r in buildings['frames']};families={f['id']:f for v in levels['views'] for f in v['families']};lv={v['view_id']:v for v in levels['views']}
    try:
        if len(scale['pairs'])>8:return hold('artwork_page_pair_budget')
        for original in scale['pairs']:
            keys=[tuple(original[k]) for k in ('subject_page_key','reference_page_key')];pages=[]
            original_pages=[prior[k] for k in keys]
            if any(p['source_page_views_sha256']!=digest(sources[k]) for k,p in zip(keys,original_pages)):
                raise ValueError('Complete original artwork page views required')
            if (not all(p['standard_page_frame'] and p['sheet_identity'] and p['header_glyph_screen']
                    and p['header_glyph_screen']['status']=='raster_consistent_candidate' for p in original_pages)
                    or original_pages[0]['sheet_identity']['project']!=original_pages[1]['sheet_identity']['project']):continue
            for key in keys:
                if key not in cache:
                    source=sources[key];path=corpus.root/'files'/(key[0]+'.pdf')
                    if file_hash(path)!=key[0]:raise ValueError('Original artwork PDF checksum mismatch')
                    with pymupdf.open(path) as document:page=page_controls(document[key[1]-1],source,prior[key]['sheet_identity']['project'],charge)
                    if file_hash(path)!=key[0]:raise ValueError('Original artwork PDF changed')
                    cache[key]=page;result['pages'].append(page)
                pages.append(cache[key])
            pair={**compare(*pages,set(excluded),charge),'source_sheet_pair_id':original['id'],
                'subject_page_key':list(keys[0]),'reference_page_key':list(keys[1]),'source_page_review_sha256':[digest(p) for p in pages]}
            pair['id']=digest([VERSION,pair]);result['pairs'].append(pair)
            if pair['status']!='supported_non_target_artwork_layout_only':continue
            inverse=np.asarray(pair['subject_to_reference_linear_row_matrix']);hull=shape(pair['fit_control_hull_pdf_native']);all_hull=shape(pair['all_control_hull_pdf_native'])
            for d in returns['diagnostics']:
                if d['pair_id']!=original['id']:continue
                charge();record=records[d['facade_record_id']];plan=lookup[record['plan_view_id']]
                reference_units={lookup[v['id']]['nominal_metres_per_pdf_point'] for v in sources[keys[1]]['views']
                    if v['id'] in lookup and v['printed_claim']['view_kind']=='plan'}
                if reference_units!={plan['nominal_metres_per_pdf_point']} or plan['nominal_metres_per_pdf_point'] is None:continue
                frame=next(f for f in record['frame_review']['frames'] if f['id']==d['frame_id'])
                axis=np.asarray(frame['diagnostic_axis'])@inverse;axis/=np.linalg.norm(axis)
                points=d['source_points_pdf_native'];span=abs(float((np.asarray(points[1])-points[0])@inverse@axis))*plan['nominal_metres_per_pdf_point']
                extent={'id':digest([VERSION,pair['id'],d['source_corner_pair_sha256']]),'nominal_plan_position_interval_m':[0.,span]}
                row={'pair_id':pair['id'],'source_return_diagnostic_sha256':digest(d),'source_corner_pair_id':d['source_corner_pair_id'],
                    'source_points_pdf_native':points,'nominal_span_m':span,'source_axis_pdf_native':frame['diagnostic_axis'],
                    'nominal_metres_per_pdf_point':plan['nominal_metres_per_pdf_point'],
                    'outside_fit_control_hull':not hull.covers(LineString(points)),
                    'outside_all_control_hull':not all_hull.covers(LineString(points)),
                    'width_comparisons':[],'target_artwork_application_verified':False,'source_geometry_changed':False}
                target=record['target_elevation_view_ids'][0]
                for old in d['raw_width_comparisons']:
                    charge();row['width_comparisons'].append(compare_extent(extent,families[old['parent_family_review_id']],
                        lv[target]['pixel_edge_to_source_display_matrix'],lookup[target]['nominal_metres_per_pdf_point'],charge))
                result['diagnostics'].append(row)
        result['counts']={'source_pages':len(result['pages']),'page_pairs':len(result['pairs']),
            'supported_artwork_pairs':sum(p['status']=='supported_non_target_artwork_layout_only' for p in result['pairs']),
            'non_target_controls':sum(len(p['controls']) for p in result['pairs']),
            'corner_span_diagnostics':len(result['diagnostics']),
            'width_comparisons':sum(len(d['width_comparisons']) for d in result['diagnostics']),
            'widths_compatible':sum(w['status']=='all_witness_extent_widths_compatible' for d in result['diagnostics'] for w in d['width_comparisons']),
            'target_spans_requiring_extrapolation':sum(d['outside_all_control_hull'] for d in result['diagnostics'])}
        return result
    except OverflowError as error:return hold(str(error))
