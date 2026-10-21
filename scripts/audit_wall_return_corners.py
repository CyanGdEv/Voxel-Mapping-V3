"""Independent source-vertex, paint-side and correspondence audit helper."""
import math

import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Point, shape

from voxel_mapper import automatic_wall_returns
from voxel_mapper.automatic_opening_links import affine
from voxel_mapper.reconstruction_evidence_queue import digest


def verify(source_pages, inventories, buildings, levels, alignment, scale, returns, checked, max_checks):
    assert digest(automatic_wall_returns.run(source_pages,inventories,buildings,levels,alignment,scale,max_checks=max_checks))==digest(returns)
    if returns['status']!='original_paint_return_corner_hypotheses_only':return
    by_view={v['view_id']:v for v in inventories};views={v['id']:v for p in source_pages for v in p['views']}
    records={r['id']:r for r in buildings['frames']};raw_reviews={digest(r):r for row in alignment['frames'] for r in row['frame_reviews']}
    families={f['id']:f for v in levels['views'] for f in v['families']};level_views={v['view_id']:v for v in levels['views']}
    pairs={p['id']:p for p in scale['pairs']};corners={};frames={};cosine=math.cos(math.radians(5))
    for result in returns['frames']:
        record=records[result['facade_record_id']];frame=next(f for f in record['frame_review']['frames'] if f['id']==result['frame_id'])
        plan=by_view[record['plan_view_id']];raw=raw_reviews[result['source_frame_review_sha256']];frames[frame['id']]=(record,frame,plan,raw)
        fills={f['id']:f for f in plan['plan_gap_review']['page_fill_recovery']['candidates']}
        matrix=pymupdf.Matrix(plan['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
        axis=np.asarray(frame['diagnostic_axis']);normal=np.array([-axis[1],axis[0]]);origin=np.asarray(frame['source_native_endpoints'][0])
        look=float(np.dot(frame['marker_direction_pdf_native'],normal));towards=-normal*(1 if look>0 else -1)
        for trace in result['paint_reviews']:
            extent=next(e for e in raw['plan_extents'] if e['id']==trace['source_extent_id']);assert digest(extent)==trace['source_extent_sha256']
            base=trace['base_profile'];profiles={p['id']:p for p in [base,*trace['return_profiles']]};geometries={}
            for profile in profiles.values():
                fill=fills[profile['source_fill_id']];geometry=affine_transform(shape(fill['geometry']),affine(matrix));geometries[profile['id']]=geometry
                assert digest(fill)==profile['source_fill_sha256'] and geometry.equals_exact(shape(profile['geometry_pdf_native']),0)
                parts=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
                assert profile['source_hole_count']==sum(len(p.interiors) for p in parts)
                assert profile['source_paint_seqno']==fill['paint_seqno'] and profile['source_clip_path_ordinals']==[c['path_ordinal'] for c in fill['clip_references']]
                for vertex in profile['vertices']:
                    coords=list(parts[vertex['part_index']].exterior.coords)[:-1];point=coords[vertex['exterior_vertex_index']]
                    assert list(point)==vertex['point_pdf_native']
                    assert abs(float((np.asarray(point)-origin)@axis)-vertex['along_pdf_points'])<1e-9
                    assert abs(float((np.asarray(point)-origin)@normal)-vertex['normal_pdf_points'])<1e-9
                    checked['original_return_corner_vertices']+=1
                for edge in profile['edges']:
                    coords=list(parts[edge['part_index']].exterior.coords)[:-1];i=edge['edge_index'];a=np.asarray(coords[i]);b=np.asarray(coords[(i+1)%len(coords)])
                    assert [a.tolist(),b.tolist()]==edge['source_native_endpoints']
                    p=(a+b)/2+towards*.1;q=(a+b)/2-towards*.1
                    assert np.allclose(p,edge['marker_probe_pdf_native'],rtol=0,atol=1e-9) and np.allclose(q,edge['away_probe_pdf_native'],rtol=0,atol=1e-9)
                    assert (geometry.contains(Point(p)),geometry.contains(Point(q)))==(edge['paint_on_marker_side'],edge['paint_on_away_side'])
                    assert abs(abs(float((b-a)@axis/np.linalg.norm(b-a)))-edge['axis_alignment_cosine'])<1e-9
                    checked['original_return_corner_edge_probes']+=1
                assert not profile['source_geometry_changed'] and not profile['physical_wall_role_verified']
            x0,x1=base['along_interval_pdf_points'];y0,y1=base['normal_interval_pdf_points'];unit=plan['nominal_metres_per_pdf_point'];expected={'left':set(),'right':set()}
            if .08<=(y1-y0)*unit<=1 and x1-x0>=3*(y1-y0):
                for fill in fills.values():
                    if fill['id']==base['source_fill_id'] or fill['fill_color']!=fills[base['source_fill_id']]['fill_color'] or fill['fill_opacity']!=1:continue
                    geometry=affine_transform(shape(fill['geometry']),affine(matrix))
                    if geometries[base['id']].distance(geometry)>.25 or not shape(views[plan['view_id']]['geometry']).covers(geometry):continue
                    points=[np.asarray(p)-origin for part in (geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry]) for p in part.exterior.coords]
                    xs=[float(p@axis) for p in points];ys=[float(p@normal) for p in points];a,b,c,d=min(xs),max(xs),min(ys),max(ys)
                    if not (.08<=(b-a)*unit<=1 and d-c>=3*(b-a) and max(c-y1,y0-d,0)<=.25):continue
                    for end,value in [('left',x0),('right',x1)]:
                        if a-.25<=value<=b+.25:expected[end].add(fill['id'])
            for end,candidates in trace['return_candidates'].items():
                assert {profiles[c['source_profile_id']]['source_fill_id'] for c in candidates}==expected[end]
                for candidate in candidates:
                    distance=geometries[base['id']].distance(geometries[candidate['source_profile_id']])
                    assert abs(distance-candidate['source_boundary_distance_pdf_points'])<1e-12
                    assert candidate['exact_source_contact']==(distance==0) and not candidate['joint_geometry_repaired']
                    checked['independent_original_return_links']+=1
                    if distance>0:checked['proximity_only_source_return_links']+=1
            assert len(trace['corner_pairs'])==2*sum(a['source_profile_id']!=b['source_profile_id'] for a in trace['return_candidates']['left'] for b in trace['return_candidates']['right'])
            for pair in trace['corner_pairs']:
                for end,corner,link in zip(('left','right'),pair['corners'],(pair['left_return'],pair['right_return']),strict=True):
                    other=profiles[link['source_profile_id']];plane=(y0 if look>0 else y1) if pair['paint_side']=='marker_facing' else (y1 if look>0 else y0)
                    endpoint=x0 if end=='left' else x1;band=max(y1-y0,other['along_interval_pdf_points'][1]-other['along_interval_pdf_points'][0])+.25;eligible={}
                    for profile in (base,other):
                        edges={(e['part_index'],e['edge_index']):e for e in profile['edges']};positions={(v['part_index'],v['exterior_vertex_index']):v for v in profile['vertices']}
                        for vertex in profile['vertices']:
                            if abs(vertex['normal_pdf_points']-plane)>.25 or abs(vertex['along_pdf_points']-endpoint)>band:continue
                            for i in vertex['adjacent_edge_indices']:
                                edge=edges.get((vertex['part_index'],i))
                                if edge is None or edge['axis_alignment_cosine']<cosine:continue
                                size=sum(v['part_index']==vertex['part_index'] for v in profile['vertices'])
                                heights=[positions[(vertex['part_index'],j)]['normal_pdf_points'] for j in (i,(i+1)%size)]
                                desired=(False,True) if pair['paint_side']=='marker_facing' else (True,False)
                                if max(abs(v-plane) for v in heights)<=.25 and (edge['paint_on_marker_side'],edge['paint_on_away_side'])==desired:eligible[vertex['id']]=vertex
                    assert {c['id'] for c in corner['candidates']}==set(eligible)
                    if not eligible:assert corner['selected_vertex'] is None;continue
                    value=(min if end=='left' else max)(v['along_pdf_points'] for v in eligible.values())
                    assert abs(corner['selected_vertex']['along_pdf_points']-value)<=1e-9 and corner['selected_vertex']['id'] in eligible
                    assert not corner['physical_corner_identity_verified'];checked['independent_original_side_corner_choices']+=1
                corners[pair['id']]=pair
    for diagnostic in returns['diagnostics']:
        corner=corners[diagnostic['source_corner_pair_id']];assert digest(corner)==diagnostic['source_corner_pair_sha256']
        record,frame,plan,raw=frames[diagnostic['frame_id']];pair=pairs[diagnostic['pair_id']]
        inverse=np.asarray(pair['layout_fit']['subject_to_reference_linear_row_matrix']);axis=np.asarray(frame['diagnostic_axis'])@inverse;axis/=np.linalg.norm(axis)
        origin=np.asarray(frame['source_native_endpoints'][0]);unit=plan['nominal_metres_per_pdf_point']
        def project(p):return float((np.asarray(p)-origin)@inverse@axis*unit)
        interval=sorted(project(c['selected_vertex']['point_pdf_native']) for c in corner['corners']);assert np.allclose(interval,diagnostic['layout_position_interval_m'],rtol=0,atol=1e-9)
        target=record['target_elevation_view_ids'][0];pixel_unit=level_views[target]['pixel_edge_to_source_display_matrix'][0]*by_view[target]['nominal_metres_per_pdf_point'];accepted=set()
        for field in ('raw_width_comparisons','layout_width_comparisons'):
            span=interval[1]-interval[0] if field=='layout_width_comparisons' else (corner['corners'][1]['selected_vertex']['along_pdf_points']-corner['corners'][0]['selected_vertex']['along_pdf_points'])*unit
            for comparison in diagnostic[field]:
                parent=families[comparison['parent_family_review_id']];assert abs(span-comparison['nominal_plan_width_m'])<1e-9;passes=[]
                for witness,source in zip(comparison['witnesses'],parent['witnesses'],strict=True):
                    bounds=source['source_bounds_pixels'];measured=(bounds[2]-bounds[0])*pixel_unit;passes.append(abs(measured-span)<=.25)
                    assert abs(measured-span-witness['elevation_minus_plan_width_m'])<1e-9 and witness['within_discovery_tolerance']==passes[-1]
                    if field=='layout_width_comparisons':checked['independent_return_extent_witnesses']+=1
                assert comparison['status']==('all_witness_extent_widths_compatible' if all(passes) else 'extent_width_witnesses_disagree' if any(passes) else 'independent_extent_width_mismatch')
                if all(passes) and field=='layout_width_comparisons':accepted.add(parent['id'])
        expected={(r['parent_family_review_id'],r['child_family_review_id'],link['projection_id'],reverse) for r in raw['parent_child_relations'] if r['parent_family_review_id'] in accepted
            for link in levels['level_supported_width_links'] if digest(link)==r['source_level_link_sha256'] for reverse in (False,True)}
        assert {(p['parent_family_review_id'],p['child_family_review_id'],p['projection_id'],p['elevation_x_reversed']) for p in diagnostic['position_comparisons']}==expected
        for position in diagnostic['position_comparisons']:
            parent=families[position['parent_family_review_id']];child=families[position['child_family_review_id']]
            projection=next(p for p in buildings['projected_gaps'] if p['id']==position['projection_id']);gap=next(g for g in plan['plan_gap_review']['gaps'] if g['id']==projection['source_gap_id'])
            target_interval=sorted(project(p) for p in gap['gap_endpoints_pdf_native']);assert digest(gap)==position['source_gap_projection']['source_gap_sha256']
            assert np.allclose(target_interval,position['source_gap_projection']['nominal_plan_position_interval_m'],rtol=0,atol=1e-9);passes=[]
            for witness,(outer,inner) in zip(position['witnesses'],[(a,b) for a in parent['witnesses'] for b in child['witnesses']],strict=True):
                a=outer['source_bounds_pixels'][0];bounds=inner['source_bounds_pixels'];distances=[(bounds[i]-a)*pixel_unit for i in (0,2)]
                observed=sorted(interval[1]-v for v in distances) if position['elevation_x_reversed'] else [interval[0]+v for v in distances]
                error=max(abs(observed[i]-target_interval[i]) for i in (0,1));passes.append(error<=.25)
                assert abs(error-witness['maximum_endpoint_residual_m'])<1e-9 and np.allclose(observed,witness['nominal_position_interval_m'],rtol=0,atol=1e-9)
                assert digest(outer)==witness['source_parent_witness_sha256'] and digest(inner)==witness['source_child_witness_sha256'];checked['independent_return_position_witnesses']+=1
            assert position['status']==('all_witness_positions_compatible' if all(passes) else 'position_witnesses_disagree' if any(passes) else 'independent_origin_position_mismatch')
            assert not position['origin_fit_to_opening'] and not position['physical_correspondence_verified'] and not position['position_alignment_verified']
