"""Exact mixed-source enclosures and explicit, bounded endcap-corridor alternatives."""
import json
import math
from pathlib import Path

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point, box, shape, mapping
from shapely.ops import unary_union, polygonize_full
from shapely.strtree import STRtree

from .building_spec import digest, build, FRAME
from .building_cross_view import _surface
from .building_plan_audit import prepare as audit_plan
from .generation_cycles import atomic_json
from .study_mesh_export import write_glb

VERSION='source-footprint-hypotheses-v1'
DEFAULTS={'max_gaps':6,'max_trials':64,'max_segments':10000,'max_checks':500000,
          'max_faces':4000,'max_provenance_links':2048,'max_candidates':128}


def preview_surface(polygon,unit):
    """Keep the source polygon; audit sub-tolerance mesh slivers explicitly."""
    xmin,ymin,_,_=polygon.bounds
    geometry=_surface(polygon,lambda x,y:[(x-xmin)*unit,(y-ymin)*unit,0])
    mesh=geometry['mesh'];retained=[];omitted=[];area=0
    for index,triangle in enumerate(mesh['triangles']):
        a,b,c=[mesh['vertices'][i] for i in triangle]
        cross=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        if cross*cross<=1e-20:
            omitted.append(index);area+=abs(cross)/2
        else:retained.append(triangle)
    if area>1e-8 or not retained:raise ValueError('Preview triangulation loss exceeds the numerical area budget')
    mesh['triangles']=retained
    return geometry,{'omitted_triangle_indices':omitted,'omitted_area_m2':area,
        'maximum_omitted_area_m2':1e-8,'minimum_mesh_triangle_cross_squared':1e-20,
        'source_polygon_modified':False,'preview_mesh_is_exact_source_polygon':not bool(omitted)}


def propose(edges,fills,gaps,seed,scope,*,options=None):
    opts={**DEFAULTS,**(options or {})}
    if set(opts)!=set(DEFAULTS) or any(type(v) is not int or not 1<=v<=DEFAULTS[k] for k,v in opts.items()):
        raise ValueError('Bounded footprint hypothesis options required')
    if len(edges)>20000 or len(fills)>4000 or len(gaps)>4000:raise ValueError('Bounded original page inventory required')
    zone=box(*scope);point=Point(seed)
    if not zone.contains(point):raise ValueError('Interior original label seed required')
    keys={(r['document_sha256'],r['page']) for r in [*edges,*fills]}
    if len(keys)!=1:raise ValueError('One original source page required')
    if any(r['coordinate_frame']!='unrotated_mupdf_points_y_down' for r in [*edges,*fills]):
        raise ValueError('Original MuPDF source coordinate frame required')
    sha,page=next(iter(keys));checks=0;segments=[];proofs=[];counts={'crossing_scope_sources':0,'white_fills_deferred':0}
    def charge(n=1):
        nonlocal checks
        checks+=n
        if checks>opts['max_checks']:raise OverflowError('work_budget')
    def append(a,b,proof):
        if a==b:return
        charge();segments.append(LineString([a,b]));proofs.append(proof)
        if len(segments)>opts['max_segments']:raise OverflowError('source_segment_budget')
    base={'version':VERSION,'document_sha256':sha,'page':page,'options':opts,
        'coordinate_frame':'unrotated_mupdf_points_y_down','label_seed':list(seed),'declared_scope':list(scope),
        'source_geometry_changed':False,'physical_footprint_verified':False,'world_geometry_additions':0}
    try:
        for edge in sorted(edges,key=lambda r:r['id']):
            charge();g=LineString(edge['points'])
            if not zone.covers(g):counts['crossing_scope_sources']+=1;continue
            append(*edge['points'],{'kind':'original_stroke','source_edge_id':edge['id'],
                'source_endpoints':edge['points']})
        for fill in sorted(fills,key=lambda r:r['id']):
            charge();g=shape(fill['geometry'])
            if list(fill['fill_color'])==[1,1,1]:counts['white_fills_deferred']+=1;continue
            if not g.is_valid or g.is_empty or g.geom_type not in ('Polygon','MultiPolygon'):
                raise ValueError('Valid source fill polygons required')
            if not zone.covers(g):counts['crossing_scope_sources']+=1;continue
            for part_index,part in enumerate(g.geoms if g.geom_type=='MultiPolygon' else [g]):
                for ring_index,ring in enumerate([part.exterior,*part.interiors]):
                    for segment_index,(a,b) in enumerate(zip(ring.coords,list(ring.coords)[1:])):
                        append(a,b,{'kind':'original_fill_boundary','source_fill_id':fill['id'],
                            'part_index':part_index,'ring_index':ring_index,'segment_index':segment_index,
                            'source_endpoints':[list(a),list(b)],'paint_seqno':fill.get('paint_seqno'),
                            'clip_source_path_ordinals':[c['path_ordinal'] for c in fill.get('clip_references',[])]})
        local=[];fill_map={r['id']:r for r in fills}
        for gap in sorted(gaps,key=lambda r:r['id']):
            charge();g=shape(gap['gap_corridor_geometry'])
            if not zone.covers(g):continue
            if (len(gap['source_endcaps'])!=2 or any(c['fill_candidate_id'] not in fill_map for c in gap['source_endcaps'])):
                raise ValueError('Retained original endcap parents required')
            if not g.is_valid or g.geom_type!='Polygon' or len(g.exterior.coords)!=5:
                raise ValueError('Exact four-corner source endcap corridor required')
            source_corners=[]
            for cap in gap['source_endcaps']:
                line=LineString(cap['source_endpoints']);parent=shape(fill_map[cap['fill_candidate_id']]['geometry'])
                if not parent.boundary.buffer(1e-7).covers(line):raise ValueError('Endcap differs from original filled boundary')
                source_corners.extend(tuple(p) for p in cap['source_endpoints'])
            if sorted(source_corners)!=sorted(tuple(p) for p in list(g.exterior.coords)[:-1]):
                raise ValueError('Corridor vertices differ from original source cap endpoints')
            local.append(gap)
        if len(local)>opts['max_gaps'] or 2**len(local)>opts['max_trials']:
            raise OverflowError('gap_combination_budget')
        if not segments:return {**base,'status':'no_complete_source_segments','candidates':[],'gap_effects':[],'checks':checks}
        source_tree=STRtree(segments)
        for i,line in enumerate(segments):
            charge(sum(int(j)>i for j in source_tree.query(line,predicate='intersects')))
        original_network=unary_union(segments);original_support=original_network.buffer(1e-7)
        candidates={};trial_keys={};trials=[]
        for mask in range(2**len(local)):
            charge();trial_segments=list(segments);trial_proofs=list(proofs);active=[]
            for i,gap in enumerate(local):
                if not mask>>i&1:continue
                active.append(gap['id']);coords=list(shape(gap['gap_corridor_geometry']).exterior.coords)
                for index,(a,b) in enumerate(zip(coords,coords[1:])):
                    line=LineString([a,b]);charge(len(source_tree.query(line,predicate='intersects')))
                    trial_segments.append(line);trial_proofs.append({'kind':'inferred_corridor_edge','source_gap_id':gap['id'],
                        'corridor_edge_index':index,'source_endpoints':[list(a),list(b)]})
            network=unary_union([original_network,*trial_segments[len(segments):]])
            parts=list(network.geoms) if hasattr(network,'geoms') else [network]
            if sum(len(p.coords) for p in parts)>100000:raise OverflowError('noded_point_budget')
            faces,cuts,dangles,invalid=polygonize_full(network)
            if len(faces.geoms)>opts['max_faces']:raise OverflowError('face_budget')
            index=STRtree(trial_segments);hits=[]
            for face in faces.geoms:
                charge()
                if not face.contains(point) or not zone.covers(face):continue
                if sum(len(r.coords) for r in [face.exterior,*face.interiors])>4096:raise OverflowError('boundary_vertex_budget')
                key=face.normalize().wkb_hex
                if key not in candidates:
                    links=[];coverage=[];required_gaps=set()
                    for j in index.query(face.boundary.buffer(1e-7)):
                        charge();j=int(j);line=trial_segments[j]
                        overlap=face.boundary.intersection(line.buffer(1e-7,cap_style=2))
                        if overlap.length<=1e-6:continue
                        pieces=list(overlap.geoms) if hasattr(overlap,'geoms') else [overlap]
                        for piece in pieces:
                            if piece.geom_type!='LineString' or piece.length<=1e-6:continue
                            links.append({**trial_proofs[j],'interval_fractions':sorted([
                                line.project(Point(piece.coords[0]),normalized=True),
                                line.project(Point(piece.coords[-1]),normalized=True)]),
                                'boundary_length_pdf_points':piece.length})
                            coverage.append(piece)
                            if j>=len(segments) and not original_support.covers(piece):
                                required_gaps.add(trial_proofs[j]['source_gap_id'])
                            if len(links)>opts['max_provenance_links']:raise OverflowError('boundary_provenance_budget')
                    if not coverage or not unary_union(coverage).buffer(1e-7).covers(face.boundary):
                        raise OverflowError('complete_boundary_provenance_required')
                    candidate={'id':digest([VERSION,sha,page,key]),'geometry':mapping(face),
                        'area_pdf_points_squared':face.area,'interior_ring_candidates':len(face.interiors),
                        'boundary_provenance':sorted(links,key=digest),'boundary_gap_ids':sorted(required_gaps),
                        'status':'gap_qualified_enclosure_hypothesis' if required_gaps else 'source_only_mixed_enclosure_candidate',
                        'trial_gap_sets':[],'physical_footprint_verified':False,'physical_opening_count':None,
                        'source_geometry_changed':False}
                    candidates[key]=candidate
                    if len(candidates)>opts['max_candidates']:raise OverflowError('candidate_budget')
                candidates[key]['trial_gap_sets'].append(active);hits.append(key)
            trial_keys[mask]=hits;trials.append({'active_gap_ids':active,'named_faces':len(hits),
                'cuts':len(cuts.geoms),'dangles':len(dangles.geoms),'invalid_rings':len(invalid.geoms)})
        baseline=trial_keys[0];effects=[]
        for i,gap in enumerate(local):
            solo=trial_keys[1<<i]
            effect='creates_named_enclosure' if not baseline and solo else 'changes_existing_named_enclosure' if baseline and set(solo)!=set(baseline) else 'no_named_enclosure_change'
            effects.append({'source_gap_id':gap['id'],'parent_fill_candidate_ids':gap['parent_fill_candidate_ids'],
                'single_gap_effect':effect,'physical_role':'unclassified','physical_opening_verified':False,
                'baseline_candidate_ids':[candidates[k]['id'] for k in baseline],
                'single_gap_candidate_ids':[candidates[k]['id'] for k in solo]})
        return json.loads(json.dumps({**base,'status':'mixed_source_enclosure_hypotheses_only',
            'source_segment_count':len(segments),'checks':checks,'counts':counts,'trials':trials,
            'candidates':sorted(candidates.values(),key=lambda r:r['id']),'gap_effects':effects,
            'baseline_candidate_ids':[candidates[k]['id'] for k in baseline],
            'provenance_epsilon_pdf_points':1e-7,'selected_physical_footprint_id':None,
            'limitations':['Mixed paint/stroke topology is drafting evidence, not exterior-wall or opening identity.',
                'Every active corridor is an explicit alternative; source endpoints are never moved or snapped.',
                'Interior rings remain protected drafting voids, not automatically classified shafts or openings.',
                'The epsilon compensates provenance overlay only and never enters network construction.']}))
    except OverflowError as error:
        return {**base,'status':'hypothesis_budget_withheld','reason':str(error),'checks':checks,
            'candidates':[],'gap_effects':[],'baseline_candidate_ids':[]}


def prepare(config,resolve,output):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{'version','plan_audit','options'}:
        raise ValueError('Versioned original-source footprint hypothesis request required')
    destination=Path(output);root=destination.with_name(destination.name+'.partial')
    if destination.exists() or root.exists():raise ValueError('Fresh footprint hypothesis output required')
    root.mkdir(parents=True)
    report=audit_plan(config['plan_audit'],resolve,root/'source-audit')
    request=config['plan_audit'];source=request['plan'];path=Path(resolve(source['path']))
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('Original footprint PDF changed')
    labels=[r for r in report['named_enclosure_audit']['label_occurrences'] if r['glyph_screen']['status']=='raster_consistent_candidate']
    if len(labels)!=1:raise ValueError('One visible original component label required; competing labels remain unresolved')
    with pymupdf.open(path) as doc:
        from .drawing_geometry import native_inverse
        inverse=native_inverse(doc[source['page']-1]);to_page=~inverse
        scope=box(*request['component_bounds_pdf_native'])
        scope_page=affine_transform(scope,[to_page.a,to_page.c,to_page.b,to_page.d,to_page.e,to_page.f])
        seed=pymupdf.Point(labels[0]['center_pdf_native'])*to_page
    network=json.loads((root/'source-audit/source-network.json').read_text())
    fills=json.loads((root/'source-audit/source-fills.json').read_text())
    gaps=json.loads((root/'source-audit/source-fill-endcaps.json').read_text())
    hypotheses=propose(network['source_edges'],fills['candidates'],gaps['gaps'],list(seed),list(scope_page.bounds),options=config.get('options'))
    unit=report['plan_scale_review']['nominal_metres_per_pdf_point_candidate'];previews=[]
    for candidate in hypotheses['candidates']:
        polygon=affine_transform(shape(candidate['geometry']),[inverse.a,inverse.c,inverse.b,inverse.d,inverse.e,inverse.f])
        candidate['geometry_pdf_native']=mapping(polygon)
        candidate['nominal_area_m2']=polygon.area*unit**2 if unit else None
        if unit:
            def extents(g):
                points=list(g.minimum_rotated_rectangle.exterior.coords)
                lengths=[math.dist(a,b)*unit for a,b in zip(points,points[1:])]
                return [max(lengths),min(lengths)]
            raw=extents(polygon);layout=report['sheet_layout_audit'];corrected=None
            reference_unit=report['reference_scale_review']['nominal_metres_per_pdf_point_candidate']
            if (layout['status']=='supported_furniture_layout_correspondence_only'
                    and reference_unit is not None and abs(reference_unit-unit)<1e-12):
                matrix=layout['subject_to_reference_linear_row_matrix']
                corrected=extents(affine_transform(polygon,[matrix[0][0],matrix[1][0],matrix[0][1],matrix[1][1],0,0]))
            targets=request.get('elevation_width_candidates_m',[])
            candidate['dimension_review']={'raw_nominal_extent_dimensions_m':raw,
                'inverse_layout_extent_candidates_m':corrected,
                'declared_target_matches_per_axis':[[w for w in targets if abs(length-w)<=.25]
                    for length in corrected] if corrected is not None else [],
                'extent_recipe':'minimum_rotated_rectangle_for_diagnostics_only_not_outline_replacement',
                'layout_application_verified':False,'physical_correspondence_verified':False,
                'source_geometry_changed':False}
        # Only no-corridor baseline candidates receive standalone source-topology
        # previews. This is not a selection for assembly or a correctness label.
        if candidate['id'] not in hypotheses['baseline_candidate_ids'] or not unit:continue
        geometry,numerical=preview_surface(polygon,unit)
        spec={'version':'building-spec-v1','coordinate_frame':FRAME,
            'building_id':request['building_id']+':source-enclosure:'+candidate['id'][:12],
            'sources':[{'id':'original_plan','sha256':source['sha256'],'state':'unknown'}],
            'preview_scope':'source_drafting_enclosure_not_accepted_footprint',
            'preview_mesh_numerical_review':numerical,
            'components':[{'id':'source_enclosure','role':'detail',
                'geometry':geometry,
                'evidence':{'class':'inferred','source_ids':['original_plan'],
                    'description':'Mixed original stroked/fill-boundary drafting enclosure; physical extent and voids unverified.',
                    'candidate_id':candidate['id']}}],
            'assumptions':['Original interior rings and source orientation are retained; no gap corridor or layout-scale correction is applied.',
                'Nominal printed scale, unknown view state and arbitrary local zero remain unverified.',
                'A closed drafting face is not an accepted exterior footprint, floor plate or complete building.']}
        directory=root/f'baseline-preview-{len(previews):04d}';directory.mkdir()
        model=build(spec);model['preview_scope']=spec['preview_scope']
        atomic_json(directory/'spec.json',spec);atomic_json(directory/'model.json',model)
        write_glb(model,directory/'model.glb');previews.append({'candidate_id':candidate['id'],'spec_sha256':digest(spec)})
    for original in (request['plan'],request['reference_sheet']):
        if hashlib.sha256(Path(resolve(original['path'])).read_bytes()).hexdigest()!=original['sha256']:
            raise ValueError('Original footprint PDF changed before publication')
    atomic_json(root/'hypotheses.json',hypotheses)
    compatible=[c['id'] for c in hypotheses['candidates']
        if c.get('dimension_review',{}).get('declared_target_matches_per_axis')
        and all(c['dimension_review']['declared_target_matches_per_axis'])]
    result={'version':VERSION,'config_sha256':digest(config),'source_sha256':source['sha256'],
        'status':hypotheses['status'],'candidate_count':len(hypotheses['candidates']),
        'diagnostic_extent_compatible_candidate_ids':compatible,
        'baseline_candidate_ids':hypotheses['baseline_candidate_ids'],'baseline_previews':previews,
        'gap_effects':hypotheses['gap_effects'],'selected_physical_footprint_id':None,
        'complete_building_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0}
    atomic_json(root/'report.json',result);atomic_json(root/'review-queue.json',{'version':VERSION,
        'source_sha256':source['sha256'],'candidate_ids':[r['id'] for r in hypotheses['candidates']],
        'hypotheses_sha256':digest(hypotheses),'outcome':None,
        'requirements':['exterior_wall_and_void_identity','gap_role_review','view_state_scale_revision','cross_view_correspondence'],
        'training_labels_generated':0})
    if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>128000000:
        raise ValueError('Footprint evidence output byte budget exceeded')
    root.replace(destination)
    return result
