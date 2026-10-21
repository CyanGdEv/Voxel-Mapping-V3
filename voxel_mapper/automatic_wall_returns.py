"""Original paint-side corners and conditional facade correspondence; no repair."""
from collections import Counter
import math

import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Point, mapping, shape

from . import automatic_facade_alignment
from .automatic_opening_links import affine, bounded_work
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-wall-return-corners-v1'
NEIGHBOURHOOD = .25
PROBE = .1
COSINE = math.cos(math.radians(5))


def paint_profile(fill, geometry, frame, unit, charge):
    axis = np.asarray(frame['diagnostic_axis'],dtype=float); normal = np.array([-axis[1],axis[0]])
    origin = np.asarray(frame['source_native_endpoints'][0],dtype=float)
    look = float(np.dot(frame['marker_direction_pdf_native'],normal))
    if (not np.isfinite([*axis,*origin,*frame['marker_direction_pdf_native'],look]).all()
            or type(unit) not in (int,float) or not math.isfinite(unit) or unit<=0
            or abs(np.linalg.norm(axis)-1)>1e-6 or abs(look)<1e-6):
        raise ValueError('Unit source frame axis and nonparallel marker direction required')
    towards = -normal*(1 if look>0 else -1); vertices = []; edges = []
    for part_index,part in enumerate(geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry]):
        coords = list(part.exterior.coords)[:-1]
        for index,point in enumerate(coords):
            charge(); delta = np.asarray(point)-origin
            vertex = {'part_index':part_index,'exterior_vertex_index':index,'point_pdf_native':list(point),
                'along_pdf_points':float(delta@axis),'normal_pdf_points':float(delta@normal),
                'adjacent_edge_indices':[(index-1)%len(coords),index]}
            vertex['id'] = digest([VERSION,fill['id'],frame['id'],'vertex',part_index,index]); vertices.append(vertex)
            other = coords[(index+1)%len(coords)]; vector = np.asarray(other)-point; length = float(np.linalg.norm(vector))
            if length==0: continue
            midpoint = (np.asarray(point)+other)/2; a = midpoint+towards*PROBE; b = midpoint-towards*PROBE
            edge = {'part_index':part_index,'edge_index':index,'source_native_endpoints':[list(point),list(other)],
                'axis_alignment_cosine':abs(float(vector@axis/length)),
                'marker_probe_pdf_native':a.tolist(),'away_probe_pdf_native':b.tolist(),
                'paint_on_marker_side':geometry.contains(Point(a)), 'paint_on_away_side':geometry.contains(Point(b))}
            edges.append(edge)
    row = {'source_fill_id':fill['id'],'source_fill_sha256':digest(fill),
        'geometry_pdf_native':mapping(geometry),'source_geometry_sha256':digest(mapping(geometry)),
        'source_part_count':len(geometry.geoms) if geometry.geom_type=='MultiPolygon' else 1,
        'source_hole_count':sum(len(p.interiors) for p in (geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry])),
        'source_paint_seqno':fill['paint_seqno'],'source_clip_path_ordinals':[c['path_ordinal'] for c in fill['clip_references']],
        'vertices':vertices,'edges':edges,'along_interval_pdf_points':[min(v['along_pdf_points'] for v in vertices),max(v['along_pdf_points'] for v in vertices)],
        'normal_interval_pdf_points':[min(v['normal_pdf_points'] for v in vertices),max(v['normal_pdf_points'] for v in vertices)],
        'marker_direction_normal_projection':look,'source_geometry_changed':False,
        'physical_wall_role_verified':False,'later_overpaint_visibility_verified':False}
    row['id'] = digest([VERSION,row]); return row


def corner(profile_list, base, return_profile, end, side, charge):
    low,high = base['normal_interval_pdf_points']; look = base['marker_direction_normal_projection']
    plane = (low if look>0 else high) if side=='marker_facing' else (high if look>0 else low)
    endpoint = base['along_interval_pdf_points'][0 if end=='left' else 1]
    return_width = return_profile['along_interval_pdf_points'][1]-return_profile['along_interval_pdf_points'][0]
    band = max(high-low,return_width)+NEIGHBOURHOOD; candidates = []
    for profile in profile_list:
        edges = {(e['part_index'],e['edge_index']):e for e in profile['edges']}
        vertex_normal = {(v['part_index'],v['exterior_vertex_index']):v['normal_pdf_points'] for v in profile['vertices']}
        sizes = Counter(v['part_index'] for v in profile['vertices'])
        for vertex in profile['vertices']:
            charge()
            if abs(vertex['normal_pdf_points']-plane)>NEIGHBOURHOOD or abs(vertex['along_pdf_points']-endpoint)>band:continue
            support = []
            for index in vertex['adjacent_edge_indices']:
                edge = edges.get((vertex['part_index'],index))
                if edge is None or edge['axis_alignment_cosine']<COSINE:continue
                ends = [vertex_normal[(vertex['part_index'],j)] for j in (index,(index+1)%sizes[vertex['part_index']])]
                desired = (False,True) if side=='marker_facing' else (True,False)
                if (max(abs(v-plane) for v in ends)<=NEIGHBOURHOOD
                        and (edge['paint_on_marker_side'],edge['paint_on_away_side'])==desired):support.append(index)
            if support:candidates.append({**vertex,'source_profile_id':profile['id'],'supporting_original_edge_indices':support})
    if not candidates:return {'status':'original_corner_vertex_required','candidates':[],'selected_vertex':None}
    value = (min if end=='left' else max)(v['along_pdf_points'] for v in candidates)
    extreme = [v for v in candidates if abs(v['along_pdf_points']-value)<=1e-9]
    return {'status':'original_paint_side_vertex_candidate','source_plane_pdf_points':plane,
        'end_neighbourhood_pdf_points':band,'candidates':candidates,'extreme_vertex_ids':[v['id'] for v in extreme],
        'selected_vertex':extreme[0],'selection_recipe':'original_minimum_or_maximum_source_axis_coordinate_before_elevation_comparison',
        'physical_corner_identity_verified':False}


def review_returns(plan, view, frame, extent, charge):
    fills = plan['plan_gap_review']['page_fill_recovery']['candidates']
    if len(fills)>4000:raise OverflowError('source_paint_budget')
    original = next(f for f in fills if f['id']==extent['source_id'])
    if digest(original)!=extent['source_record_sha256']:raise ValueError('Matching original source paint required')
    unit = plan['nominal_metres_per_pdf_point']; geometry = shape(extent['geometry_pdf_native'])
    matrix = pymupdf.Matrix(plan['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
    if not affine_transform(shape(original['geometry']),affine(matrix)).equals_exact(geometry,0):
        raise ValueError('Unchanged original source paint geometry required')
    base = paint_profile(original,geometry,frame,unit,charge)
    result = {'source_extent_id':extent['id'],'source_extent_sha256':digest(extent),
        'base_profile':base,'return_profiles':[],'return_candidates':{'left':[],'right':[]},
        'corner_pairs':[],'withheld_crossing_paints':[],'status':'source_strip_proportions_required'}
    x0,x1 = base['along_interval_pdf_points']; y0,y1 = base['normal_interval_pdf_points']
    if not (.08<=(y1-y0)*unit<=1 and x1-x0>=3*(y1-y0)):return result
    zone = shape(view['geometry'])
    for fill in sorted(fills,key=lambda f:f['id']):
        charge()
        if (fill['id']==original['id'] or fill['fill_color']!=original['fill_color']
                or fill['fill_opacity']!=1 or original['fill_opacity']!=1):continue
        native = affine_transform(shape(fill['geometry']),affine(matrix)); distance = geometry.distance(native)
        if distance>NEIGHBOURHOOD:continue
        if not zone.covers(native):
            result['withheld_crossing_paints'].append({'source_fill_id':fill['id'],'status':'whole_return_paint_crosses_view'});continue
        profile = paint_profile(fill,native,frame,unit,charge)
        a,b = profile['along_interval_pdf_points']; c,d = profile['normal_interval_pdf_points']
        if not (.08<=(b-a)*unit<=1 and d-c>=3*(b-a) and max(c-y1,y0-d,0)<=NEIGHBOURHOOD):continue
        ends = [end for end,value in [('left',x0),('right',x1)] if a-NEIGHBOURHOOD<=value<=b+NEIGHBOURHOOD]
        if not ends:continue
        result['return_profiles'].append(profile)
        for end in ends:result['return_candidates'][end].append({'source_profile_id':profile['id'],
            'source_boundary_distance_pdf_points':distance,'exact_source_contact':distance==0,
            'joint_geometry_repaired':False,'physical_return_identity_verified':False})
        if len(result['return_profiles'])>64:raise OverflowError('source_return_candidate_budget')
    lookup = {p['id']:p for p in result['return_profiles']}
    result['status']=('paired_perpendicular_return_candidates_only' if all(result['return_candidates'].values())
                      else 'both_original_perpendicular_returns_required')
    for left in result['return_candidates']['left']:
        for right in result['return_candidates']['right']:
            charge()
            if left['source_profile_id']==right['source_profile_id']:continue
            for side in ('marker_facing','away_from_marker'):
                a = corner([base,lookup[left['source_profile_id']]],base,lookup[left['source_profile_id']],'left',side,charge)
                b = corner([base,lookup[right['source_profile_id']]],base,lookup[right['source_profile_id']],'right',side,charge)
                row = {'paint_side':side,'left_return':left,'right_return':right,'corners':[a,b],
                    'status':'original_corner_pair_candidate' if all(c['selected_vertex'] is not None for c in (a,b)) else 'original_corner_vertex_required',
                    'source_geometry_changed':False,'physical_facade_extent_verified':False}
                row['id'] = digest([VERSION,extent['id'],frame['id'],row]);result['corner_pairs'].append(row)
                if len(result['corner_pairs'])>128:raise OverflowError('source_corner_pair_budget')
    return result


def run(source_pages, inventories, buildings, levels, alignment, scale, *, max_checks=100000):
    bounded_work(max_checks); lookup = {v['view_id']:v for v in inventories}; pins = {k:digest(v) for k,v in lookup.items()}
    if len(inventories)>32 or len(lookup)!=len(inventories):raise ValueError('Bounded unique source inventories required')
    if (buildings['source_inventory_sha256']!=pins or levels['source_inventory_sha256']!=pins
            or levels['source_building_links_sha256']!=digest(buildings)
            or alignment['source_inventory_sha256']!=pins or alignment['source_building_links_sha256']!=digest(buildings)
            or alignment['source_level_context_sha256']!=digest(levels)
            or scale['source_inventory_sha256']!=pins or scale['source_facade_alignment_sha256']!=digest(alignment)
            or scale['source_building_links_sha256']!=digest(buildings) or scale['source_level_context_sha256']!=digest(levels)):
        raise ValueError('Matching source scale and facade reviews required')
    result = {'version':VERSION,'status':'original_paint_return_corner_hypotheses_only','frames':[],'diagnostics':[],'checks':0,
        'source_inventory_sha256':pins,'source_building_links_sha256':digest(buildings),
        'source_level_context_sha256':digest(levels),'source_facade_alignment_sha256':digest(alignment),
        'source_sheet_scale_sha256':digest(scale),'recipe':{'source_neighbourhood_pdf_points':NEIGHBOURHOOD,
            'paint_side_probe_pdf_points':PROBE,'maximum_axis_difference_degrees':5.,'raw_strip_thickness_m':[.08,1.],
            'minimum_strip_aspect_ratio':3,'corner_selection':'source_side_extrema_before_width_or_opening_comparison',
            'source_geometry_repair_allowed':False,'max_checks':max_checks},
        'physical_corner_identity_verified':False,'layout_application_verified':False,'position_alignment_verified':False,
        'physical_opening_verified':False,'world_geometry_additions':0,'training_labels_generated':0}
    if (alignment['status']!='independent_source_extent_and_origin_hypotheses_only'
            or scale['status']!='peripheral_sheet_layout_evidence_only'):
        return {**result,'status':'complete_facade_and_sheet_scale_required'}
    selected = [v for p in source_pages for v in p['views'] if v['id'] in lookup]
    if (len(selected)!=len(lookup) or len({v['id'] for v in selected})!=len(lookup)
            or any(digest(v)!=lookup[v['id']]['source_view_sha256'] for v in selected)):
        raise ValueError('Matching unique automatic source views required')
    views = {v['id']:v for v in selected}; records = {r['id']:r for r in buildings['frames']}
    families = {f['id']:f for v in levels['views'] for f in v['families']}
    level_views = {v['view_id']:v for v in levels['views']}; pairs = {p['id']:p for p in scale['pairs']}
    def charge():
        result['checks'] += 1
        if result['checks']>max_checks:raise OverflowError('wall_return_work_budget')
    def hold(reason):
        return {**result,'status':'wall_return_budget_withheld','reason':reason,'frames':[],'diagnostics':[],'counts':{}}
    try:
        for row in alignment['frames']:
            record = records[row['facade_record_id']]; plan = lookup[record['plan_view_id']]
            for review in row['frame_reviews']:
                charge(); frame = next(f for f in record['frame_review']['frames'] if f['id']==review['frame_id'])
                traces = [review_returns(plan,views[plan['view_id']],frame,e,charge)
                          for e in review['plan_extents'] if e['source_kind']=='near_ray_original_paint']
                result['frames'].append({'facade_record_id':record['id'],'frame_id':frame['id'],
                    'source_frame_review_sha256':digest(review),'paint_reviews':traces})
                for diagnostic in scale['diagnostics']:
                    if diagnostic['source_frame_review_sha256']!=digest(review):continue
                    pair = pairs[diagnostic['pair_id']]; inverse = np.asarray(pair['layout_fit']['subject_to_reference_linear_row_matrix'])
                    axis = np.asarray(frame['diagnostic_axis'])@inverse; axis /= np.linalg.norm(axis)
                    origin = np.asarray(frame['source_native_endpoints'][0]); unit = plan['nominal_metres_per_pdf_point']
                    def project(point):return float((np.asarray(point)-origin)@inverse@axis*unit)
                    target = record['target_elevation_view_ids'][0]; matrix = level_views[target]['pixel_edge_to_source_display_matrix']
                    for trace in traces:
                        for corner_pair in trace['corner_pairs']:
                            charge()
                            if corner_pair['status']!='original_corner_pair_candidate':continue
                            points = [c['selected_vertex']['point_pdf_native'] for c in corner_pair['corners']]
                            interval = sorted(project(p) for p in points)
                            extent = {'id':corner_pair['id'],'nominal_plan_position_interval_m':interval}
                            raw = {'id':corner_pair['id'],'nominal_plan_position_interval_m':
                                [c['selected_vertex']['along_pdf_points']*unit for c in corner_pair['corners']]}
                            item = {'source_corner_pair_id':corner_pair['id'],'source_corner_pair_sha256':digest(corner_pair),
                                'pair_id':pair['id'],'frame_id':frame['id'],'facade_record_id':record['id'],
                                'source_points_pdf_native':points,'layout_position_interval_m':interval,
                                'raw_width_comparisons':[],'layout_width_comparisons':[],'position_comparisons':[],
                                'layout_application_verified':False,'physical_corner_identity_verified':False}
                            parents = sorted({r['parent_family_review_id'] for r in review['parent_child_relations']})
                            for identity in parents:
                                parent = families[identity]
                                item['raw_width_comparisons'].append(automatic_facade_alignment.compare_extent(raw,parent,matrix,lookup[target]['nominal_metres_per_pdf_point'],charge))
                                width = automatic_facade_alignment.compare_extent(extent,parent,matrix,lookup[target]['nominal_metres_per_pdf_point'],charge)
                                item['layout_width_comparisons'].append(width)
                                if width['status']!='all_witness_extent_widths_compatible':continue
                                seen = set()
                                for relation in review['parent_child_relations']:
                                    if relation['parent_family_review_id']!=identity:continue
                                    link = next(l for l in levels['level_supported_width_links'] if digest(l)==relation['source_level_link_sha256'])
                                    projection = next(p for p in buildings['projected_gaps'] if p['id']==link['projection_id'])
                                    child = families[relation['child_family_review_id']]
                                    if (projection['id'],child['id']) in seen:continue
                                    seen.add((projection['id'],child['id']))
                                    gap = next(g for g in plan['plan_gap_review']['gaps'] if g['id']==projection['source_gap_id'])
                                    projected = {'id':projection['id'],'source_projection_sha256':digest(projection),
                                        'source_gap_sha256':digest(gap),'nominal_plan_position_interval_m':sorted(project(p) for p in gap['gap_endpoints_pdf_native'])}
                                    for reverse in (False,True):
                                        position = automatic_facade_alignment.compare_position(extent,parent,child,projected,matrix,
                                            lookup[target]['nominal_metres_per_pdf_point'],reverse,charge)
                                        position.update(source_gap_projection=projected,source_extent_comparison_id=width['id'],
                                            conditional_on_original_corner_and_layout_hypotheses=True)
                                        item['position_comparisons'].append(position)
                            result['diagnostics'].append(item)
        traces = [p for r in result['frames'] for p in r['paint_reviews']]
        result['counts'] = {'source_frame_reviews':len(result['frames']),'near_ray_paint_reviews':len(traces),
            'perpendicular_return_candidates':sum(len(r) for t in traces for r in t['return_candidates'].values()),
            'original_corner_pairs':sum(p['status']=='original_corner_pair_candidate' for t in traces for p in t['corner_pairs']),
            'layout_width_comparisons':sum(len(d['layout_width_comparisons']) for d in result['diagnostics']),
            'layout_widths_compatible':sum(c['status']=='all_witness_extent_widths_compatible' for d in result['diagnostics'] for c in d['layout_width_comparisons']),
            'position_comparisons':sum(len(d['position_comparisons']) for d in result['diagnostics']),
            'conditional_positions_compatible':sum(p['status']=='all_witness_positions_compatible' for d in result['diagnostics'] for p in d['position_comparisons'])}
        return result
    except OverflowError as error:return hold(str(error))
