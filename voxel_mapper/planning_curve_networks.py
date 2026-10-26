"""Endpoint-exact assembled curved source rings; physical surfaces stay unverified."""
from collections import Counter,defaultdict
from concurrent.futures import CancelledError
import base64
import hashlib
from html import escape
import json
import math
import re

import pymupdf
from shapely.geometry import LineString,Point,MultiPoint,box,shape,mapping
from shapely.ops import polygonize_full,unary_union,split
from shapely.strtree import STRtree

from . import drawing_geometry,ordinary_surfaces,planning_curved_boundaries,planning_surface_footprints
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION='planning-open-curve-networks-v1'
TOLERANCE_POINTS=.05
DIAGNOSTIC_LIMIT=128
LIMITS={'max_native_candidates':10000,'max_native_points':200000,
        'max_segments':20000,'max_pair_checks':100000,'max_faces':500,
        'max_face_provenance':2048,'max_source_operators':20000,
        'max_source_control_points':100000,'max_output_bytes':8000000}


def _limits(options):
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):
        raise ValueError('Known open-curve network limits required')
    limits={**LIMITS,**options}
    if (any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items())
            or limits['max_output_bytes']<16384):
        raise ValueError('Lower-only open-curve network limits required')
    return limits


def _recover(parents,limits,check,charge):
    """Node actual straight intersections, retaining curved operator endpoints."""
    geometries=[shape(row['geometry']) for row in parents]
    endpoints=[{tuple(g.coords[0]),tuple(g.coords[-1])} for g in geometries]
    errors=[row['curve_approximation']['chord_error_bound_pdf_points'] for row in parents]
    segments=sum(len(g.coords)-1 for g in geometries)
    if segments>limits['max_segments']:raise ValueError('open_curve_segment_budget_exceeded')
    adjacency=defaultdict(list)
    for i,points in enumerate(endpoints):
        check()
        for point in points:adjacency[point].append(i)
    index=STRtree(geometries);blocked=set();counts=Counter();maximum=max(errors,default=0)
    for i,g in enumerate(geometries):
        check();distance=errors[i]+maximum
        area=g.buffer(distance) if distance else g
        for raw in index.query(area):
            j=int(raw)
            if j<=i:continue
            charge();h=geometries[j]
            intersection=g.intersection(h)
            if not intersection.is_empty:
                points=([intersection] if intersection.geom_type=='Point' else
                        list(intersection.geoms) if intersection.geom_type=='MultiPoint' else [])
                curved_i=bool(parents[i]['curve_approximation']['cubic_segments'])
                curved_j=bool(parents[j]['curve_approximation']['cubic_segments'])
                if not curved_i and not curved_j:
                    counts['original_straight_intersection_pairs']+=1;continue
                permitted=(endpoints[i]&endpoints[j] if curved_i and curved_j else
                           endpoints[i] if curved_i else endpoints[j])
                if not points or any(tuple(p.coords[0]) not in permitted for p in points):
                    blocked.update((i,j));counts['interior_crossing_or_overlap_pairs']+=1
            elif g.distance(h)<=errors[i]+errors[j]:
                blocked.update((i,j));counts['uncertain_near_curve_pairs']+=1
    counts.update(source_edges=len(parents),flattened_segments=segments,
        exact_endpoint_nodes=len(adjacency),dangling_endpoint_nodes=sum(len(v)==1 for v in adjacency.values()),
        branched_endpoint_nodes=sum(len(v)>2 for v in adjacency.values()),blocked_edges=len(blocked))
    straight=[g for p,g in zip(parents,geometries) if not p['curve_approximation']['cubic_segments']]
    curved=[g for p,g in zip(parents,geometries) if p['curve_approximation']['cubic_segments']]
    linework=unary_union(straight) if straight else None
    straight_parts=[] if linework is None else list(linework.geoms) if hasattr(linework,'geoms') else [linework]
    curve_nodes=sorted({tuple(q) for g in curved for q in (g.coords[0],g.coords[-1])})
    node_points=[Point(q) for q in curve_nodes];node_index=STRtree(node_points)
    network=[];known_curve_nodes=set()
    for g in straight_parts:
        check();nodes=[]
        for raw in node_index.query(g):
            charge();point=node_points[int(raw)]
            if g.covers(point):
                known_curve_nodes.add(tuple(point.coords[0]))
                if tuple(point.coords[0]) not in (g.coords[0],g.coords[-1]):nodes.append(point)
        network.extend(split(g,MultiPoint(nodes)).geoms if nodes else [g])
    network+=curved
    if sum(len(g.coords) for g in network)>limits['max_native_points']:
        raise ValueError('open_curve_noded_point_budget_exceeded')
    counts['noded_straight_parts']=len(network)-len(curved)
    faces,cuts,dangles,invalid=polygonize_full(network)
    counts.update(raw_faces=len(faces.geoms),cut_edges=len(cuts.geoms),
                  dangles=len(dangles.geoms),invalid_rings=len(invalid.geoms))
    if len(faces.geoms)>limits['max_faces']:raise ValueError('open_curve_face_budget_exceeded')
    records=[]
    for face in sorted(faces.geoms,key=lambda f:f.normalize().wkb_hex):
        check()
        if not face.is_valid or face.area<16:
            counts['invalid_or_small_faces']+=1;continue
        source=[];coverage=[]
        for raw in index.query(face.boundary):
            charge();i=int(raw);g=geometries[i]
            # This epsilon is only for provenance overlays. It never joins
            # endpoints or enters polygonize_full above.
            covered=g.intersection(face.boundary).length
            if covered<=1e-7:continue
            source.append(i);coverage.append(g)
        if not any(parents[i]['curve_approximation']['cubic_segments'] for i in source):
            counts['straight_only_faces_already_handled_elsewhere']+=1;continue
        if any(i in blocked for i in source):
            counts['crossing_or_uncertain_boundary_faces_withheld']+=1;continue
        if len(source)>limits['max_face_provenance']:
            raise ValueError('open_curve_face_provenance_budget_exceeded')
        if not coverage or not unary_union(coverage).buffer(1e-7).covers(face.boundary):
            counts['incomplete_original_edge_coverage']+=1;continue
        error=max(errors[i] for i in source)
        records.append({'geometry':mapping(face),'parent_indices':sorted(source),
                        'chord_error_bound_pdf_points':error})
    counts['assembled_curved_faces']=len(records)
    return records,dict(counts),known_curve_nodes


def _operator_edges(parents,check,source_parts):
    """Expose original operator joints, never interpolated curve/chord nodes."""
    edges=[]
    for parent in parents:
        check();reference=parent['paint_references'][0]
        parts,approximations=source_parts(reference['ordinal'])
        coords=parts[reference['subpath']]
        if not LineString(coords).equals(shape(parent['geometry'])):
            raise ValueError('Original scoped stroke subpath required')
        for part in approximations[reference['subpath']]['operator_ranges']:
            points=coords[part['start_vertex']:part['end_vertex']+1]
            if len(points)<2 or all(p==points[0] for p in points):continue
            geometry=mapping(LineString(points))
            edges.append({'id':digest([VERSION,parent['id'],part['operator_index'],geometry]),
                'document_sha256':parent['document_sha256'],'page':parent['page'],
                'coordinate_frame':parent['coordinate_frame'],'geometry':geometry,
                'source_parent':parent,'source_parent_sha256':digest(parent),
                'source_operator_index':part['operator_index'],'extraction_kind':'original_operator_network_edge',
                'source_operator_reference':{'ordinal':reference['ordinal'],
                    'subpath':reference['subpath'],'operator_index':part['operator_index']},
                'paint_references':parent['paint_references'],
                'curve_approximation':{'cubic_segments':part['cubic_segments'],
                    'chord_error_bound_pdf_points':part['chord_error_bound_pdf_points'],
                    'requested_tolerance_pdf_points':TOLERANCE_POINTS},
                'physical_identity_verified':False,'world_geometry_additions':0})
    return edges


def page_review(page,sha,number,surfaces,*,options=None,cancelled=lambda:False,source_scope_plan=None,_source_cache=None):
    """Recover source rings within existing whole-primitive surface scopes.

    These are source geometry hypotheses, not an ordinary source-outline
    inventory or an input to the physical/world stages. Curve topology near
    shared endpoints and physical interpretation remain unverified.
    """
    limits=_limits(options)
    if (not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
            or type(number) is not int or number<1 or page.number+1!=number):
        raise ValueError('Original document hash and matching page required')
    if (not isinstance(surfaces,dict) or surfaces.get('document_sha256')!=sha or surfaces.get('page')!=number
            or surfaces.get('version')!=planning_surface_footprints.VERSION
            or surfaces.get('coordinate_frame')!='pdf_native_points_y_up'):
        raise ValueError('Same-source surface analysis required')
    def check():
        if cancelled():raise CancelledError('Open curved network review cancelled')
    result={'version':VERSION,'document_sha256':sha,'page':number,
        'coordinate_frame':'pdf_native_points_y_up','source_surface_analysis_sha256':digest(surfaces),
        'limits':limits,'status':'assembled_curved_source_boundary_review','analysis_complete':True,
        'records':[],'regions':[],'curve_chain_diagnostics':[],
        'diagnostic_limit':DIAGNOSTIC_LIMIT,'curve_tolerance_pdf_points':TOLERANCE_POINTS,
        'endpoint_snapping_performed':False,'original_straight_intersection_noding_enabled':True,
        'curve_interior_intersection_noding_performed':False,
        'topology_against_exact_curves_verified':False,'physical_identity_verified':False,
        'world_placement_eligible':False,'world_geometry_additions':0,'training_labels_generated':0}
    def fail(reason):
        result.update(status='open_curved_network_review_withheld',analysis_complete=False,
                      reason=reason,records=[],curve_chain_diagnostics=[])
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            result.pop('regions',None);result.pop('extraction',None)
        return result
    checks=0
    def charge():
        nonlocal checks
        check();checks+=1
        if checks>limits['max_pair_checks']:raise ValueError('open_curve_pair_work_budget_exceeded')
    check()
    if not surfaces.get('analysis_complete'):return fail('complete_surface_scope_analysis_required')
    if source_scope_plan is not None:
        if (not isinstance(source_scope_plan,dict) or source_scope_plan.get('version')!='planning-complete-curve-scopes-v1'
                or source_scope_plan.get('document_sha256')!=sha or source_scope_plan.get('page')!=number
                or source_scope_plan.get('source_surface_analysis_sha256')!=digest(surfaces)):
            raise ValueError('Same-source complete curve scope plan required')
        if not source_scope_plan.get('analysis_complete'):return fail('complete_curve_source_scope_plan_required')
        scopes=source_scope_plan['regions']
        result.update(source_scope_plan_sha256=digest(source_scope_plan),
            source_scope_kind='complete_original_stroke_style_families',
            physical_role_inferred_from_style=False)
    else:scopes=surfaces.get('extraction',{}).get('regions',[])
    if not isinstance(scopes,list) or len(scopes)>32:raise ValueError('Bounded original source scopes required')
    if not scopes:return result
    windows=[r['region_native_points'] for r in scopes]
    labels=surfaces.get('labels',[])
    if not isinstance(labels,list) or len(labels)>256:raise ValueError('Bounded original surface labels required')
    operators=controls=covered=0;seen=set();witness_cache={};counts=Counter();diagnostics={}
    try:
        cache=ordinary_surfaces._source_page_cache(page) if _source_cache is None else _source_cache
        if cache.get('page') is not page or cache.get('source_content_sha256')!=hashlib.sha256(page.read_contents()).hexdigest():
            raise ValueError('Same unchanged original network page cache required')
        check()
        if source_scope_plan is not None and source_scope_plan.get('source_content_sha256')!=cache['source_content_sha256']:
            raise ValueError('Unchanged original complete curve scope source required')
        style_options={} if source_scope_plan is None else {
            'source_region_stroke_styles':source_scope_plan['region_stroke_styles']}
        parents,extraction=drawing_geometry.extract_page(page,sha,number,_paths=cache['compact'],
            region_native_windows=windows,min_line_length_points=.25,
            max_candidates=limits['max_native_candidates'],max_total_points=limits['max_native_points'],
            max_paths=100000,max_scan_paths=100000,regional_fallback=False,
            curve_tolerance_points=TOLERANCE_POINTS,open_stroked_primitives_only=True,
            isolate_open_stroked_subpaths=True,**style_options)
        result.update(extraction=extraction,source_content_sha256=cache['source_content_sha256'],
                      original_parent_inventory_sha256=digest(parents))
        if (extraction['status']!='unplaced_geometry_candidates' or
                any(count and 'budget' in key.lower() for key,count in extraction.get('rejections',{}).items())):
            return fail('complete_open_stroke_extraction_required')
        if any(p.get('paint_reference_truncated') for p in parents):
            return fail('complete_open_stroke_paint_references_required')
        if source_scope_plan is not None:
            coverage=defaultdict(set)
            for parent in parents:
                for paint in parent['paint_references']:coverage[paint['ordinal']].add(paint['subpath'])
            result['complete_anchor_coverage']=[{'ordinal':anchor['ordinal'],
                'expected_original_open_subpaths':anchor['eligible_original_subpaths'],
                'retained_original_open_subpaths':sorted(coverage[anchor['ordinal']]),
                'eligible_subpaths_retained':set(anchor['eligible_original_subpaths'])<=coverage[anchor['ordinal']]}
                for anchor in source_scope_plan['anchors']]
        buckets=[[] for _ in windows]
        for parent in parents:
            check();paints=defaultdict(list)
            for paint in parent['paint_references']:
                for region in paint['source_region_indices']:paints[region].append(paint)
            for region,refs in paints.items():buckets[region].append({**parent,'paint_references':refs})
        inverse=native_inverse(page)
        stroke_ordinals=[];stroke_bounds=[];raw_parts={};extra_points=0
        for ordinal,path in enumerate(cache['paths']):
            check()
            if path['type'] not in ('s','fs'):continue
            bounds=pymupdf.Rect(path['rect'])*inverse
            if not all(math.isfinite(v) for v in bounds):raise ValueError('Finite original stroke bounds required')
            geometry=(Point(bounds.x0,bounds.y0) if bounds.x0==bounds.x1 and bounds.y0==bounds.y1 else
                LineString([(bounds.x0,bounds.y0),(bounds.x1,bounds.y1)]) if bounds.x0==bounds.x1 or bounds.y0==bounds.y1 else box(*bounds))
            stroke_ordinals.append(ordinal);stroke_bounds.append(geometry)
        stroke_index=STRtree(stroke_bounds)
        def witness(ordinal):
            nonlocal operators,controls
            if ordinal not in witness_cache:
                path=cache['paths'][ordinal];operators+=len(path['items'])
                if operators>limits['max_source_operators']:raise ValueError('open_curve_source_operator_budget_exceeded')
                ops=planning_curved_boundaries._operators(path,inverse)
                controls+=sum(len(op['points']) for op in ops)
                if controls>limits['max_source_control_points']:raise ValueError('open_curve_control_point_budget_exceeded')
                witness_cache[ordinal]={'ordinal':ordinal,'paint_sequence':path['seqno'],
                    'paint_type':path['type'],'explicit_close_path':bool(path.get('closePath')),
                    'stroke':path.get('color'),'stroke_opacity':path.get('stroke_opacity',1),
                    'stroke_style':{'width_pdf_points':path.get('width'),'dashes_pdf':str(path.get('dashes',''))},
                    'operators_pdf_native':ops}
            return witness_cache[ordinal]
        def omitted_stroke_conflict(geometry,links,error):
            included={(r['ordinal'],r['subpath']) for p in links for r in p['paint_references']}
            nodes={tuple(point) for p in links for point in (shape(p['geometry']).coords[0],shape(p['geometry']).coords[-1])}
            search=geometry.boundary.buffer(error+TOLERANCE_POINTS)
            for raw in stroke_index.query(search):
                charge();ordinal=stroke_ordinals[int(raw)];path=cache['paths'][ordinal]
                parts,approximations=original_parts(ordinal)
                for part_index,(points,approx) in enumerate(zip(parts,approximations)):
                    if (ordinal,part_index) in included:continue
                    g=LineString(points);intersection=g.intersection(geometry.boundary)
                    if not intersection.is_empty:
                        touches=([intersection] if intersection.geom_type=='Point' else
                                 list(intersection.geoms) if intersection.geom_type=='MultiPoint' else [])
                        ends={tuple(g.coords[0]),tuple(g.coords[-1])}
                        if not touches or any(tuple(p.coords[0]) not in nodes&ends for p in touches):return True
                    elif g.distance(geometry.boundary)<=error+approx['chord_error_bound_pdf_points']:return True
            return False
        def original_parts(ordinal):
            nonlocal extra_points
            if ordinal not in raw_parts:
                witness(ordinal)
                parts,approx=drawing_geometry.subpaths(cache['paths'][ordinal],inverse,{
                    'curve_tolerance_points':TOLERANCE_POINTS,'max_points':10000,'open_stroked_primitives_only':True})
                extra_points+=sum(len(p) for p in parts)
                if extraction['retained_points']+extra_points>limits['max_native_points']:
                    raise ValueError('open_curve_global_stroke_point_budget_exceeded')
                raw_parts[ordinal]=(parts,approx['subpath_approximations'])
            return raw_parts[ordinal]
        for index,scoped in enumerate(buckets):
            check();scoped_edges=_operator_edges(scoped,check,original_parts)
            rows,metrics,known_curve_nodes=_recover(scoped_edges,limits,check,charge);counts.update(metrics)
            endpoint_degrees=Counter(tuple(q) for edge in scoped_edges
                for q in (shape(edge['geometry']).coords[0],shape(edge['geometry']).coords[-1]))
            for edge in scoped_edges:
                if not edge['curve_approximation']['cubic_segments'] or edge['id'] in diagnostics:continue
                g=shape(edge['geometry']);reference=edge['source_operator_reference'];original=witness(reference['ordinal'])
                error=edge['curve_approximation']['chord_error_bound_pdf_points']
                envelope=g.buffer(error) if error else g
                overlaps=[] if cache['fill_index'] is None else cache['fill_index'].query(envelope,predicate='intersects')
                if any(cache['later_fills'][int(i)][0]>original['paint_sequence'] for i in overlaps):continue
                diagnostics[edge['id']]={'source_edge_id':edge['id'],'source_region_index':index,
                    'geometry_pdf_native':edge['geometry'],'source_operator_reference':reference,
                    'operator_pdf_native':original['operators_pdf_native'][reference['operator_index']],
                    'curve_approximation':edge['curve_approximation'],'length_pdf_points':g.length,
                    'original_endpoint_degrees_within_source_scope':[endpoint_degrees[tuple(q)] for q in (g.coords[0],g.coords[-1])],
                    'unresolved_endpoints_within_source_scope':[endpoint_degrees[tuple(q)]==1 and tuple(q) not in known_curve_nodes
                        for q in (g.coords[0],g.coords[-1])],
                    'status':'unclassified_open_source_curve_diagnostic','physical_identity_verified':False,
                    'world_placement_eligible':False}
            result['regions'].append({'index':index,'region_native_points':windows[index],
                'source_parent_ids':[p['id'] for p in scoped],'counts':metrics})
            for row in rows:
                check();geometry=shape(row['geometry']);error=row['chord_error_bound_pdf_points']
                links=[scoped_edges[i] for i in row['parent_indices']]
                # Screen each whole contributing edge against its own original
                # paint order. A later redraw of another edge cannot clear it.
                hidden=False
                for parent in links:
                    line=shape(parent['geometry']);e=parent['curve_approximation']['chord_error_bound_pdf_points']
                    envelope=line.buffer(e) if e else line
                    seq=max(cache['paths'][p['ordinal']].get('seqno',-1) for p in parent['paint_references'])
                    if seq<0:raise ValueError('Original open-stroke paint sequence required')
                    overlaps=[] if cache['fill_index'] is None else cache['fill_index'].query(envelope,predicate='intersects')
                    if any(cache['later_fills'][int(i)][0]>seq for i in overlaps):hidden=True;break
                if hidden:covered+=1;continue
                if omitted_stroke_conflict(geometry,links,error):
                    counts['omitted_original_stroke_conflict_faces_withheld']+=1;continue
                identifier=digest([VERSION,sha,number,geometry.normalize().wkb_hex])
                if identifier in seen:continue
                if len(seen)>=limits['max_faces']:raise ValueError('combined_open_curve_face_budget_exceeded')
                source_witnesses=[]
                for parent in links:
                    for reference in parent['paint_references']:
                        ordinal=reference['ordinal']
                        original=witness(ordinal)
                        if original not in source_witnesses:source_witnesses.append(original)
                context=[]
                for label in labels:
                    charge();g=shape(label['geometry_pdf_native'])
                    if geometry.contains(g):
                        context.append({'label':label,'label_boundary_clearance_pdf_points':g.distance(geometry.boundary),
                            'clear_of_curve_approximation':g.distance(geometry.boundary)>error,
                            'semantic_role_inferred':False})
                seen.add(identifier)
                candidate={'id':identifier,'document_sha256':sha,'page':number,
                    'coordinate_frame':'pdf_native_points_y_up','geometry':row['geometry'],
                    'extraction_kind':'planning_open_curve_network','extraction_version':VERSION,
                    'source_edge_ids':sorted(p['id'] for p in links),
                    'source_parent_ids':sorted({p['source_parent']['id'] for p in links}),
                    'source_edges':links,'source_paint_witnesses':source_witnesses,
                    'source_paint_witnesses_sha256':digest(source_witnesses),
                    'curve_approximation':{'method':'endpoint_exact_network_of_bounded_source_curves',
                        'cubic_segments':sum(p['curve_approximation']['cubic_segments'] for p in links),
                        'chord_error_bound_pdf_points':error,'requested_tolerance_pdf_points':TOLERANCE_POINTS},
                    'physical_identity_verified':False,'world_geometry_additions':0}
                result['records'].append({'candidate_id':identifier,'candidate':candidate,
                    'source_record_sha256':digest(candidate),'source_region_index':index,
                    'status':'unclassified_assembled_curve_boundary_review_only','label_context':context,
                    'curve_approximation':candidate['curve_approximation'],
                    'native_metrics':{'area_square_pdf_points':geometry.area,
                        'bounds_pdf_points':list(geometry.bounds),'hole_count':len(geometry.interiors)},
                    'physical_identity_verified':False,'world_placement_eligible':False,
                    'world_geometry_additions':0})
                if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
                    raise ValueError('open_curve_output_budget_exceeded')
        check()
        if hashlib.sha256(page.read_contents()).hexdigest()!=cache['source_content_sha256']:
            raise ValueError('Original open-stroke source changed')
        result.update(counts=dict(counts),pair_and_label_checks=checks,
            source_operator_count=operators,source_control_point_count=controls,
            global_stroke_check_points=extra_points,covered_boundaries_withheld=covered)
        result.update(curve_chain_diagnostics=sorted(diagnostics.values(),
            key=lambda r:(-r['length_pdf_points'],r['source_edge_id']))[:DIAGNOSTIC_LIMIT],
            diagnostic_candidates=len(diagnostics),diagnostics_sampled=len(diagnostics)>DIAGNOSTIC_LIMIT,
            diagnostic_selection='up to128 longest visible original curved operators; not a complete feature inventory')
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            raise ValueError('open_curve_output_budget_exceeded')
        return result
    except (ValueError,RuntimeError,OverflowError) as error:
        return fail(str(error)[:512])


def write_overlay(review,preview,path):
    if not review or not review['analysis_complete'] or not (review['records'] or review['curve_chain_diagnostics']):return None
    width,height=preview['size_pixels'];matrix=pymupdf.Matrix(preview['pdf_native_to_pixels'])
    background=base64.b64encode((path.parent/preview['file']).read_bytes()).decode('ascii')
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Original curved stroke networks; physical identity unverified">',
        f'<image href="data:image/png;base64,{background}" width="{width}" height="{height}"/>']
    for record in review['records']:
        commands=[]
        for ring in record['candidate']['geometry']['coordinates']:
            points=[pymupdf.Point(*q)*matrix for q in ring]
            commands.append('M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)+' Z')
        parts.append('<path class="assembled-source-boundary" fill="none" stroke="#087b36" stroke-width="2" '
            'vector-effect="non-scaling-stroke" d="'+' '.join(commands)+'"><title>'+escape(record['candidate_id'])+'</title></path>')
    for record in review['curve_chain_diagnostics']:
        points=[pymupdf.Point(*q)*matrix for q in record['geometry_pdf_native']['coordinates']]
        title=escape('Original curved operator '+json.dumps(record['source_operator_reference'])+
            '; source-scope endpoint degrees '+str(record['original_endpoint_degrees_within_source_scope']))
        parts.append('<path class="original-open-curve" fill="none" stroke="#c00090" stroke-width="1.5" '
            'vector-effect="non-scaling-stroke" d="M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)+
            '"><title>'+title+'</title></path>')
        for point,unresolved in zip((points[0],points[-1]),record['unresolved_endpoints_within_source_scope']):
            if unresolved:parts.append(f'<circle class="unmatched-source-endpoint" cx="{point.x:.4f}" cy="{point.y:.4f}" r="2.5" fill="#d00000"/>')
    parts.append('</svg>');raw=''.join(parts).encode()
    if len(raw)>16000000:raise ValueError('Open curve overlay byte budget exceeded')
    path.write_bytes(raw)
    return {'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'assembled_records':len(review['records']),
        'diagnostic_curves':len(review['curve_chain_diagnostics']),'diagnostics_sampled':review['diagnostics_sampled'],
        'physical_geometry_verified':False,'pdf_native_to_pixels':preview['pdf_native_to_pixels']}
