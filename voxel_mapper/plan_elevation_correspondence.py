"""Numbered marker/ray and opening-position hypotheses; never physical view certification."""
import hashlib
import json
import math
from pathlib import Path

import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString,Point,Polygon,shape,mapping

from . import footprint_hypotheses,building_facade_feed
from .building_spec import digest
from .drawing_geometry import native_inverse
from .generation_cycles import atomic_json

VERSION='source-plan-elevation-correspondence-v1'
DEFAULTS={'dimension_tolerance_m':.25,'marker_axis_tolerance_degrees':5.,
          'paint_boundary_neighborhood_pdf_points':.25,'max_checks':100000}


def _affine(matrix):return [matrix.a,matrix.c,matrix.b,matrix.d,matrix.e,matrix.f]


def marker_frames(polygon,marker,unit,layout=None,axis_tolerance=5):
    """Retain all ray-hit facing segments, not a nearest physical wall choice."""
    center=marker['center_pdf_native'];corner=marker['corner_center_pdf_native']
    direction=[corner[i]-center[i] for i in (0,1)];length=math.hypot(*direction)
    if length<=0:raise ValueError('Nondegenerate original marker corner required')
    direction=[v/length for v in direction]
    if polygon.covers(Point(center)):
        return {'status':'withheld_marker_inside_enclosure','frames':[]}
    bounds=polygon.bounds;distance=4*max(math.dist(center,(x,y)) for x in bounds[::2] for y in bounds[1::2])
    ray=LineString([center,[center[i]+direction[i]*distance for i in (0,1)]])
    intersection=polygon.exterior.intersection(ray)
    points=[intersection] if intersection.geom_type=='Point' else list(intersection.geoms) if intersection.geom_type=='MultiPoint' else []
    if not points:return {'status':'withheld_no_isolated_outer_boundary_ray_hit','frames':[]}
    transform=layout or [[1.,0.],[0.,1.]]
    def metric(point):return [(point[0]*transform[0][i]+point[1]*transform[1][i])*unit for i in (0,1)]
    camera_right=(direction[1],-direction[0]);frames=[]
    coords=list(polygon.exterior.coords)
    for index,(a,b) in enumerate(zip(coords,coords[1:])):
        line=LineString([a,b])
        hits=[p for p in points if line.distance(p)<=1e-7]
        if not hits or line.length==0:continue
        tangent=[(b[i]-a[i])/line.length for i in (0,1)]
        outward=(tangent[1],-tangent[0]) if polygon.exterior.is_ccw else (-tangent[1],tangent[0])
        if -sum(outward[i]*direction[i] for i in (0,1))<math.cos(math.radians(axis_tolerance)):continue
        am,bm=metric(a),metric(b);v=[bm[i]-am[i] for i in (0,1)];size=math.hypot(*v)
        axis=[x/size for x in v]
        native_axis=tangent
        if sum(native_axis[i]*camera_right[i] for i in (0,1))<0:axis=[-x for x in axis]
        values=[sum(metric(p)[i]*axis[i] for i in (0,1)) for p in polygon.exterior.coords]
        frame={'boundary_segment_index':index,'source_native_endpoints':[list(a),list(b)],
            'ray_hits_pdf_native':[[p.x,p.y] for p in sorted(hits,key=lambda p:ray.project(p))],
            'marker_direction_pdf_native':direction,'diagnostic_axis':axis,
            'diagnostic_plane_origin':am,'projection_min_m':min(values),'projection_max_m':max(values),
            'projected_extent_width_m':max(values)-min(values),
            'projection_uses_provisional_layout':layout is not None,
            'marker_semantics_verified':False,'physical_wall_identity_verified':False}
        frame['id']=digest(frame);frames.append(frame)
    return {'status':'source_marker_ray_frame_candidates' if frames else 'withheld_no_facing_segment',
        'frames':frames,'orientation_basis':'inferred from printed marker corner; all eligible ray hits retained'}


def compare(candidate,markers,regions,opening_views,gaps,plan_inverse,unit,layout,options=None,*,paint_fills=None):
    opts={**DEFAULTS,**(options or {})}
    if set(opts)!=set(DEFAULTS):raise ValueError('Unknown correspondence option')
    for key in ('dimension_tolerance_m','marker_axis_tolerance_degrees','paint_boundary_neighborhood_pdf_points'):
        if type(opts[key]) not in (int,float) or not math.isfinite(opts[key]) or not 0<opts[key]<=DEFAULTS[key]:
            raise ValueError('Bounded correspondence tolerance required')
    if type(opts['max_checks']) is not int or not 1<=opts['max_checks']<=DEFAULTS['max_checks']:
        raise ValueError('Bounded correspondence work required')
    if len(markers)>32 or len(regions)>128 or len(opening_views)>32 or len(gaps)>4000 or len(paint_fills or [])>4000:
        raise ValueError('Bounded source correspondence inventories required')
    if not math.isfinite(unit) or unit<=0:raise ValueError('Positive nominal plan scale required')
    polygon=shape(candidate['geometry_pdf_native']);checks=0;views=[]
    transform=layout or [[1.,0.],[0.,1.]]
    def metric(point):return [(point[0]*transform[0][i]+point[1]*transform[1][i])*unit for i in (0,1)]
    def charge():
        nonlocal checks
        checks+=1
        if checks>opts['max_checks']:raise OverflowError
    try:
        paints=[]
        for fill in paint_fills or []:
            charge()
            if list(fill['fill_color'])==[1,1,1]:continue
            native=affine_transform(shape(fill['geometry']),_affine(plan_inverse))
            paints.append((fill,native))
        for marker in markers:
            charge();key=marker['target_view_key_candidate']
            frame_review=marker_frames(polygon,marker,unit,layout,opts['marker_axis_tolerance_degrees'])
            matches=[];projected_gaps=[];opening_matches=[];paint_witnesses=[];paint_matches=[]
            view_regions=[r for r in regions if r['view_key_candidate']==key]
            scans=[v for v in opening_views if v['view_key_candidate']==key]
            if len(scans)!=1:scan_status='withheld_nonunique_or_missing_opening_view';openings=[]
            else:scan_status=scans[0]['scan']['status'];openings=scans[0]['scan']['candidates']
            for frame in frame_review['frames']:
                a,b=frame['source_native_endpoints'];length=math.dist(a,b)
                tangent=[(b[i]-a[i])/length for i in (0,1)]
                outward=(tangent[1],-tangent[0]) if polygon.exterior.is_ccw else (-tangent[1],tangent[0])
                for fill,native in paints:
                    charge()
                    hits=[p for p in frame['ray_hits_pdf_native']
                        if native.boundary.distance(Point(p))<=opts['paint_boundary_neighborhood_pdf_points']]
                    if not hits:continue
                    sides=[]
                    for hit in hits:
                        inside=native.covers(Point([hit[i]-.1*outward[i] for i in (0,1)]))
                        outside=native.covers(Point([hit[i]+.1*outward[i] for i in (0,1)]))
                        sides.append({'source_ray_hit_pdf_native':hit,'paint_on_enclosure_interior_side':inside,
                            'source_boundary_distance_pdf_points':native.boundary.distance(Point(hit)),
                            'exact_boundary_coincidence':native.boundary.distance(Point(hit))<=1e-7,
                            'paint_on_enclosure_exterior_side':outside,
                            'attribution':'inner_edge_of_source_paint' if outside and not inside else
                                'outer_edge_of_source_paint' if inside and not outside else 'ambiguous_source_paint_side'})
                    axis=frame['diagnostic_axis'];projected=[]
                    for part in native.geoms if native.geom_type=='MultiPolygon' else [native]:
                        projected.extend(sum(metric(p)[i]*axis[i] for i in (0,1)) for p in part.exterior.coords)
                    span=max(projected)-min(projected)
                    witness={'frame_id':frame['id'],'source_fill_id':fill['id'],'paint_seqno':fill.get('paint_seqno'),
                        'ray_hit_sidedness':sides,'side_probe_distance_pdf_points':.1,
                        'paint_boundary_neighborhood_pdf_points':opts['paint_boundary_neighborhood_pdf_points'],
                        'paint_neighbor_is_discovery_hypothesis':True,
                        'source_paint_projected_extent_m':span,'source_fill_geometry_pdf_native':mapping(native),
                        'clip_source_path_ordinals':[c['path_ordinal'] for c in fill.get('clip_references',[])],
                        'physical_wall_role_verified':False,'complete_wall_extent_verified':False,
                        'source_geometry_changed':False}
                    paint_witnesses.append(witness)
                    for region in view_regions:
                        charge();bounds=shape(region['display_geometry']).bounds;factor=region['nominal_metres_per_pdf_point_candidate']
                        width=(bounds[2]-bounds[0])*factor
                        paint_matches.append({'frame_id':frame['id'],'source_fill_id':fill['id'],'region_id':region['id'],
                            'material_number':region['material_number'],'source_paint_minus_region_width_m':span-width,
                            'within_discovery_tolerance':abs(span-width)<=opts['dimension_tolerance_m'],
                            'physical_correspondence_verified':False})
                for region in view_regions:
                    charge();bounds=shape(region['display_geometry']).bounds;factor=region['nominal_metres_per_pdf_point_candidate']
                    width=(bounds[2]-bounds[0])*factor;residual=frame['projected_extent_width_m']-width
                    matches.append({'frame_id':frame['id'],'region_id':region['id'],
                        'component_class_candidate':region['component_class_candidate'],'material_number':region['material_number'],
                        'region_width_m':width,'plan_projected_width_m':frame['projected_extent_width_m'],
                        'plan_minus_region_width_m':residual,'within_discovery_tolerance':abs(residual)<=opts['dimension_tolerance_m'],
                        'complete_facade_identity_verified':False})
                for gap in gaps:
                    charge()
                    if gap['id'] not in candidate['boundary_gap_ids']:continue
                    raw=[list(pymupdf.Point(p)*plan_inverse) for p in gap['projected_gap_endpoints']]
                    a,b=[metric(p) for p in raw];delta=[b[i]-a[i] for i in (0,1)];length=math.hypot(*delta)
                    axis=frame['diagnostic_axis'];normal=(-axis[1],axis[0])
                    if not length or abs(sum(delta[i]/length*axis[i] for i in (0,1)))<math.cos(math.radians(opts['marker_axis_tolerance_degrees'])):continue
                    origin=frame['diagnostic_plane_origin'];plane_residual=max(abs(sum((p[i]-origin[i])*normal[i] for i in (0,1))) for p in (a,b))
                    if plane_residual>opts['dimension_tolerance_m']:continue
                    span=sorted(sum(p[i]*axis[i] for i in (0,1))-frame['projection_min_m'] for p in (a,b))
                    projection={'frame_id':frame['id'],'source_gap_id':gap['id'],
                        'position_interval_m':span,'width_m':span[1]-span[0],
                        'plane_residual_m':plane_residual,'physical_opening_verified':False}
                    projected_gaps.append(projection)
                    for region in view_regions:
                        bounds=shape(region['display_geometry']).bounds;factor=region['nominal_metres_per_pdf_point_candidate']
                        region_width=(bounds[2]-bounds[0])*factor
                        for opening in openings:
                            charge();native=shape(opening['geometry'])
                            # Original elevation pages in this feed retain their
                            # source display transforms, never the plan layout fit.
                            m=pymupdf.Matrix(region['unrotated_mupdf_to_pdf_native_matrix'])
                            rotation=pymupdf.Matrix(region['unrotated_mupdf_to_display_matrix'])
                            display=affine_transform(native,_affine((~m)*rotation));ob=display.bounds
                            elevation_span=[(ob[0]-bounds[0])*factor,(ob[2]-bounds[0])*factor]
                            if elevation_span[0]<-opts['dimension_tolerance_m'] or elevation_span[1]>region_width+opts['dimension_tolerance_m']:continue
                            for reverse in (False,True):
                                observed=[region_width-elevation_span[1],region_width-elevation_span[0]] if reverse else elevation_span
                                width_residual=(observed[1]-observed[0])-projection['width_m']
                                position_residual=max(abs(observed[i]-span[i]) for i in (0,1))
                                if abs(width_residual)<=opts['dimension_tolerance_m'] and position_residual<=opts['dimension_tolerance_m']:
                                    opening_matches.append({'frame_id':frame['id'],'source_gap_id':gap['id'],
                                        'region_id':region['id'],'raster_opening_candidate_id':opening['id'],
                                        'region_component_class_candidate':region['component_class_candidate'],
                                        'facade_width_within_discovery_tolerance':abs(frame['projected_extent_width_m']-region_width)<=opts['dimension_tolerance_m'],
                                        'elevation_x_reversed':reverse,'width_residual_m':width_residual,
                                        'maximum_position_residual_m':position_residual,
                                        'physical_correspondence_verified':False})
            views.append({'view_key_candidate':key,'marker_source':marker,'frame_review':frame_review,
                'region_width_comparisons':matches,'boundary_gap_projections':projected_gaps,
                'opening_scan_status':scan_status,'opening_position_matches':opening_matches,
                'source_paint_boundary_witnesses':paint_witnesses,'source_paint_width_comparisons':paint_matches,
                'view_scope_and_state_verified':False,'region_matches_are_partial_not_complete_facades':True})
        voids=[{'ring_index':i,'geometry':mapping(Polygon(ring)),
            'role':'unclassified_drafting_void','physical_void_identity_verified':False}
            for i,ring in enumerate(polygon.interiors)]
        return {'candidate_id':candidate['id'],'status':'source_view_correspondence_hypotheses_only',
            'views':views,'voids':voids,'checks':checks,'layout_application_verified':False,
            'selected_physical_footprint':False,'complete_building_specs_generated':0,'world_geometry_additions':0}
    except OverflowError:
        return {'candidate_id':candidate['id'],'status':'correspondence_budget_withheld','views':[],
            'voids':[],'checks':checks,'selected_physical_footprint':False,'world_geometry_additions':0}


def prepare(config,resolve,output):
    if not isinstance(config,dict) or config.get('version')!=VERSION or set(config)-{'version','footprint','facades','options'}:
        raise ValueError('Versioned original-source correspondence request required')
    destination=Path(output);root=destination.with_name(destination.name+'.partial')
    if root.exists() or destination.exists():raise ValueError('Fresh correspondence output required')
    root.mkdir(parents=True)
    footprint=footprint_hypotheses.prepare(config['footprint'],resolve,root/'footprint')
    facade=building_facade_feed.prepare(config['facades'],resolve,root/'facades')
    request=config['footprint']['plan_audit'];identifier=request['building_id'];plan=request['plan']
    buildings=config['facades']['buildings']
    if len(buildings)!=1 or buildings[0]['building_id']!=identifier:raise ValueError('One same-declared-building source scope required')
    if facade['buildings'][0]['status']!='awaiting_facade_interpretation':raise ValueError('Complete original facade extraction required')
    directory=root/'facades/building-0000';hypotheses=json.loads((root/'footprint/hypotheses.json').read_text())
    source_report=json.loads((root/'footprint/source-audit/report.json').read_text())
    region_feed=json.loads((directory/'regions.json').read_text())['regions']
    opening_feed=json.loads((directory/'opening-candidates.json').read_text())['views']
    view_pages=[json.loads(line) for line in (directory/'faces/drawing-view-pages.jsonl').read_text().splitlines()]
    page_rows=[p for p in view_pages if p['document_sha256']==plan['sha256'] and p['page']==plan['page']]
    if len(page_rows)!=1:raise ValueError('Same original plan reference page required')
    source_markers=page_rows[0]['plan_references']['references'];markers=[]
    with pymupdf.open(Path(resolve(plan['path']))) as doc:
        matrix=native_inverse(doc[plan['page']-1])
    for marker in source_markers:
        if marker['status']!='unverified_native_view_reference_candidate' or not marker.get('target_view_key_candidate'):continue
        center=pymupdf.Rect(marker['circle_bbox_page_points']);corner=pymupdf.Rect(marker['corner_fill_bbox_page_points'])
        a=(center.tl+center.br)*.5*matrix;b=(corner.tl+corner.br)*.5*matrix
        markers.append({'target_view_key_candidate':marker['target_view_key_candidate'],
            'center_pdf_native':list(a),'corner_center_pdf_native':list(b),
            'document_sha256':plan['sha256'],'page':plan['page'],'source_reference_sha256':digest(marker),
            'circle_path_index':marker['circle_path_index'],'corner_fill_path_index':marker['corner_fill_path_index'],
            'marker_semantics_verified':False})
    gaps=json.loads((root/'footprint/source-audit/source-fill-endcaps.json').read_text())['gaps']
    fills=json.loads((root/'footprint/source-audit/source-fills.json').read_text())['candidates']
    unit=source_report['plan_scale_review']['nominal_metres_per_pdf_point_candidate']
    reference_unit=source_report['reference_scale_review']['nominal_metres_per_pdf_point_candidate']
    layout=source_report['sheet_layout_audit']
    inverse=layout['subject_to_reference_linear_row_matrix'] if layout['status']=='supported_furniture_layout_correspondence_only' and reference_unit==unit else None
    if unit is None:raise ValueError('Nominal source plan scale required for correspondence discovery')
    focus=set(footprint['diagnostic_extent_compatible_candidate_ids']);results=[]
    for candidate in hypotheses['candidates']:
        if candidate['id'] in focus:
            results.append(compare(candidate,markers,region_feed,opening_feed,gaps,matrix,unit,inverse,config.get('options'),paint_fills=fills))
    atomic_json(root/'correspondences.json',{'version':VERSION,'records':results})
    originals=[request['plan'],request['reference_sheet'],*buildings[0]['sources']]
    for source in originals:
        if hashlib.sha256(Path(resolve(source['path'])).read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Original source changed before correspondence publication')
    report={'version':VERSION,'config_sha256':digest(config),'building_id':identifier,
        'source_sha256':sorted({s['sha256'] for s in originals}),'focus_candidate_ids':sorted(focus),
        'source_marker_candidates':len(markers),'candidate_reports':len(results),
        'view_frame_candidates':sum(len(v['frame_review']['frames']) for r in results for v in r['views']),
        'region_width_matches':sum(m['within_discovery_tolerance'] for r in results for v in r['views'] for m in v['region_width_comparisons']),
        'source_paint_width_matches':sum(m['within_discovery_tolerance'] for r in results for v in r['views'] for m in v['source_paint_width_comparisons']),
        'opening_position_matches':sum(len(v['opening_position_matches']) for r in results for v in r['views']),
        'selected_physical_footprint_id':None,'complete_building_specs_generated':0,
        'training_labels_generated':0,'park_world_blocks_added':0}
    atomic_json(root/'report.json',report);atomic_json(root/'review-queue.json',{'version':VERSION,
        'source_sha256':report['source_sha256'],'correspondence_sha256':digest(results),'outcome':None,
        'requirements':['physical_wall_opening_void_roles','complete_facade_scope','viewport_scale_state_revision','independent_cross_view_identity'],
        'training_labels_generated':0})
    if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>128000000:
        raise ValueError('Correspondence output byte budget exceeded')
    root.replace(destination);return report
