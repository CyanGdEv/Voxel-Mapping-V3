"""Automatic peripheral-text layout evidence, never a physical scale correction."""
from collections import Counter
import math
import re

import numpy as np
import pymupdf
from shapely.geometry import MultiPoint, Polygon, box, shape

from . import automatic_facade_alignment, drawing_annotations, drawing_views, sheet_layout_audit
from .architectural_view_layout import view_claim
from .automatic_opening_links import bounded_work
from .drawing_page_tools import native_inverse
from .glyph_visibility import screen_architectural_span
from .ordinary_surfaces import label_runs
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-sheet-scale-evidence-v1'


def page_review(page, source, charge):
    traces = page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:
        raise OverflowError('sheet_text_budget')
    inverse = native_inverse(page); frame = box(*(page.rect*page.derotation_matrix*inverse))
    x0,y0,x1,y1 = frame.bounds
    inner = box(x0+.2*(x1-x0), y0+.2*(y1-y0), x1-.2*(x1-x0), y1-.2*(y1-y0))
    unit_kind,unit = page.parent.xref_get_key(page.xref,'UserUnit')
    standard = (unit_kind=='null' or float(unit)==1) and page.cropbox==page.mediabox
    identity = drawing_views.sheet_identity(traces)
    header = screen_architectural_span(page,traces[identity['trace_index']]) if identity else None
    runs = list(label_runs(traces)); counts = Counter(''.join(chr(c[0]) for c in r['chars']).strip() for r in runs)
    result = {'document_sha256':source['document_sha256'],'page':source['page'],
        'source_page_views_sha256':digest(source),'standard_page_frame':standard,
        'native_page_bounds':list(frame.bounds),'sheet_identity':identity,'header_glyph_screen':header,
        'text_occurrence_counts':dict(counts),'peripheral_text':[],'dimension_text':[],
        'figured_facade_dimensions_verified':False}
    for run in runs:
        charge(); text = ''.join(chr(c[0]) for c in run['chars']).strip(); claims = drawing_annotations.categories(text)
        rect = pymupdf.Rect(run['bbox']); geometry = Polygon([tuple(p*inverse) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        dimensional = [c for c in claims if c['kind'] in ('explicit_dimension','untyped_numeric')]
        peripheral = (3<=len(text)<=256 and any(c.isalpha() for c in text) and '\\' not in text
            and not claims and view_claim(text) is None and not re.search(r'\b1\s*:\s*\d+',text)
            and frame.covers(geometry) and not inner.intersects(geometry))
        if not dimensional and not peripheral: continue
        row = {'text':text,'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'origin_pdf_native':list(pymupdf.Point(run['chars'][0][2])*inverse),
            'geometry_pdf_native':geometry.__geo_interface__,'font_size_points':run['size'],
            'page_literal_occurrences':counts[text],'within_declared_furniture_scope':peripheral,
            'scope_basis':'automatic_outer_20_percent_page_band',
            'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)
                if counts[text]==1 else None}
        row['id'] = digest([VERSION,result['document_sha256'],result['page'],row])
        if peripheral: result['peripheral_text'].append(row)
        if dimensional:
            result['dimension_text'].append({**row,'claims':dimensional,
                'whole_automatic_view_ids':[v['id'] for v in source['views'] if shape(v['geometry']).covers(geometry)],
                'status':'unassociated_length_or_numeric_text','component_dimension_verified':False})
        if len(result['peripheral_text'])>256 or len(result['dimension_text'])>256:
            raise OverflowError('sheet_candidate_text_budget')
    return result


def compare_pages(subject, reference, charge):
    a = {}; b = {}
    for page,lookup in ((subject,a),(reference,b)):
        for row in page['peripheral_text']: lookup.setdefault(row['text'],[]).append(row)
    common = sorted(a.keys() & b.keys()); eligible = []; excluded = []
    for text in common:
        charge(); left,right = a[text],b[text]
        usable = (len(left)==len(right)==1 and all(r['page_literal_occurrences']==1
            and r['glyph_screen'] is not None and r['glyph_screen']['status']=='raster_consistent_candidate'
            for r in [*left,*right]))
        (eligible if usable else excluded).append(text)
    result = {'subject_page_key':[subject['document_sha256'],subject['page']],
        'reference_page_key':[reference['document_sha256'],reference['page']],
        'source_subject_review_sha256':digest(subject),'source_reference_review_sha256':digest(reference),
        'common_text':common,'excluded_before_role_assignment':excluded,'terms':[],
        'status':'independent_visible_same_project_sheets_required','layout_fit':None,
        'physical_scale_verified':False,'geometry_correction_applied':False}
    identities = [p['sheet_identity'] for p in (subject,reference)]
    if (not all(p['standard_page_frame'] and p['header_glyph_screen'] is not None
            and p['header_glyph_screen']['status']=='raster_consistent_candidate' for p in (subject,reference))
            or any(i is None for i in identities) or identities[0]['project']!=identities[1]['project']
            or subject['document_sha256']==reference['document_sha256']): return result
    if not 12<=len(eligible)<=64:
        result['status']='twelve_to_sixty_four_unique_visible_peripheral_terms_required'; return result
    terms = [{'text':text,'role':'holdout' if i%3==0 else 'fit'} for i,text in enumerate(eligible)]
    result.update(terms=terms,layout_fit=sheet_layout_audit.fit(a,b,terms),
        role_assignment='lexical_order_every_third_term_held_out_before_fit_no_outlier_removal')
    result['status'] = result['layout_fit']['status']
    return result


def diagnostic_extent(extent, frame, inverse, unit, hull, charge):
    axis = np.asarray(frame['diagnostic_axis']) @ inverse; axis /= np.linalg.norm(axis)
    origin = np.asarray(frame['source_native_endpoints'][0]); geometry = shape(extent['geometry_pdf_native'])
    values = []
    for part_index,part in enumerate(geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry]):
        for vertex_index,point in enumerate(part.exterior.coords):
            charge(); values.append({'part_index':part_index,'exterior_vertex_index':vertex_index,
                'point_pdf_native':list(point),'position_m':float((np.asarray(point)-origin) @ inverse @ axis*unit)})
    extrema = [min(values,key=lambda v:v['position_m']),max(values,key=lambda v:v['position_m'])]
    row = {'source_extent_id':extent['id'],'source_extent_sha256':digest(extent),
        'source_geometry_sha256':digest(extent['geometry_pdf_native']),
        'nominal_plan_position_interval_m':[v['position_m'] for v in extrema],
        'diagnostic_extreme_vertices':extrema,
        'subject_axis_to_reference_unit_axis':axis.tolist(),'source_origin_pdf_native':origin.tolist(),
        'requires_artwork_extrapolation':not hull.covers(geometry),
        'basis':'peripheral_text_inverse_layout_diagnostic_only',
        'layout_application_verified':False,'physical_facade_extent_verified':False,'source_geometry_changed':False}
    row['id'] = digest([VERSION,row]); return row


def run(corpus, source_pages, inventories, buildings, levels, alignment, *, max_checks=100000):
    bounded_work(max_checks); lookup = {v['view_id']:v for v in inventories}; pins = {k:digest(v) for k,v in lookup.items()}
    if len(inventories)>32 or len(lookup)!=len(inventories): raise ValueError('Bounded unique source inventories required')
    if (alignment['source_inventory_sha256']!=pins or alignment['source_building_links_sha256']!=digest(buildings)
            or alignment['source_level_context_sha256']!=digest(levels)):
        raise ValueError('Matching source inventory and facade alignment required')
    result = {'version':VERSION,'status':'peripheral_sheet_layout_evidence_only','pages':[],'pairs':[],
        'diagnostics':[],'evidence_requirements':[],'checks':0,'source_inventory_sha256':pins,
        'source_facade_alignment_sha256':digest(alignment),'source_building_links_sha256':digest(buildings),
        'source_level_context_sha256':digest(levels),
        'recipe':{'page_edge_band_fraction':.2,'minimum_common_terms':12,'maximum_common_terms':64,
            'role_assignment':'lexical_order_every_third_holdout_before_fit','maximum_page_pairs':8,
            'reference_recipe':'all_independent_roof_plan_pages_in_selected_inventory_no_best_fit_selection',
            'dimension_policy':'explicit_units_and_bare_numbers_retained_without_component_or_unit_inference',
            'max_checks':max_checks},
        'physical_scale_verified':False,'layout_application_verified':False,'position_alignment_verified':False,
        'world_geometry_additions':0,'training_labels_generated':0}
    def charge():
        result['checks'] += 1
        if result['checks']>max_checks: raise OverflowError('sheet_scale_work_budget')
    def hold(reason):
        return {**result,'status':'sheet_scale_budget_withheld','reason':reason,'pages':[],'pairs':[],
                'diagnostics':[],'evidence_requirements':[],'counts':{}}
    if alignment['status']!='independent_source_extent_and_origin_hypotheses_only':
        return {**result,'status':'complete_source_facade_alignment_required'}
    selected = [(p,[v for v in p['views'] if v['id'] in lookup]) for p in source_pages]
    if sum(len(vs) for _,vs in selected)!=len(lookup) or any(digest(v)!=lookup[v['id']]['source_view_sha256'] for _,vs in selected for v in vs):
        raise ValueError('Matching unique automatic source views required')
    try:
        page_lookup = {}; view_pages = {}; roof_pages = []
        for source,views in selected:
            if not views: continue
            charge(); key = (source['document_sha256'],source['page'])
            with pymupdf.open(corpus.root/'files'/(key[0]+'.pdf')) as document:
                page = page_review(document[key[1]-1],source,charge)
            result['pages'].append(page); page_lookup[key] = page
            for view in views: view_pages[view['id']] = key
            roof = [v for v in views if v['printed_claim']['view_kind']=='plan' and v['printed_claim'].get('plan_level_or_form')=='roof']
            if roof: roof_pages.append((key,roof))
        records = {r['id']:r for r in buildings['frames']}
        families = {f['id']:f for v in levels['views'] for f in v['families']}
        level_views = {v['view_id']:v for v in levels['views']}; pair_cache = {}
        for row in alignment['frames']:
            subject_key = view_pages[row['plan_view_id']]
            for reference_key,roof in roof_pages:
                if subject_key[0]==reference_key[0]: continue
                key = (subject_key,reference_key)
                if key not in pair_cache:
                    if len(pair_cache)>=8: return hold('sheet_page_pair_budget')
                    pair = compare_pages(page_lookup[subject_key],page_lookup[reference_key],charge)
                    pair['id'] = digest([VERSION,pair]); pair_cache[key] = pair; result['pairs'].append(pair)
                pair = pair_cache[key]
                if pair['status']!='supported_furniture_layout_correspondence_only': continue
                plan = lookup[row['plan_view_id']]; unit = plan['nominal_metres_per_pdf_point']
                if unit is None or any(v['nominal_metres_per_pdf_point']!=unit for v in roof): continue
                fit = pair['layout_fit']; inverse = np.asarray(fit['subject_to_reference_linear_row_matrix'])
                hull = MultiPoint([r['subject_origin'] for r in fit['rows'] if r['role']=='fit']).convex_hull
                record = records[row['facade_record_id']]
                for review in row['frame_reviews']:
                    charge(); frame = next(f for f in record['frame_review']['frames'] if f['id']==review['frame_id'])
                    extents = {e['id']:diagnostic_extent(e,frame,inverse,unit,hull,charge) for e in review['plan_extents']}
                    target = record['target_elevation_view_ids'][0]; matrix = level_views[target]['pixel_edge_to_source_display_matrix']
                    diagnostic = {'pair_id':pair['id'],'source_frame_review_sha256':digest(review),
                        'facade_record_id':row['facade_record_id'],'frame_id':frame['id'],
                        'extents':list(extents.values()),'width_comparisons':[],
                        'physical_scale_verified':False,'layout_application_verified':False}
                    for original in review['extent_comparisons']:
                        charge(); parent = families[original['parent_family_review_id']]
                        comparison = automatic_facade_alignment.compare_extent(extents[original['plan_extent_id']],parent,matrix,
                            lookup[target]['nominal_metres_per_pdf_point'],charge)
                        comparison['source_raw_comparison_sha256'] = digest(original)
                        comparison['layout_application_verified'] = False
                        diagnostic['width_comparisons'].append(comparison)
                        result['evidence_requirements'].append({'pair_id':pair['id'],'source_raw_comparison_id':original['id'],
                            'status':'independent_dimension_and_matching_extent_corners_required',
                            'reason':'Peripheral text validates page layout only; artwork scale and corresponding facade boundaries remain unverified.',
                            'requested_evidence':['dimensioned_facade_or_floor_plan','corresponding_exterior_wall_corners'],
                            'automatic_geometry_authorized':False})
                    result['diagnostics'].append(diagnostic)
        result['counts'] = {'source_pages':len(result['pages']),'page_pairs':len(result['pairs']),
            'supported_layout_pairs':sum(p['status']=='supported_furniture_layout_correspondence_only' for p in result['pairs']),
            'unassociated_explicit_length_texts':sum(any(c['kind']=='explicit_dimension' for c in r['claims']) for p in result['pages'] for r in p['dimension_text']),
            'diagnostic_extent_comparisons':sum(len(d['width_comparisons']) for d in result['diagnostics']),
            'diagnostic_widths_compatible':sum(c['status']=='all_witness_extent_widths_compatible' for d in result['diagnostics'] for c in d['width_comparisons']),
            'evidence_requirements':len(result['evidence_requirements'])}
        return result
    except OverflowError as error: return hold(str(error))
