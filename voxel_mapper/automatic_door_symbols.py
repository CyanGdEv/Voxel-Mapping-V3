"""Original plan leaf/segmented-swing evidence; no aperture or scale acceptance."""
from collections import Counter, defaultdict
import math
import re

import pymupdf
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.strtree import STRtree

from .automatic_opening_links import bounded_work
from .drawing_footprints import fill_geometry, rings_from_path
from .drawing_page_tools import native_inverse
from .glyph_visibility import screen_architectural_span
from .generation_cycles import file_hash
from .ordinary_surfaces import label_runs
from .reconstruction_evidence_queue import digest

VERSION = 'automatic-original-door-symbols-v1'


def source_edges(page, source, charge):
    """Keep original short line items omitted by the broad 12-point extractor."""
    paths = page.get_drawings(extended=True)
    if len(paths)>100000:raise OverflowError('door_source_path_budget')
    matrix = native_inverse(page); frame = box(0,0,page.cropbox.width,page.cropbox.height)
    clips = []; groups = []; edges = []; excluded = Counter()
    for ordinal,path in enumerate(paths):
        charge(); level = path.get('level',0)
        clips = [c for c in clips if c['level']<level]; groups = [g for g in groups if g<level]
        if path['type']=='group':groups.append(level);continue
        if path['type']=='clip':
            if len(clips)>=16:raise OverflowError('door_clip_depth_budget')
            clip = {'level':level,'path_ordinal':ordinal,'geometry':None}
            try:
                if path.get('layer'):raise ValueError('optional clip layer')
                if len(path['items'])>1000:raise OverflowError('door_clip_item_budget')
                rings = rings_from_path({**path,'type':'f'},pymupdf.Matrix(1,1),4000)
                geometry = fill_geometry(rings,path.get('even_odd',False),True)
                if not geometry.is_valid or geometry.is_empty:raise ValueError('invalid clip')
                clip.update(geometry=geometry,source_rings=rings,even_odd=path.get('even_odd',False))
            except ValueError:pass
            clips.append(clip);continue
        if path['type']!='s':continue
        if (groups or any(c['geometry'] is None for c in clips) or path.get('layer')
                or path.get('stroke_opacity')!=1 or path.get('closePath')
                or not re.fullmatch(r'\s*\[\s*\]\s*0(?:\.0*)?\s*',str(path.get('dashes','unknown')))):
            excluded['unsupported_paint_or_clip_scope'] += 1;continue
        if len(path['items'])>1000:raise OverflowError('door_stroke_item_budget')
        if any(item[0]!='l' for item in path['items']):
            excluded['nonstraight_original_path'] += 1;continue
        width = path.get('width'); color = path.get('color')
        if (type(width) not in (int,float) or not math.isfinite(width) or not 0<width<=3
                or color is None or any(not math.isfinite(v) for v in color)):
            excluded['unsupported_stroke_style'] += 1;continue
        lines = [LineString([item[1],item[2]]) for item in path['items']]
        if any(not all(math.isfinite(v) for point in line.coords for v in point) for line in lines):
            raise ValueError('Finite original symbol edges required')
        # Screen the complete original path and stroke envelope, never trim it to a clip.
        if any(not frame.covers(line.buffer(width/2)) or any(not c['geometry'].covers(line.buffer(width/2)) for c in clips) for line in lines):
            excluded['whole_stroke_crosses_page_or_clip'] += 1;continue
        references = [{'path_ordinal':c['path_ordinal'],'level':c['level'],
            'source_rings':c['source_rings'],'even_odd':c['even_odd']} for c in clips]
        for index,line in enumerate(lines):
            charge()
            if line.length<.05:continue
            points = [list(pymupdf.Point(p)*matrix) for p in line.coords]
            row = {'document_sha256':source['document_sha256'],'page':source['page'],
                'path_ordinal':ordinal,'paint_seqno':path['seqno'],'item_index':index,
                'points_pdf_native':points,'stroke_width_pdf_points':width,'stroke_color':list(color),
                'clip_references':references,'whole_original_stroke_within_clip':True,
                'later_overpaint_visibility_verified':False}
            row['id'] = digest([VERSION,row]);edges.append(row)
            if len(edges)>20000:raise OverflowError('door_source_edge_budget')
    return {'edges':edges,'excluded_paths':dict(excluded),'source_paths':len(paths),
        'unrotated_mupdf_to_pdf_native_matrix':list(matrix)}


def find_symbols(gap, edges, charge):
    """Anchor every circle test to an original leaf endpoint; never fit a circle."""
    endpoints = gap['gap_endpoints_pdf_native']; width = math.dist(*endpoints)
    if not math.isfinite(width) or width<=0:raise ValueError('Finite positive source gap required')
    corridor = shape(gap['geometry_pdf_native']); axis = [(endpoints[1][i]-endpoints[0][i])/width for i in (0,1)]
    normal = [-axis[1],axis[0]]
    values = [p[0]*normal[0]+p[1]*normal[1] for p in corridor.exterior.coords]
    end_tolerance = (max(values)-min(values))/2+1.5
    if end_tolerance>.3*width:return {'status':'gap_depth_too_large_for_leaf_review','symbols':[]}
    geometry = [LineString(e['points_pdf_native']) for e in edges]; tree = STRtree(geometry)
    adjacency = defaultdict(list)
    for i,e in enumerate(edges):
        for p in e['points_pdf_native']:adjacency[tuple(p)].append(i)
    symbols = []
    for end,hinge_end in enumerate(endpoints):
        for index in sorted(tree.query(Point(hinge_end).buffer(end_tolerance)).tolist()):
            charge(); leaf = edges[index]; points = leaf['points_pdf_native']; radius = math.dist(*points)
            if not .65*width<=radius<=1.2*width:continue
            for origin_index in (0,1):
                hinge,tip = points[origin_index],points[1-origin_index]
                if math.dist(hinge,hinge_end)>end_tolerance:continue
                vector = [(tip[i]-hinge[i])/radius for i in (0,1)]
                if abs(sum(vector[i]*axis[i] for i in (0,1)))>math.sin(math.radians(15)):continue
                stack = [(tip,[],[tip],0.,0)]
                while stack:
                    charge(); point,path,vertices,sweep,sign = stack.pop()
                    if abs(sweep)>100:continue
                    choices = adjacency[tuple(point)]
                    if len(choices)>16:raise OverflowError('door_source_vertex_branch_budget')
                    extensions = []
                    for j in choices:
                        charge(); edge = edges[j]
                        if j==index or j in path:continue
                        if any(edge[k]!=leaf[k] for k in ('stroke_color','stroke_width_pdf_points','clip_references')):continue
                        a,b = edge['points_pdf_native']; other = b if a==point else a
                        residual = abs(math.dist(hinge,other)-radius)
                        if residual>max(.25,.015*radius):continue
                        u = [point[i]-hinge[i] for i in (0,1)]; v = [other[i]-hinge[i] for i in (0,1)]
                        delta = math.degrees(math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1]))
                        direction = 1 if delta>0 else -1
                        if not 1<=abs(delta)<=25 or (sign and direction!=sign):continue
                        extensions.append((other,[*path,j],[*vertices,other],sweep+delta,direction))
                    if len(path)<64:stack.extend(extensions)
                    if not extensions and len(path)>=4 and 80<=abs(sweep)<=100 and math.dist(point,endpoints[1-end])<=end_tolerance:
                        row = {'source_gap_id':gap['id'],'source_gap_sha256':digest(gap),
                            'leaf_edge_id':leaf['id'],'hinge_endpoint_index':origin_index,'hinge_gap_end_index':end,
                            'hinge_pdf_native':hinge,'leaf_tip_pdf_native':tip,'radius_pdf_points':radius,
                            'arc_edge_ids':[edges[j]['id'] for j in path],'arc_vertices_pdf_native':vertices,
                            'sweep_degrees':sweep,'maximum_radius_residual_pdf_points':max(abs(math.dist(hinge,p)-radius) for p in vertices),
                            'hinge_to_gap_end_distance_pdf_points':math.dist(hinge,hinge_end),
                            'closed_tip_to_gap_end_distance_pdf_points':math.dist(point,endpoints[1-end]),
                            'gap_end_tolerance_pdf_points':end_tolerance,'status':'original_segmented_door_swing_candidate',
                            'symbol_semantics_verified':False,'physical_opening_verified':False,
                            'hinge_fitted':False,'source_points_moved':False,'joints_snapped':False}
                        row['id'] = digest([VERSION,row]);symbols.append(row)
                        if len(symbols)>128:raise OverflowError('door_symbol_candidate_budget')
    return {'status':'original_leaf_and_swing_candidates_only','symbols':sorted(symbols,key=lambda r:r['id'])}


def run(corpus, source_pages, inventories, returns, *, max_checks=100000):
    bounded_work(max_checks); lookup = {v['view_id']:v for v in inventories}
    pins = {k:digest(v) for k,v in lookup.items()}
    if len(inventories)>32 or len(lookup)!=len(inventories):raise ValueError('Bounded unique symbol inventories required')
    if returns['source_inventory_sha256']!=pins:raise ValueError('Matching original return inventories required')
    selected = [v for p in source_pages for v in p['views'] if v['id'] in lookup]
    if (len(selected)!=len(lookup) or len({v['id'] for v in selected})!=len(lookup)
            or any(digest(v)!=lookup[v['id']]['source_view_sha256'] for v in selected)):
        raise ValueError('Matching unique original symbol views required')
    result = {'version':VERSION,'status':'original_door_symbol_evidence_only',
        'source_inventory_sha256':pins,'source_wall_return_corners_sha256':digest(returns),
        'pages':[],'views':[],'conditional_position_links':[],'checks':0,
        'recipe':{'max_checks':max_checks,'native_radius_tolerance_pdf_points':.25,
            'relative_radius_tolerance':.015,'sweep_degrees':[80,100],'segment_angle_degrees':[1,25],
            'leaf_to_gap_length_ratio':[.65,1.2],'maximum_leaf_axis_difference_from_perpendicular_degrees':15,
            'source_connectivity':'exact_original_endpoint_equality','complete_source_arc_required':True,'circle_fit_allowed':False},
        'physical_opening_verified':False,'artwork_scale_verified':False,
        'world_geometry_additions':0,'training_labels_generated':0}
    def charge():
        result['checks'] += 1
        if result['checks']>max_checks:raise OverflowError('door_symbol_work_budget')
    try:
        for source in sorted(source_pages,key=lambda p:(p['document_sha256'],p['page'])):
            views = [v for v in source['views'] if v['id'] in lookup and v['printed_claim']['view_kind']=='plan'
                and v['printed_claim'].get('plan_level_or_form')!='roof']
            if not views:continue
            source_path = corpus.root/'files'/(source['document_sha256']+'.pdf')
            if file_hash(source_path)!=source['document_sha256']:raise ValueError('Original symbol PDF checksum mismatch')
            with pymupdf.open(source_path) as document:
                page = document[source['page']-1]
                recovered = source_edges(page,source,charge); notes = []
                traces = page.get_texttrace()
                if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:raise OverflowError('door_note_text_budget')
                for run in label_runs(traces):
                    charge(); text = ''.join(chr(c[0]) for c in run['chars']).strip()
                    if not re.search(r'\b(?:illustrative|indicative)\b',text,re.I):continue
                    rect = pymupdf.Rect(run['bbox']); matrix = native_inverse(page)
                    note = {'text':text,'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
                        'geometry_pdf_native':Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)]).__geo_interface__,
                        'glyph_screen':screen_architectural_span(page,run),'scope':'original_page_wording_component_application_unverified'}
                    note['id']=digest(note);notes.append(note)
                    if len(notes)>64:raise OverflowError('door_note_candidate_budget')
            if file_hash(source_path)!=source['document_sha256']:raise ValueError('Original symbol PDF changed during review')
            page_row = {'document_sha256':source['document_sha256'],'page':source['page'],
                'source_page_views_sha256':digest(source),**recovered,'illustrative_wording':notes}
            result['pages'].append(page_row)
            for view in views:
                charge(); scope = shape(view['geometry'])
                whole = [e for e in recovered['edges'] if scope.covers(LineString(e['points_pdf_native']))]
                row = {'view_id':view['id'],'source_view_sha256':digest(view),
                    'source_edges_sha256':digest(whole),'whole_edge_ids':[e['id'] for e in whole],'gaps':[]}
                for gap in lookup[view['id']]['plan_gap_review']['gaps']:
                    charge(); found = find_symbols(gap,recovered['edges'],charge)
                    whole_ids = {e['id'] for e in whole}
                    crossing = [s['id'] for s in found['symbols'] if not {s['leaf_edge_id'],*s['arc_edge_ids']}<=whole_ids]
                    found['symbols'] = [s for s in found['symbols'] if s['id'] not in crossing]
                    row['gaps'].append({'source_gap_id':gap['id'],'source_gap_sha256':digest(gap),
                        **found,'whole_source_symbol_crosses_view_ids':crossing})
                result['views'].append(row)
        by_gap = {(v['view_id'],g['source_gap_sha256']):g['symbols'] for v in result['views'] for g in v['gaps']}
        for diagnostic in returns['diagnostics']:
            for position in diagnostic['position_comparisons']:
                charge()
                if position['status']!='all_witness_positions_compatible':continue
                gap_sha = position['source_gap_projection']['source_gap_sha256']
                candidates = [(view_id,s) for (view_id,pin),symbols in by_gap.items() if pin==gap_sha for s in symbols]
                result['conditional_position_links'].append({'source_position_comparison_id':position['id'],
                    'source_position_comparison_sha256':digest(position),'source_gap_sha256':gap_sha,
                    'symbol_candidates':[{'plan_view_id':v,'symbol_id':s['id']} for v,s in candidates],
                    'status':'source_door_symbol_support_only' if candidates else 'original_door_symbol_not_found',
                    'physical_opening_verified':False,'artwork_scale_verified':False})
        result['counts'] = {'source_pages':len(result['pages']),'source_edges':sum(len(p['edges']) for p in result['pages']),
            'plan_gaps_reviewed':sum(len(v['gaps']) for v in result['views']),
            'gaps_with_symbol_candidates':sum(bool(g['symbols']) for v in result['views'] for g in v['gaps']),
            'symbol_candidates':sum(len(g['symbols']) for v in result['views'] for g in v['gaps']),
            'conditional_positions_with_symbol_support':sum(bool(l['symbol_candidates']) for l in result['conditional_position_links']),
            'illustrative_wording_records':sum(len(p['illustrative_wording']) for p in result['pages'])}
        return result
    except OverflowError as error:
        return {**result,'status':'door_symbol_budget_withheld','reason':str(error),
            'pages':[],'views':[],'conditional_position_links':[],'counts':{}}
