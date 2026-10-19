"""Automatic source-relative level and jamb-row evidence, never a physical datum."""
from collections import Counter
import math

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import shape, box

from . import elevation_levels
from .automatic_opening_links import bounded_work, affine
from .drawing_page_tools import native_inverse
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-elevation-level-context-v1'
MINIMUM_ABOVE_LEVEL_ROWS = 24


def family_review(inventory, family_index, reference, pixel_to_display, charge):
    """Retain every original threshold witness; never trim the source jambs."""
    index = inventory['residual_raster_scan']['index']; family = index['consensus_families'][family_index]
    matrix = pymupdf.Matrix(pixel_to_display); factor = inventory['nominal_metres_per_pdf_point']
    if (any(not math.isfinite(v) for v in matrix) or abs(matrix.b)>1e-7 or abs(matrix.c)>1e-7
            or matrix.a<=0 or matrix.d<=0 or type(factor) not in (int,float)
            or not math.isfinite(factor) or factor<=0):
        raise ValueError('Positive aligned finite source display transform and nominal scale required')
    datum = reference['datum_y_display_points']; level_pixel = (datum-matrix.f)/matrix.d
    if not math.isfinite(level_pixel): raise ValueError('Finite source relative level required')
    locations = [(0,family['first_pair_index']), *[(1,i) for i in family['second_pair_indices']]]
    if not family['second_pair_indices'] or len(set(locations))!=len(locations):
        raise ValueError('Distinct complete threshold-consensus witnesses required')
    witnesses = []
    for variant_index, pair_index in locations:
        charge(); variant = index['variants'][variant_index]; pair = variant['pairs'][pair_index]
        groups = [variant['jamb_groups'][i] for i in pair['jamb_group_indices']]
        top = max(g['top'] for g in groups); bottom = min(g['bottom'] for g in groups)
        above_end = min(bottom,math.floor(level_pixel)); rows = max(0,above_end-top)
        witnesses.append({'variant_index':variant_index,'threshold':variant['threshold'],'pair_index':pair_index,
            'source_pair_sha256':digest(pair),'jamb_group_indices':pair['jamb_group_indices'],
            'source_group_sha256':[digest(g) for g in groups], 'source_bounds_pixels':pair['bounds_pixels'],
            'common_jamb_row_interval_pixels':[top,bottom],
            'whole_rows_above_printed_level_interval_pixels':[top,above_end] if rows else None,
            'whole_rows_above_printed_level':rows,
            'nominal_head_above_printed_level_m':(datum-(pair['bounds_pixels'][1]*matrix.d+matrix.f))*factor,
            'nominal_bottom_above_printed_level_m':(datum-(pair['bounds_pixels'][3]*matrix.d+matrix.f))*factor,
            'minimum_above_level_rows_met':rows>=MINIMUM_ABOVE_LEVEL_ROWS})
    counts = [w['whole_rows_above_printed_level'] for w in witnesses]
    status = ('all_threshold_witnesses_support_above_level_rows' if min(counts)>=MINIMUM_ABOVE_LEVEL_ROWS else
              'threshold_witnesses_disagree_about_above_level_rows' if max(counts)>=MINIMUM_ABOVE_LEVEL_ROWS else
              'insufficient_above_level_rows_in_all_witnesses')
    result = {'consensus_family_index':family_index,'status':status,'witnesses':witnesses,
        'source_family_sha256':digest(family),'source_relative_reference_sha256':digest(reference),
        'source_gray_sha256':inventory['residual_raster_scan']['source_gray_sha256'],
        'printed_level_pixel_candidate':level_pixel,'minimum_above_level_rows':MINIMUM_ABOVE_LEVEL_ROWS,
        'observed_above_level_row_count_range':[min(counts),max(counts)],
        'observed_head_height_range_nominal_m':[min(w['nominal_head_above_printed_level_m'] for w in witnesses),
                                                max(w['nominal_head_above_printed_level_m'] for w in witnesses)],
        'physical_opening_verified':False,'physical_floor_role_verified':False,'vertical_datum_verified':False,
        'source_geometry_changed':False,'unsupported_intervals_filled':False}
    result['id'] = digest([VERSION,result]); return result


def run(corpus, source_pages, inventories, building_links, *, max_checks=100000):
    bounded_work(max_checks)
    if len(inventories)>32 or len({v['view_id'] for v in inventories})!=len(inventories):
        raise ValueError('Bounded unique source inventories required')
    result = {'version':VERSION,'status':'source_relative_elevation_context_only','pages':[],'views':[],
        'level_supported_width_links':[],'checks':0,
        'source_inventory_sha256':{v['view_id']:digest(v) for v in inventories},
        'source_building_links_sha256':digest(building_links),
        'scope_identity_basis':'automatic_view_id_not_a_printed_sheet_reference',
        'recipe':{'view_scope_mode':'whole_view_containment','minimum_above_level_rows':MINIMUM_ABOVE_LEVEL_ROWS,
            'threshold_policy':'all retained original consensus witnesses must qualify',
            'row_policy':'only whole original rows with bottom pixel edge at or above the printed level',
            'max_checks':max_checks},
        'elevation_facade_origin_status':'independent_elevation_facade_origin_required',
        'position_alignment_verified':False,'physical_opening_verified':False,'vertical_datum_verified':False,
        'world_geometry_additions':0,'training_labels_generated':0}
    def charge():
        result['checks'] += 1
        if result['checks']>max_checks: raise OverflowError('level_witness_work_budget')
    def hold(reason):
        return {**result,'status':'elevation_context_budget_withheld','reason':reason,
                'pages':[],'views':[],'level_supported_width_links':[]}
    selected = {(v['document_sha256'],v['page']) for v in inventories if v['printed_claim']['view_kind']=='elevation'}
    lookup = {v['view_id']:v for v in inventories}; reviewed = {}; total_families = 0
    try:
        for source_page in source_pages:
            key = (source_page['document_sha256'],source_page['page'])
            if key not in selected: continue
            views = [v for v in source_page['views'] if v['printed_claim']['view_kind']=='elevation']
            if len(views)>100: return hold('page_view_scope_budget')
            with pymupdf.open(corpus.root/'files'/(key[0]+'.pdf')) as document:
                page = document[key[1]-1]; display = (~native_inverse(page))*page.rotation_matrix
                scopes = []
                for view in views:
                    polygon = affine_transform(shape(view['geometry']),affine(display))
                    if not polygon.equals(box(*polygon.bounds)):
                        return {**result,'status':'rectangular_source_view_scope_required',
                                'pages':[],'views':[],'level_supported_width_links':[]}
                    scopes.append({'view_key_candidate':['automatic_view',view['id']],
                        'display_bounds':list(polygon.bounds),
                        'nominal_metres_per_pdf_point_candidate':view['nominal_metres_per_pdf_point']})
                try:
                    levels = elevation_levels.extract(page,key[0],key[1],scopes,max_checks=max_checks,
                                                     scope_mode='whole_view_containment')
                except ValueError as error:
                    if 'budget exceeded' not in str(error): raise
                    return hold(str(error))
            result['pages'].append({'document_sha256':key[0],'page':key[1],
                'source_page_view_records_sha256':digest(source_page),'source_scopes':scopes,
                'source_native_to_display_matrix':list(display),'level_review':levels})
            for view in views:
                if view['id'] not in lookup: continue
                inventory = lookup[view['id']]; reference = elevation_levels.relative_reference(levels,['automatic_view',view['id']])
                row = {'view_id':view['id'],'status':'source_relative_reference_required',
                    'relative_reference':reference,'families':[], 'pixel_edge_to_source_display_matrix':None,
                    'physical_floor_role_verified':False,'physical_opening_verified':False,'position_alignment_verified':False}
                if reference['status']=='unverified_source_relative_shop_level':
                    receipt = inventory['raster_coordinate_receipt']; scan = inventory['residual_raster_scan']
                    if receipt is None: row['status']='source_raster_coordinate_receipt_required'
                    elif scan.get('index') is None: row['status']='source_residual_scan_required'
                    else:
                        matrix = pymupdf.Matrix(receipt['pixel_edge_to_pdf_native_matrix'])*display
                        row['pixel_edge_to_source_display_matrix']=list(matrix)
                        if (abs(matrix.b)>1e-7 or abs(matrix.c)>1e-7 or matrix.a<=0 or matrix.d<=0):
                            row['status']='aligned_source_display_transform_required'
                        else:
                            row['status']='all_original_residual_families_reviewed_against_source_level'
                            hypotheses = {h['consensus_family_index']:h for h in inventory['residual_raster_hypotheses']}
                            total_families += len(scan['index']['consensus_families'])
                            if total_families>8192: return hold('retained_family_budget')
                            for i in range(len(scan['index']['consensus_families'])):
                                family = family_review(inventory,i,reference,list(matrix),charge)
                                family['residual_family_id']=hypotheses[i]['id']
                                family['candidate_scope_status']=hypotheses[i]['status']
                                row['families'].append(family); reviewed[(view['id'],hypotheses[i]['id'])]=family
                result['views'].append(row)
        if building_links['status']=='numbered_source_facade_candidates_only':
            for link in building_links['width_links']:
                charge(); family = reviewed.get((link['elevation_view_id'],link['residual_family_id']))
                if (family is None or family['status']!='all_threshold_witnesses_support_above_level_rows'
                        or family['candidate_scope_status']=='candidate_scope_crossing_withheld'): continue
                result['level_supported_width_links'].append({'elevation_view_id':link['elevation_view_id'],
                    'residual_family_id':link['residual_family_id'],'family_review_id':family['id'],
                    'source_building_link_sha256':digest(link),'projection_id':link['projection_id'],
                    'source_width_link_id':link['source_width_link_id'],
                    'physical_correspondence_verified':False,'position_alignment_verified':False})
        counts = Counter(f['status'] for v in result['views'] for f in v['families'])
        result['counts'] = {**dict(counts),'reviewed_residual_families':total_families,
            'native_level_marker_records':sum(len(p['level_review']['records']) for p in result['pages']),
            'relative_view_references':sum(v['relative_reference']['status']=='unverified_source_relative_shop_level' for v in result['views']),
            'source_building_width_links':len(building_links['width_links']),
            'level_supported_width_links':len(result['level_supported_width_links'])}
        return result
    except OverflowError as error: return hold(str(error))
