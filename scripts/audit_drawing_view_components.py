"""Verify unseeded view inventories against original parents and a fresh replay."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import pymupdf
from PIL import Image

from shapely.affinity import affine_transform
from shapely.geometry import Point, Polygon, box, shape

from voxel_mapper.area_reconstruction import run as area_run
from voxel_mapper.drawing_components import split_page
from voxel_mapper.drawing_view_components import run as inventory, orient, affine
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.planning_bulk import Corpus
from voxel_mapper.reconstruction_evidence_queue import digest
from voxel_mapper.raster_opening_scan import scan as opening_scan
from voxel_mapper import automatic_opening_links, clipped_plan_fills, fill_endcaps
from voxel_mapper import automatic_building_scope, plan_elevation_edges
from voxel_mapper import automatic_elevation_context, elevation_levels, automatic_facade_alignment
from voxel_mapper import automatic_sheet_scale, drawing_annotations
from scripts.audit_wall_return_corners import verify as verify_wall_returns
from scripts.audit_door_symbol_evidence import verify as verify_door_symbols
from scripts.audit_artwork_scale_controls import verify as verify_artwork_controls
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.glyph_visibility import screen_architectural_span
from voxel_mapper.ordinary_surfaces import label_runs


def verify_building_scope(page, view, result, checked):
    review = result['building_scope_review']
    if review['status']!='named_source_enclosure_candidates_only': return
    edges = plan_elevation_edges.straight_edges(page, result['document_sha256'], result['page'])
    assert digest(edges)==review['source_edges_sha256']
    fills = result['plan_gap_review']['page_fill_recovery']['candidates']
    assert digest(fills)==review['source_fills_sha256']
    edge_lookup = {e['id']: e for e in edges}; fill_lookup = {f['id']: f for f in fills}
    runs = {(tuple(r['trace_indices']),tuple(r['character_indices'])): r for r in label_runs(page.get_texttrace())}
    matrix = pymupdf.Matrix(result['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
    expected = set(); gap_lookup = {g['id']: g for g in result['plan_gap_review']['gaps']}
    for label in review['labels']:
        run = runs[(tuple(label['trace_indices']),tuple(label['character_indices']))]
        assert ''.join(chr(c[0]) for c in run['chars']).strip()==label['text']
        rect = pymupdf.Rect(run['bbox'])
        native_label = Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        assert native_label.equals_exact(shape(label['geometry_pdf_native']),0)
        source = label['source_only_enclosure_review']
        if source is None:
            assert not label['candidates']; continue
        assert not source['gap_effects'] and all(not t['active_gap_ids'] for t in source['trials'])
        candidate_lookup = {c['id']: c for c in source['candidates']}
        for candidate in label['candidates']:
            original = candidate_lookup[candidate['id']]
            assert digest(original)==candidate['source_candidate_sha256']
            polygon = affine_transform(shape(original['geometry']),affine(matrix))
            assert polygon.equals_exact(shape(candidate['geometry_pdf_native']),0)
            assert polygon.contains(native_label) and shape(view['geometry']).covers(polygon)
            assert len(polygon.interiors)==candidate['source_hole_count']
            for proof in original['boundary_provenance']:
                if proof['kind']=='original_stroke':
                    assert digest(proof['source_endpoints'])==digest(edge_lookup[proof['source_edge_id']]['points'])
                else:
                    assert proof['kind']=='original_fill_boundary'
                    fill = fill_lookup[proof['source_fill_id']]; geometry = shape(fill['geometry'])
                    part = list(geometry.geoms)[proof['part_index']] if geometry.geom_type=='MultiPolygon' else geometry
                    ring = part.exterior if proof['ring_index']==0 else part.interiors[proof['ring_index']-1]
                    coords = list(ring.coords); i = proof['segment_index']
                    assert digest(proof['source_endpoints'])==digest([list(coords[i]),list(coords[i+1])])
                    assert proof['paint_seqno']==fill['paint_seqno']
                    assert proof['clip_source_path_ordinals']==[c['path_ordinal'] for c in fill['clip_references']]
                checked['named_enclosure_boundary_proofs'] += 1
            for gap in gap_lookup.values():
                corridor = shape(gap['geometry_pdf_native']); fraction = polygon.intersection(corridor).area/corridor.area
                if fraction>0: expected.add((label['id'],candidate['id'],gap['id']))
            checked['whole_label_named_enclosures'] += 1
            checked['named_enclosure_protected_holes'] += len(polygon.interiors)
        for identifier in label['whole_label_crossing_candidate_ids']:
            polygon = affine_transform(shape(candidate_lookup[identifier]['geometry']),affine(matrix))
            assert not polygon.contains(native_label)
            checked['whole_label_crossing_enclosures_withheld'] += 1
        checked['original_named_labels'] += 1
    observed = {(r['label_id'],r['enclosure_id'],r['source_gap_id']) for r in review['gap_links']}
    assert observed==expected and len(observed)==len(review['gap_links'])
    for link in review['gap_links']:
        label = next(r for r in review['labels'] if r['id']==link['label_id'])
        candidate = next(c for c in label['candidates'] if c['id']==link['enclosure_id'])
        corridor = shape(gap_lookup[link['source_gap_id']]['geometry_pdf_native'])
        assert link['corridor_overlap_area_fraction']==shape(candidate['geometry_pdf_native']).intersection(corridor).area/corridor.area
        assert not link['physical_building_assignment_verified']
    checked['independent_named_gap_links'] += len(observed)


def verify_elevation_context(corpus, source_pages, inventories, buildings, context, checked, max_checks):
    fresh = automatic_elevation_context.run(corpus,source_pages,inventories,buildings,max_checks=max_checks)
    assert digest(fresh)==digest(context)
    if context['status']!='source_relative_elevation_context_only': return
    by_view = {v['view_id']:v for v in inventories}; qualified = {}
    for page_context in context['pages']:
        sha=page_context['document_sha256']; number=page_context['page']
        with pymupdf.open(corpus.root/'files'/(sha+'.pdf')) as document:
            page=document[number-1]; paths=page.get_drawings(extended=True); traces=page.get_texttrace()
            fills=clipped_plan_fills.recover(page,sha,number)['candidates']; fill_lookup={f['paint_ordinal']:f for f in fills}
            rotation=page.rotation_matrix
            for record in page_context['level_review']['records']:
                path=paths[record['source_circle_path_ordinal']]
                assert len(path['items'])==4 and all(item[0]=='c' for item in path['items'])
                assert list(pymupdf.Rect(path['rect'])*rotation)==record['circle_bbox_display_points']
                for ordinal,fill in zip(record['source_quadrant_path_ordinals'],record['source_quadrant_fills']):
                    assert digest(fill_lookup[ordinal])==digest(fill)
                    assert list(fill['fill_color'])==[0,0,0]
                    checked['original_level_quadrant_fills']+=1
                for line in record['datum_line_candidates']:
                    item=paths[line['source_path_ordinal']]['items'][0]; assert item[0]=='l'
                    assert digest([list(p*rotation) for p in item[1:3]])==digest(line['display_endpoints'])
                    checked['original_level_leader_lines']+=1
                for label in record['label_candidates']:
                    span=traces[label['trace_index']]
                    assert ''.join(chr(c[0]) for c in span['chars']).strip()==label['text']
                    assert digest(elevation_levels.screen_span(page,span))==digest(label['glyph_screen'])
                    assert list(pymupdf.Rect(span['bbox'])*rotation)==label['bbox_display_points']
                    checked['original_level_glyph_claims']+=1
                expected=[]
                for scope in page_context['source_scopes']:
                    bounds=pymupdf.Rect(scope['display_bounds'])
                    if (bounds.contains(pymupdf.Rect(record['circle_bbox_display_points']))
                            and all(bounds.contains(pymupdf.Rect(l['bbox_display_points'])) for l in record['label_candidates'])
                            and all(bounds.contains(pymupdf.Point(*p)) for l in record['datum_line_candidates'] for p in l['display_endpoints'])):
                        expected.append(scope['view_key_candidate'])
                assert expected==record['view_key_candidates']
                checked['whole_view_level_markers']+=1
    for view in context['views']:
        inventory=by_view[view['view_id']]; reference=view['relative_reference']
        if view['status']!='all_original_residual_families_reviewed_against_source_level':continue
        index=inventory['residual_raster_scan']['index']; matrix=pymupdf.Matrix(view['pixel_edge_to_source_display_matrix'])
        # Point/Matrix inversion through MuPDF rounds to single precision.
        # Solve the retained affine coefficients independently in float64.
        level=float(np.linalg.solve(np.array([[matrix.a,matrix.c],[matrix.b,matrix.d]],dtype=float),
            np.array([-matrix.e,reference['datum_y_display_points']-matrix.f],dtype=float))[1])
        assert [f['consensus_family_index'] for f in view['families']]==list(range(len(index['consensus_families'])))
        for family in view['families']:
            original=index['consensus_families'][family['consensus_family_index']]
            assert digest(original)==family['source_family_sha256']
            expected=[(0,original['first_pair_index']),*[(1,i) for i in original['second_pair_indices']]]
            assert expected==[(w['variant_index'],w['pair_index']) for w in family['witnesses']]
            assert abs(level-family['printed_level_pixel_candidate'])<=1e-9
            counts=[]
            for witness in family['witnesses']:
                variant=index['variants'][witness['variant_index']]; pair=variant['pairs'][witness['pair_index']]
                groups=[variant['jamb_groups'][i] for i in pair['jamb_group_indices']]
                assert digest(pair)==witness['source_pair_sha256'] and pair['bounds_pixels']==witness['source_bounds_pixels']
                assert [digest(g) for g in groups]==witness['source_group_sha256']
                top=max(g['top'] for g in groups); bottom=min(g['bottom'] for g in groups)
                end=min(bottom,math.floor(level)); rows=max(0,end-top); counts.append(rows)
                assert witness['common_jamb_row_interval_pixels']==[top,bottom]
                assert witness['whole_rows_above_printed_level_interval_pixels']==([top,end] if rows else None)
                assert witness['whole_rows_above_printed_level']==rows
                assert witness['minimum_above_level_rows_met']==(rows>=24)
                head=(reference['datum_y_display_points']-(pair['bounds_pixels'][1]*matrix.d+matrix.f))*inventory['nominal_metres_per_pdf_point']
                assert abs(head-witness['nominal_head_above_printed_level_m'])<=1e-9
                checked['original_threshold_level_witnesses']+=1
            expected_status=('all_threshold_witnesses_support_above_level_rows' if min(counts)>=24 else
                'threshold_witnesses_disagree_about_above_level_rows' if max(counts)>=24 else 'insufficient_above_level_rows_in_all_witnesses')
            assert family['status']==expected_status and family['observed_above_level_row_count_range']==[min(counts),max(counts)]
            assert not family['source_geometry_changed'] and not family['physical_opening_verified']
            if min(counts)>=24 and family['candidate_scope_status']!='candidate_scope_crossing_withheld':
                qualified[(view['view_id'],family['residual_family_id'])]=family['id']
            checked['independent_source_level_family_reviews']+=1
    expected={(w['projection_id'],w['source_width_link_id'],w['elevation_view_id'],w['residual_family_id'])
        for w in buildings['width_links'] if (w['elevation_view_id'],w['residual_family_id']) in qualified}
    observed={(w['projection_id'],w['source_width_link_id'],w['elevation_view_id'],w['residual_family_id'])
        for w in context['level_supported_width_links']}
    assert observed==expected and len(observed)==len(context['level_supported_width_links'])
    for link in context['level_supported_width_links']:
        original=next(w for w in buildings['width_links'] if digest(w)==link['source_building_link_sha256'])
        assert link['family_review_id']==qualified[(original['elevation_view_id'],original['residual_family_id'])]
        assert not link['physical_correspondence_verified'] and not link['position_alignment_verified']
    checked['independent_level_supported_width_links']+=len(observed)


def verify_facade_alignment(source_pages, inventories, buildings, levels, alignment, checked, max_checks):
    assert digest(automatic_facade_alignment.run(source_pages,inventories,buildings,levels,max_checks=max_checks))==digest(alignment)
    if alignment['status']!='independent_source_extent_and_origin_hypotheses_only': return
    by_view={v['view_id']:v for v in inventories}
    views={v['id']:v for p in source_pages for v in p['views']}
    level_views={v['view_id']:v for v in levels['views']}
    records={r['id']:r for r in buildings['frames']}
    projections={p['id']:p for p in buildings['projected_gaps']}
    for row in alignment['frames']:
        original=records[row['facade_record_id']]; plan=by_view[original['plan_view_id']]
        assert digest(original)==row['source_facade_record_sha256']
        if row['status']!='independent_extent_reviews_only':
            assert not row['frame_reviews']; continue
        target=original['target_elevation_view_ids'][0]; level=level_views[target]
        families={f['id']:f for f in level['families']}; matrix=level['pixel_edge_to_source_display_matrix']
        unit=by_view[target]['nominal_metres_per_pdf_point']; pixel_unit=matrix[0]*unit
        for review in row['frame_reviews']:
            frame=next(f for f in original['frame_review']['frames'] if f['id']==review['frame_id'])
            label=next(l for l in plan['building_scope_review']['labels'] if l['id']==original['label_id'])
            enclosure=next(c for c in label['candidates'] if c['id']==original['enclosure_id'])
            inverse=pymupdf.Matrix(plan['plan_gap_review']['unrotated_mupdf_to_pdf_native_matrix'])
            expected_sources={('named_enclosure',enclosure['id']):(enclosure,shape(enclosure['geometry_pdf_native']))}
            for fill in plan['plan_gap_review']['page_fill_recovery']['candidates']:
                if fill['fill_color']==[1,1,1]:continue
                geometry=affine_transform(shape(fill['geometry']),affine(inverse))
                if (min(geometry.boundary.distance(Point(p)) for p in frame['ray_hits_pdf_native'])<=.25
                        and shape(views[plan['view_id']]['geometry']).covers(geometry)):
                    expected_sources[('near_ray_original_paint',fill['id'])]=(fill,geometry)
            assert {(e['source_kind'],e['source_id']) for e in review['plan_extents']}==set(expected_sources)
            extents={e['id']:e for e in review['plan_extents']}
            for extent in extents.values():
                record,geometry=expected_sources[(extent['source_kind'],extent['source_id'])]
                assert extent['source_record_sha256']==digest(record)
                assert geometry.equals_exact(shape(extent['geometry_pdf_native']),0)
                parts=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
                positions=[sum(point[i]*frame['diagnostic_axis'][i] for i in (0,1))*plan['nominal_metres_per_pdf_point']-frame['projection_min_m']
                    for part in parts for point in part.exterior.coords]
                assert extent['nominal_plan_position_interval_m']==[min(positions),max(positions)]
                assert extent['source_part_count']==len(parts) and extent['source_hole_count']==sum(len(p.interiors) for p in parts)
                for witness in extent['source_extreme_vertices']:
                    point=list(parts[witness['part_index']].exterior.coords[witness['exterior_vertex_index']])
                    assert point==witness['point_pdf_native']
                    checked['independent_plan_extent_vertex_proofs']+=1
                assert not extent['span_establishes_continuity'] and not extent['physical_facade_extent_verified']
                checked['independent_whole_plan_extent_candidates']+=1
            links=[l for l in levels['level_supported_width_links'] if l['elevation_view_id']==target
                and projections[l['projection_id']]['facade_record_id']==original['id']
                and projections[l['projection_id']]['frame_id']==frame['id']]
            assert review['reviewed_level_link_sha256']==[digest(l) for l in links]
            def surrounds(outer,inner):
                if outer['id']==inner['id']:return False
                return all(a['source_bounds_pixels'][0]<b['source_bounds_pixels'][0]
                    and a['source_bounds_pixels'][2]>b['source_bounds_pixels'][2]
                    and a['source_bounds_pixels'][1]<b['source_bounds_pixels'][1]
                    and a['source_bounds_pixels'][3]>=b['source_bounds_pixels'][3]
                    and (a['variant_index']!=b['variant_index'] or not set(a['jamb_group_indices'])&set(b['jamb_group_indices']))
                    for a in outer['witnesses'] for b in inner['witnesses'])
            expected_relations=set()
            for link in links:
                child=next(f for f in families.values() if f['residual_family_id']==link['residual_family_id'])
                for parent in families.values():
                    if (parent['status']=='all_threshold_witnesses_support_above_level_rows'
                            and parent['candidate_scope_status']!='candidate_scope_crossing_withheld' and surrounds(parent,child)):
                        expected_relations.add((digest(link),parent['id'],child['id']))
            assert {(r['source_level_link_sha256'],r['parent_family_review_id'],r['child_family_review_id'])
                for r in review['parent_child_relations']}==expected_relations
            checked['independent_all_witness_parent_child_relations']+=len(expected_relations)
            expected_extents={(e,parent) for _,parent,_ in expected_relations for e in extents}
            assert {(c['plan_extent_id'],c['parent_family_review_id']) for c in review['extent_comparisons']}==expected_extents
            accepted={}
            for comparison in review['extent_comparisons']:
                parent=families[comparison['parent_family_review_id']]; extent=extents[comparison['plan_extent_id']]
                assert digest(parent)==comparison['source_parent_review_sha256']
                low,high=extent['nominal_plan_position_interval_m']; width=high-low; passes=[]
                assert comparison['nominal_plan_width_m']==width
                for witness,original_witness in zip(comparison['witnesses'],parent['witnesses'],strict=True):
                    bounds=original_witness['source_bounds_pixels']; measured=(bounds[2]-bounds[0])*pixel_unit
                    assert witness['source_witness_sha256']==digest(original_witness)
                    assert abs(witness['nominal_elevation_width_m']-measured)<1e-9
                    assert abs(witness['elevation_minus_plan_width_m']-(measured-width))<1e-9
                    assert abs(witness['diagnostic_elevation_to_plan_width_ratio']-measured/width)<1e-9
                    passes.append(abs(measured-width)<=.25)
                    assert witness['within_discovery_tolerance']==passes[-1]
                    checked['independent_extent_threshold_widths']+=1
                expected_status='all_witness_extent_widths_compatible' if all(passes) else 'extent_width_witnesses_disagree' if any(passes) else 'independent_extent_width_mismatch'
                assert comparison['status']==expected_status and not comparison['scale_correction_applied']
                if all(passes):accepted[(extent['id'],parent['id'])]=comparison['id']
            expected_positions={(e,parent,child,l['projection_id'],reverse)
                for link_sha,parent,child in expected_relations for l in links if digest(l)==link_sha
                for e in extents if (e,parent) in accepted for reverse in (False,True)}
            observed_positions={(p['plan_extent_id'],p['parent_family_review_id'],p['child_family_review_id'],p['projection_id'],p['elevation_x_reversed'])
                for p in review['position_comparisons']}
            assert expected_positions==observed_positions
            for position in review['position_comparisons']:
                parent=families[position['parent_family_review_id']]; child=families[position['child_family_review_id']]
                extent=extents[position['plan_extent_id']]; low,high=extent['nominal_plan_position_interval_m']
                target_interval=projections[position['projection_id']]['nominal_plan_position_interval_m']
                assert position['source_extent_comparison_id']==accepted[(extent['id'],parent['id'])]
                expected_witnesses=[(a,b) for a in parent['witnesses'] for b in child['witnesses']]; passes=[]
                for witness,(outer,inner) in zip(position['witnesses'],expected_witnesses,strict=True):
                    bounds=inner['source_bounds_pixels']; left=outer['source_bounds_pixels'][0]
                    observed=[(x-left)*pixel_unit for x in (bounds[0],bounds[2])]
                    interval=sorted(high-x for x in observed) if position['elevation_x_reversed'] else [low+x for x in observed]
                    assert np.allclose(interval,witness['nominal_position_interval_m'],rtol=0,atol=1e-9)
                    residual=max(abs(interval[i]-target_interval[i]) for i in (0,1)); passes.append(residual<=.25)
                    assert abs(residual-witness['maximum_endpoint_residual_m'])<1e-9
                    assert witness['source_parent_witness_sha256']==digest(outer) and witness['source_child_witness_sha256']==digest(inner)
                    checked['independent_origin_position_witnesses']+=1
                assert position['status']==('all_witness_positions_compatible' if all(passes) else 'position_witnesses_disagree' if any(passes) else 'independent_origin_position_mismatch')
                assert not position['origin_fit_to_opening'] and not position['scale_correction_applied']
                assert not position['position_alignment_verified'] and not position['physical_correspondence_verified']


def verify_sheet_scale(corpus, source_pages, inventories, buildings, levels, alignment, scale, checked, max_checks):
    assert digest(automatic_sheet_scale.run(corpus,source_pages,inventories,buildings,levels,alignment,max_checks=max_checks))==digest(scale)
    if scale['status']!='peripheral_sheet_layout_evidence_only':return
    pages={(p['document_sha256'],p['page']):p for p in scale['pages']}
    for key,review in pages.items():
        with pymupdf.open(corpus.root/'files'/(key[0]+'.pdf')) as document:
            page=document[key[1]-1];inverse=native_inverse(page);runs=list(label_runs(page.get_texttrace()))
            original={(tuple(r['trace_indices']),tuple(r['character_indices'])):r for r in runs}
            counts=Counter(''.join(chr(c[0]) for c in r['chars']).strip() for r in runs)
            assert review['text_occurrence_counts']==dict(counts)
            x0,y0,x1,y1=review['native_page_bounds'];inner=box(x0+.2*(x1-x0),y0+.2*(y1-y0),x1-.2*(x1-x0),y1-.2*(y1-y0))
            for row in [*review['peripheral_text'],*review['dimension_text']]:
                run=original[(tuple(row['trace_indices']),tuple(row['character_indices']))]
                text=''.join(chr(c[0]) for c in run['chars']).strip();assert row['text']==text
                rect=pymupdf.Rect(run['bbox']);geometry=Polygon([tuple(p*inverse) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
                assert geometry.equals_exact(shape(row['geometry_pdf_native']),0)
                assert list(pymupdf.Point(run['chars'][0][2])*inverse)==row['origin_pdf_native']
                assert row['page_literal_occurrences']==counts[text]
                if row['glyph_screen'] is not None:
                    assert digest(screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6))==digest(row['glyph_screen'])
                    checked['original_sheet_scale_glyph_screens']+=1
                if 'claims' in row:
                    assert row['claims']==[c for c in drawing_annotations.categories(text) if c['kind'] in ('explicit_dimension','untyped_numeric')]
                    assert not row['component_dimension_verified']
                    checked['unassociated_original_dimension_texts']+=1
                else:
                    assert not inner.intersects(geometry) and box(x0,y0,x1,y1).covers(geometry)
                    checked['original_peripheral_text_records']+=1
    pairs={p['id']:p for p in scale['pairs']}
    for pair in pairs.values():
        a=pages[tuple(pair['subject_page_key'])];b=pages[tuple(pair['reference_page_key'])]
        assert digest(a)==pair['source_subject_review_sha256'] and digest(b)==pair['source_reference_review_sha256']
        if pair['layout_fit'] is None:continue
        terms=pair['terms'];assert [t['role'] for t in terms]==['holdout' if i%3==0 else 'fit' for i in range(len(terms))]
        assert [t['text'] for t in terms]==sorted(t['text'] for t in terms)
        fit=pair['layout_fit']
        if pair['status']!='supported_furniture_layout_correspondence_only':continue
        rows=fit['rows'];train=[r for r in rows if r['role']=='fit']
        reference=np.asarray([r['reference_origin'] for r in train]);subject=np.asarray([r['subject_origin'] for r in train])
        center=reference.mean(axis=0);coefficients=np.linalg.lstsq(np.column_stack((reference-center,np.ones(len(train)))),subject,rcond=None)[0]
        linear=coefficients[:2];translation=coefficients[2]-center@linear
        assert np.allclose(linear,fit['reference_to_subject_linear_row_matrix'],atol=1e-10,rtol=0)
        assert np.allclose(translation,fit['reference_to_subject_translation'],atol=1e-9,rtol=0)
        assert np.allclose(np.linalg.inv(linear),fit['subject_to_reference_linear_row_matrix'],atol=1e-10,rtol=0)
        for row in rows:
            residual=float(np.linalg.norm(np.asarray(row['reference_origin'])@linear+translation-np.asarray(row['subject_origin'])))
            assert abs(residual-row['residual_pdf_points'])<1e-9 and residual<=.25
            assert abs(row['observed_font_size_ratio']/math.sqrt(np.linalg.det(linear))-1)<=.015
            checked['independent_layout_'+row['role']+'_anchors']+=1
        assert not pair['physical_scale_verified'] and not pair['geometry_correction_applied']
    by_view={v['view_id']:v for v in inventories};records={r['id']:r for r in buildings['frames']}
    reviews={digest(r):r for row in alignment['frames'] for r in row['frame_reviews']}
    families={f['id']:f for v in levels['views'] for f in v['families']}
    for diagnostic in scale['diagnostics']:
        pair=pairs[diagnostic['pair_id']];review=reviews[diagnostic['source_frame_review_sha256']]
        record=records[diagnostic['facade_record_id']];plan=by_view[record['plan_view_id']]
        frame=next(f for f in record['frame_review']['frames'] if f['id']==diagnostic['frame_id'])
        inverse=np.asarray(pair['layout_fit']['subject_to_reference_linear_row_matrix']);axis=np.asarray(frame['diagnostic_axis'])@inverse;axis/=np.linalg.norm(axis)
        origin=np.asarray(frame['source_native_endpoints'][0]);unit=plan['nominal_metres_per_pdf_point']
        extents={e['id']:e for e in diagnostic['extents']};raw={e['id']:e for e in review['plan_extents']}
        for extent in extents.values():
            original=raw[extent['source_extent_id']];assert digest(original)==extent['source_extent_sha256']
            assert digest(original['geometry_pdf_native'])==extent['source_geometry_sha256']
            geometry=shape(original['geometry_pdf_native']);parts=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
            values=[float(np.dot(np.dot(np.asarray(p)-origin,inverse),axis)*unit) for part in parts for p in part.exterior.coords]
            assert np.allclose([min(values),max(values)],extent['nominal_plan_position_interval_m'],rtol=0,atol=1e-9)
            for proof in extent['diagnostic_extreme_vertices']:
                assert list(parts[proof['part_index']].exterior.coords[proof['exterior_vertex_index']])==proof['point_pdf_native']
                checked['independent_layout_extreme_vertex_proofs']+=1
            assert not extent['layout_application_verified'] and not extent['source_geometry_changed']
            checked['independent_layout_extent_candidates']+=1
        target=record['target_elevation_view_ids'][0];level=next(v for v in levels['views'] if v['view_id']==target)
        for comparison in diagnostic['width_comparisons']:
            parent=families[comparison['parent_family_review_id']];interval=extents[comparison['plan_extent_id']]['nominal_plan_position_interval_m'];width=interval[1]-interval[0]
            assert abs(width-comparison['nominal_plan_width_m'])<1e-9
            for witness,source in zip(comparison['witnesses'],parent['witnesses'],strict=True):
                bounds=source['source_bounds_pixels'];measured=(bounds[2]-bounds[0])*level['pixel_edge_to_source_display_matrix'][0]*by_view[target]['nominal_metres_per_pdf_point']
                assert abs(measured-witness['nominal_elevation_width_m'])<1e-9
                assert abs(measured-width-witness['elevation_minus_plan_width_m'])<1e-9
                assert witness['within_discovery_tolerance']==(abs(measured-width)<=.25)
                checked['independent_layout_threshold_widths']+=1
            assert not comparison['layout_application_verified'] and not comparison['scale_correction_applied']
    assert all(not r['automatic_geometry_authorized'] for r in scale['evidence_requirements'])


def audit(job, output, baseline=None):
    job = Path(job).resolve(); configuration = json.loads(job.read_text())
    if len(configuration['areas']) != 1: raise ValueError('One bounded area required')
    area = configuration['areas'][0]['id']; work = (job.parent/configuration['work_directory']).resolve()/area
    entry = area_run(job, stage='extract')['areas'][area]
    report = entry['drawing_view_components']; root = Path(report['directory']); pack = Path(entry['drawing_views']['directory'])
    source = json.loads((pack/'view-candidates.json').read_text())
    views = {v['id']: v for p in source['pages'] for v in p['views']}
    parents = {}
    with (work/'drawing-geometry/geometry-candidates.jsonl').open() as stream:
        for line in stream:
            record = json.loads(line); parents[record['id']] = record
    corpus = Corpus(work/'corpus')
    try:
        with tempfile.TemporaryDirectory(prefix='view-component-fresh-replay-') as temporary:
            fresh = inventory(corpus, work/'drawing-geometry', pack, Path(temporary)/'components', settings=report['contract']['options'])
            assert fresh['output_sha256'] == report['output_sha256']
    finally: corpus.close()
    checked = Counter(); rows = []; baseline_comparison = None; old_views = {}; inspected_views = []
    if baseline is not None:
        baseline = Path(baseline); baseline_report = json.loads((baseline/'component-report.json').read_text())
        for name, pin in baseline_report['output_sha256'].items(): assert file_hash(baseline/name) == pin
        old_views = {r['view_id']: json.loads((baseline/r['file']).read_text()) for r in baseline_report['results']}
        baseline_comparison = {'report_sha256': file_hash(baseline/'component-report.json'), 'views_checked': 0,
            'native_geometry_and_raw_scan_preserved': True,
            'comparison_scope': 'Original default attempts; selected partitioned fallbacks are additional evidence.'}
    for row in report['results']:
        result = json.loads((root/row['file']).read_text()); view = views[result['view_id']]
        inspected_views.append(result)
        if baseline is not None:
            old = old_views[result['view_id']]
            assert digest(old['source_components']) == digest(result['source_components'])
            assert digest(old['wall_band_candidates']) == digest(result['wall_band_candidates'])
            assert digest(old['native_rectangle_review']) == digest(result['native_rectangle_review'])
            assert [digest(r['geometry_pdf_native']) for r in old['closed_source_regions']] == [digest(r['geometry_pdf_native']) for r in result['closed_source_regions']]
            old_raw = old.get('legacy_group_limit_attempts', {}).get('raster', old['raster_opening_scan'])
            before = {k: v for k, v in old_raw.items() if k != 'version'}
            legacy = result['legacy_group_limit_attempts'].get('raster', result['raster_opening_scan'])
            after = {k: v for k, v in legacy.items() if k != 'version'}
            assert before == after
            if 'residual_raster_scan' in old:
                legacy_residual = result['legacy_group_limit_attempts'].get('residual', result['residual_raster_scan'])
                old_residual = old.get('legacy_group_limit_attempts', {}).get('residual', old['residual_raster_scan'])
                assert {k: v for k, v in old_residual.items() if k!='version'} == {k: v for k, v in legacy_residual.items() if k!='version'}
            baseline_comparison['views_checked'] += 1
        originals = [parents[s['id']] for s in view['whole_sources'] if s['kind'] == 'native_vector']
        components = sorted(split_page(originals), key=lambda r: r['id']); by_id = {r['id']: r for r in components}
        assert result['source_view_sha256'] == digest(view)
        assert digest(components) == digest(result['source_components'])
        assert result['source_parent_records_sha256'] == digest(sorted(originals, key=lambda r: r['id']))
        assert not result['world_placement_eligible'] and not result['physical_boundary_verified']
        if result['building_scope_review']['status']=='named_source_enclosure_candidates_only':
            with pymupdf.open(work/'corpus/files'/(result['document_sha256']+'.pdf')) as document:
                verify_building_scope(document[result['page']-1],view,result,checked)
        gaps = result['plan_gap_review']
        if gaps['status'] == 'whole_view_source_endcap_gaps_only':
            with pymupdf.open(work/'corpus/files'/(result['document_sha256']+'.pdf')) as document:
                fills = clipped_plan_fills.recover(document[result['page']-1], result['document_sha256'], result['page'])
            assert digest(fills) == digest(gaps['page_fill_recovery'])
            originals = fill_endcaps.recover(fills['candidates'], view['nominal_metres_per_pdf_point'],
                                            max_checks=report['contract']['options']['max_checks'])
            assert digest(originals) == digest(gaps['page_endcap_recovery'])
            lookup = {g['id']: g for g in originals['gaps']}
            matrix = pymupdf.Matrix(gaps['unrotated_mupdf_to_pdf_native_matrix'])
            fill_lookup = {c['id']: c for c in fills['candidates']}
            retained_ids = {g['id'] for g in gaps['gaps']}
            assert retained_ids | set(gaps['withheld_scope_gap_ids']) == set(lookup)
            assert not retained_ids & set(gaps['withheld_scope_gap_ids'])
            scope = shape(view['geometry'])
            for gap in gaps['gaps']:
                source_gap = lookup[gap['id']]
                assert gap['source_gap_sha256'] == digest(source_gap)
                native = affine_transform(shape(source_gap['gap_corridor_geometry']), affine(matrix))
                assert native.equals_exact(shape(gap['geometry_pdf_native']), 0) and scope.covers(native)
                assert gap['nominal_gap_width_m'] == source_gap['nominal_gap_width_m']
                assert gap['source_fill_overlap_present'] == bool(source_gap['intersecting_fill_candidates'])
                for cap in source_gap['source_endcaps']:
                    fill = fill_lookup[cap['fill_candidate_id']]; geometry = shape(fill['geometry'])
                    part = list(geometry.geoms)[cap['polygon_part']] if geometry.geom_type=='MultiPolygon' else geometry
                    coords = list(part.exterior.coords); i = cap['boundary_edge_index']
                    assert digest([list(coords[i]), list(coords[i+1])]) == digest(cap['source_endpoints'])
                    assert scope.covers(affine_transform(geometry, affine(matrix)))
                    checked['original_plan_endcap_edges'] += 1
                checked['whole_view_plan_gaps'] += 1
            checked['original_page_fill_records'] += len(fills['candidates'])
        for region in result['closed_source_regions']:
            record = by_id[region['source_component_id']]; g = shape(record['geometry'])
            if g.geom_type == 'LineString': g = Polygon(g.coords)
            assert digest(record) == region['source_component_sha256']
            assert g.equals_exact(shape(region['geometry_pdf_native']), 0)
            assert len(g.interiors) == region['source_hole_count']
            if region['geometry_nominal_local'] is not None:
                assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(region['geometry_nominal_local']), 0)
            checked['closed_regions'] += 1; checked['protected_holes'] += len(g.interiors)
        for frame in result['native_rectangle_review']['frames']:
            for side in frame['source_side_support']:
                assert side['source_intervals']
                for proof in side['source_intervals']:
                    record = by_id[proof['component_id']]; g = shape(record['geometry'])
                    chain = list(g.coords) if g.geom_type == 'LineString' else list(g.exterior.coords) if proof['ring_index'] == 0 else list(g.interiors[proof['ring_index']-1].coords)
                    i = proof['segment_index']
                    assert digest([list(chain[i]), list(chain[i+1])]) == digest(proof['native_endpoints'])
                    assert 0 <= proof['interval_fractions'][0] < proof['interval_fractions'][1] <= 1
                    checked['native_cycle_side_intervals'] += 1
        scan = result['raster_opening_scan']; families = scan['index']['consensus_families'] if scan['index'] else []
        matrix = None
        if result['raster_coordinate_receipt'] is not None:
            receipt = json.loads((pack/view['render']['receipt']).read_text())
            with Image.open(pack/view['render']['png']) as image: gray = np.asarray(image.convert('L')).copy()
            gray, matrix, k = orient(gray, receipt['pixel_edge_to_pdf_native_matrix'], view['caption_evidence']['reading_direction_pdf_native'])
            assert hashlib.sha256(gray.tobytes()).hexdigest() == scan['source_gray_sha256']
            assert list(matrix) == result['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix']
            checked['original_crop_gray_hashes'] += 1
        assert len(result['raster_opening_hypotheses']) == len(families)
        for h in result['raster_opening_hypotheses']:
            assert not h['physical_opening_verified'] and h['opening_type'] is None
            family = families[h['consensus_family_index']]
            g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
            assert g.equals_exact(shape(h['geometry_pdf_native']), 0)
            if h['geometry_nominal_local'] is not None:
                assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(h['geometry_nominal_local']), 0)
            assert (h['status']=='candidate_scope_crossing_withheld') == (not shape(view['geometry']).covers(g))
            checked['raster_families'] += 1
        context = result['repeated_stroke_context']; residual = result['residual_raster_scan']
        for inspected in [scan, residual]:
            for proof in inspected.get('group_partition_proofs', []):
                variant = next(v for v in inspected['index']['variants'] if v['threshold']==proof['threshold'])
                groups = variant['jamb_groups']; owners = {}; per_component = [0]*len(proof['components'])
                source_variant = next(v for v in context['variants'] if v['threshold']==proof['threshold'])
                excluded = {tuple(g) for g in inspected.get('excluded_group_bounds', {}).get(str(proof['threshold']), [])}
                expected = [g for g in source_variant['original_vertical_groups'] if tuple(g) not in excluded]
                assert [[g[k] for k in ['left', 'top', 'right', 'bottom']] for g in groups] == expected
                checked['partition_source_tables_verified'] += 1
                for k, component in enumerate(proof['components']):
                    assert len(component['group_indices']) <= inspected['recipe']['max_groups_per_component']
                    for i in component['group_indices']:
                        assert i not in owners; owners[i] = k
                assert set(owners) == set(range(len(groups)))
                for i, left in enumerate(groups):
                    for j, right in enumerate(groups):
                        if (inspected['recipe']['min_width_pixels'] <= right['left']-left['right'] <= inspected['recipe']['maximum_width_pixels']
                                and max(abs(left[k]-right[k]) for k in ['top', 'bottom']) <= 2):
                            assert owners[i] == owners[j]
                            per_component[owners[i]] += 1; checked['partition_eligible_pairs'] += 1
                assert per_component == [c['eligible_directed_pairs'] for c in proof['components']]
                assert sum(per_component) == proof['eligible_directed_pairs']
                assert proof['total_original_groups'] == len(groups)
                assert proof['max_component_groups'] == max((len(c['group_indices']) for c in proof['components']), default=0)
                for pair in variant['pairs']:
                    a, b = pair['jamb_group_indices']; assert owners[a] == owners[b]
                checked['partition_original_groups'] += len(groups)
        if context['status'] == 'repeated_stroke_layout_context_only':
            assert context['source_gray_sha256'] == scan['source_gray_sha256']
            for variant in context['variants']:
                groups = variant['original_vertical_groups']; union = set()
                for lattice in variant['lattices']:
                    ids = lattice['group_indices']; rows_for_lattice = [groups[i] for i in ids]
                    assert len(ids) >= 6 and len(set(ids)) == len(ids)
                    assert max(g[1] for g in rows_for_lattice)-min(g[1] for g in rows_for_lattice) <= 2
                    assert max(g[3] for g in rows_for_lattice)-min(g[3] for g in rows_for_lattice) <= 2
                    for a, b in zip(rows_for_lattice, rows_for_lattice[1:]):
                        pitch = b[0]-a[0]
                        assert 2 <= pitch <= 16 and abs(pitch-lattice['first_pitch_pixels']) <= 1 and b[0] > a[2]
                    assert all(1 <= g[2]-g[0] <= 3 for g in rows_for_lattice)
                    union.update(ids)
                assert sorted(union) == variant['residual_excluded_group_indices']
                assert context['excluded_groups'][str(variant['threshold'])] == [groups[i] for i in sorted(union)]
                dark = gray < variant['threshold']
                for left, top, right, bottom in groups:
                    assert dark[top:bottom, left:right].all() and not dark[top-1, left:right].any() and not dark[bottom, left:right].any()
                    checked['original_stroke_groups'] += 1
            recomputed = opening_scan(gray, representation='indexed', pair_scope='all',
                max_checks=report['contract']['options']['max_checks'], excluded_groups=context['excluded_groups'],
                partition_groups='group_partition_proofs' in residual)
            assert recomputed == residual
            if residual['index'] is not None:
                families = residual['index']['consensus_families']
                assert len(families) == len(result['residual_raster_hypotheses'])
                for h in result['residual_raster_hypotheses']:
                    family = families[h['consensus_family_index']]
                    g = affine_transform(box(*family['bounds_pixels']), affine(matrix))
                    assert g.equals_exact(shape(h['geometry_pdf_native']), 0)
                    assert not h['physical_opening_verified'] and h['opening_type'] is None
                    if h['geometry_nominal_local'] is not None:
                        assert affine_transform(g, view['native_to_nominal_local_affine']).equals_exact(shape(h['geometry_nominal_local']), 0)
                    checked['residual_family_transforms'] += 1
        text = result['native_cycle_text_context']
        frame_lookup = {f['id']: f for f in result['native_rectangle_review']['frames']}
        for cycle in text['cycles']:
            assert not cycle['physical_opening_verified'] and not cycle['automatic_geometry_selection']
            for i in cycle['visible_label_indices']:
                label = text['labels'][i]
                assert label['glyph_screen']['status'] == 'raster_consistent_candidate'
                g = shape(frame_lookup[cycle['cycle_id']]['geometry_pdf_native']); label_geometry = shape(label['geometry_pdf_native'])
                assert g.intersection(label_geometry).area > 0
                assert cycle['cycle_id'] in label['intersecting_cycle_ids']
                relation = next(r for r in label['cycle_box_relations'] if r['cycle_id']==cycle['cycle_id'])
                assert relation['label_box_overlap_fraction'] == g.intersection(label_geometry).area/label_geometry.area
                assert (relation['relationship']=='whole_label_box_contained') == g.covers(label_geometry)
                checked['original_glyph_cycle_links'] += 1
        rows.append({'caption': result['caption'], 'view_id': result['view_id'], 'printed_claim': result['printed_claim'],
            'counts': result['counts'], 'native_status': result['native_rectangle_review']['status'],
            'raster_status': scan['status'], 'scan_checks': scan.get('checks', 0),
            'residual_raster_status': residual['status'], 'residual_scan_checks': residual.get('checks', 0),
            'text_context_status': text['status'],
            'source_png_sha256': result['source_png_sha256'], 'source_components_sha256': digest(components)})
    opening_links = json.loads((root/report['opening_links']['file']).read_text())
    assert automatic_opening_links.compare(inspected_views, max_checks=report['contract']['options']['max_checks']) == opening_links
    if baseline is not None and 'opening_links' in baseline_report:
        before = json.loads((baseline/baseline_report['opening_links']['file']).read_text())
        keys = ['plan_view_id','source_gap_id','elevation_view_id','consensus_family_index',
                'plan_nominal_width_m','elevation_nominal_width_m','elevation_minus_plan_width_m',
                'source_fill_overlap_present','construction_state_unresolved']
        assert sorted(tuple(m[k] for k in keys) for m in before['matches'])==sorted(tuple(m[k] for k in keys) for m in opening_links['matches'])
        baseline_comparison['nominal_width_pairs_preserved'] = len(opening_links['matches'])
    by_view = {v['view_id']: v for v in inspected_views}; expected = set()
    for plan in inspected_views:
        for gap in plan['plan_gap_review']['gaps']:
            for elevation in inspected_views:
                scale = elevation['nominal_metres_per_pdf_point']
                scan = elevation['residual_raster_scan']
                if scan.get('index') is None or scale is None: continue
                states = [v['printed_claim'].get('printed_state', 'unspecified') for v in (plan, elevation)]
                if 'unspecified' not in states and states[0] != states[1]: continue
                matrix = elevation['raster_coordinate_receipt']['pixel_edge_to_pdf_native_matrix']
                for h in elevation['residual_raster_hypotheses']:
                    if h['status']=='candidate_scope_crossing_withheld': continue
                    family = scan['index']['consensus_families'][h['consensus_family_index']]
                    width = (family['bounds_pixels'][2]-family['bounds_pixels'][0])*(matrix[0]**2+matrix[1]**2)**.5*scale
                    if abs(width-gap['nominal_gap_width_m']) <= .25:
                        expected.add((plan['view_id'], gap['id'], elevation['view_id'], h['id']))
                    checked['independent_width_pair_comparisons'] += 1
    if opening_links['status']=='nominal_width_links_only':
        observed = {(m['plan_view_id'], m['source_gap_id'], m['elevation_view_id'], m['residual_family_id']) for m in opening_links['matches']}
        assert observed == expected and len(observed)==len(opening_links['matches'])
        for match in opening_links['matches']:
            assert match['plan_inventory_sha256']==digest(by_view[match['plan_view_id']])
            assert match['elevation_inventory_sha256']==digest(by_view[match['elevation_view_id']])
            assert not match['physical_correspondence_verified'] and not match['position_alignment_verified']
        checked['independent_nominal_width_links'] += len(observed)
    building_links = json.loads((root/report['building_facade_links']['file']).read_text())
    assert automatic_building_scope.link(inspected_views,opening_links,max_checks=report['contract']['options']['max_checks'])==building_links
    width_lookup = {w['id']: w for w in opening_links['matches']}
    records = {r['id']: r for r in building_links['frames']}
    projection_lookup = {p['id']: p for p in building_links['projected_gaps']}
    for record in records.values():
        plan = by_view[record['plan_view_id']]
        reference = next(r for r in plan['drawing_reference_review']['plan_references']['references'] if digest(r)==record['source_reference_sha256'])
        assert digest(reference) in plan['drawing_reference_review']['whole_view_reference_sha256']
        assert reference['target_view_key_candidate']==record['target_view_key_candidate']
        label = next(l for l in plan['building_scope_review']['labels'] if l['id']==record['label_id'])
        candidate = next(c for c in label['candidates'] if c['id']==record['enclosure_id'])
        polygon = shape(candidate['geometry_pdf_native'])
        for frame in record['frame_review']['frames']:
            coords = list(polygon.exterior.coords); i = frame['boundary_segment_index']
            assert digest(frame['source_native_endpoints'])==digest([list(coords[i]),list(coords[i+1])])
            checked['original_named_facade_segments'] += 1
        checked['numbered_marker_enclosure_reviews'] += 1
    expected = set()
    for projection in projection_lookup.values():
        record = records[projection['facade_record_id']]
        frame = next(f for f in record['frame_review']['frames'] if f['id']==projection['frame_id'])
        plan = by_view[projection['plan_view_id']]
        gap = next(g for g in plan['plan_gap_review']['gaps'] if g['id']==projection['source_gap_id'])
        axis = frame['diagnostic_axis']; factor = plan['nominal_metres_per_pdf_point']
        expected_interval = sorted(sum(p[i]*axis[i] for i in (0,1))*factor-frame['projection_min_m'] for p in gap['gap_endpoints_pdf_native'])
        assert expected_interval==projection['nominal_plan_position_interval_m']
        assert projection['maximum_gap_plane_offset_nominal_m']<=.25 and not projection['position_alignment_verified']
        for width in width_lookup.values():
            if (width['plan_view_id']==projection['plan_view_id'] and width['source_gap_id']==projection['source_gap_id']
                    and width['elevation_view_id'] in record['target_elevation_view_ids']):
                expected.add((projection['id'],width['id']))
        checked['nominal_plan_gap_projections'] += 1
    observed = {(r['projection_id'],r['source_width_link_id']) for r in building_links['width_links']}
    assert observed==expected and len(observed)==len(building_links['width_links'])
    for link in building_links['width_links']:
        assert digest(width_lookup[link['source_width_link_id']])==link['source_width_link_sha256']
        assert not link['physical_correspondence_verified'] and not link['position_alignment_verified']
    checked['independent_reference_scoped_width_links'] += len(observed)
    if baseline is not None and 'building_facade_links' in baseline_report:
        old_buildings=json.loads((baseline/baseline_report['building_facade_links']['file']).read_text())
        old_widths=json.loads((baseline/baseline_report['opening_links']['file']).read_text())
        def semantic_pairs(buildings,widths):
            lookup={w['id']:w for w in widths['matches']}; projections={p['id']:p for p in buildings['projected_gaps']}
            return sorted((lookup[w['source_width_link_id']]['plan_view_id'],lookup[w['source_width_link_id']]['source_gap_id'],
                w['elevation_view_id'],lookup[w['source_width_link_id']]['consensus_family_index'],
                tuple(projections[w['projection_id']]['nominal_plan_position_interval_m'])) for w in buildings['width_links'])
        assert semantic_pairs(old_buildings,old_widths)==semantic_pairs(building_links,opening_links)
        baseline_comparison['reference_scoped_width_pairs_preserved']=len(building_links['width_links'])
    levels=json.loads((root/report['elevation_level_context']['file']).read_text())
    corpus=Corpus(work/'corpus')
    try:verify_elevation_context(corpus,source['pages'],inspected_views,building_links,levels,checked,report['contract']['options']['max_checks'])
    finally:corpus.close()
    if baseline is not None and 'elevation_level_context' in baseline_report:
        old_levels=json.loads((baseline/baseline_report['elevation_level_context']['file']).read_text())
        def semantic_levels(context,buildings):
            projections={p['id']:p for p in buildings['projected_gaps']}
            families={f['id']:f for v in context['views'] for f in v['families']}
            return sorted((p['plan_view_id'],p['source_gap_id'],w['elevation_view_id'],families[w['family_review_id']]['consensus_family_index'])
                for w in context['level_supported_width_links'] for p in [projections[w['projection_id']]])
        assert semantic_levels(old_levels,old_buildings)==semantic_levels(levels,building_links)
        baseline_comparison['level_supported_width_pairs_preserved']=len(levels['level_supported_width_links'])
    alignment=json.loads((root/report['facade_alignment']['file']).read_text())
    verify_facade_alignment(source['pages'],inspected_views,building_links,levels,alignment,checked,report['contract']['options']['max_checks'])
    if baseline is not None and 'facade_alignment' in baseline_report:
        old_alignment=json.loads((baseline/baseline_report['facade_alignment']['file']).read_text())
        def semantic_extents(value):
            return sorted((r['frame_id'],e['source_kind'],e['source_id'],c['nominal_plan_width_m'],c['status'],
                tuple(w['nominal_elevation_width_m'] for w in c['witnesses']))
                for row in value['frames'] for r in row['frame_reviews'] for c in r['extent_comparisons']
                for e in r['plan_extents'] if e['id']==c['plan_extent_id'])
        assert semantic_extents(old_alignment)==semantic_extents(alignment)
        baseline_comparison['raw_facade_extent_comparisons_preserved']=len(semantic_extents(alignment))
    scale=json.loads((root/report['sheet_scale_evidence']['file']).read_text())
    corpus=Corpus(work/'corpus')
    try:verify_sheet_scale(corpus,source['pages'],inspected_views,building_links,levels,alignment,scale,checked,report['contract']['options']['max_checks'])
    finally:corpus.close()
    if baseline is not None and 'sheet_scale_evidence' in baseline_report:
        old_scale=json.loads((baseline/baseline_report['sheet_scale_evidence']['file']).read_text())
        assert sorted(p['layout_fit']['apparent_subject_layout_scale'] for p in old_scale['pairs'] if p['layout_fit'])==sorted(p['layout_fit']['apparent_subject_layout_scale'] for p in scale['pairs'] if p['layout_fit'])
        assert sorted(c['nominal_plan_width_m'] for d in old_scale['diagnostics'] for c in d['width_comparisons'])==sorted(c['nominal_plan_width_m'] for d in scale['diagnostics'] for c in d['width_comparisons'])
        baseline_comparison['prior_sheet_layout_diagnostics_preserved']=True
    returns=json.loads((root/report['wall_return_corners']['file']).read_text())
    verify_wall_returns(source['pages'],inspected_views,building_links,levels,alignment,scale,returns,checked,report['contract']['options']['max_checks'])
    if baseline is not None and 'wall_return_corners' in baseline_report:
        old_returns=json.loads((baseline/baseline_report['wall_return_corners']['file']).read_text())
        def semantic_return_positions(value):
            return sorted((tuple(map(tuple,d['source_points_pdf_native'])),p['elevation_x_reversed'],p['status'],
                tuple(w['maximum_endpoint_residual_m'] for w in p['witnesses']))
                for d in value['diagnostics'] for p in d['position_comparisons'])
        assert old_returns['counts']==returns['counts']
        assert semantic_return_positions(old_returns)==semantic_return_positions(returns)
        baseline_comparison['prior_wall_return_position_comparisons_preserved']=len(semantic_return_positions(returns))
    symbols=json.loads((root/report['door_symbol_evidence']['file']).read_text())
    corpus=Corpus(work/'corpus')
    try:verify_door_symbols(corpus,source['pages'],inspected_views,returns,symbols,checked,report['contract']['options']['max_checks'])
    finally:corpus.close()
    if baseline is not None and 'door_symbol_evidence' in baseline_report:
        old_symbols=json.loads((baseline/baseline_report['door_symbol_evidence']['file']).read_text())
        assert old_symbols['counts']==symbols['counts']
        assert digest([p['edges'] for p in old_symbols['pages']])==digest([p['edges'] for p in symbols['pages']])
        assert digest([v['gaps'] for v in old_symbols['views']])==digest([v['gaps'] for v in symbols['views']])
        def semantic_symbol_links(value):
            return sorted((l['source_gap_sha256'],l['status'],tuple(sorted((s['plan_view_id'],s['symbol_id']) for s in l['symbol_candidates'])))
                for l in value['conditional_position_links'])
        assert semantic_symbol_links(old_symbols)==semantic_symbol_links(symbols)
        baseline_comparison['prior_original_door_symbols_preserved']=symbols['counts']['symbol_candidates']
        baseline_comparison['prior_symbol_position_links_preserved']=len(symbols['conditional_position_links'])
    artwork=json.loads((root/report['artwork_scale_controls']['file']).read_text())
    corpus=Corpus(work/'corpus')
    try:verify_artwork_controls(corpus,source['pages'],inspected_views,building_links,levels,scale,returns,artwork,checked,report['contract']['options']['max_checks'])
    finally:corpus.close()
    result = {'version': 'automatic-view-component-audit-v9', 'status': 'passed',
        'job_sha256': file_hash(job), 'source_contract': report['contract'], 'views': rows, 'counts': report['counts'],
        'checked': dict(checked), 'fresh_replay_artifact_hashes_identical': len(report['output_sha256']),
        'inventory_status': report['status'], 'withheld_passes': report['withheld_passes'],
        'opening_links': report['opening_links'],
        'building_facade_links': report['building_facade_links'],
        'elevation_level_context': report['elevation_level_context'],
        'facade_alignment': report['facade_alignment'],
        'sheet_scale_evidence': report['sheet_scale_evidence'],
        'wall_return_corners': report['wall_return_corners'],
        'door_symbol_evidence': report['door_symbol_evidence'],
        'artwork_scale_controls': report['artwork_scale_controls'],
        'baseline_comparison': baseline_comparison,
        'all_requested_passes_completed': report['all_requested_passes_completed'],
        'output_sha256': report['output_sha256'], 'world_geometry_additions': 0, 'accepted_physical_components': 0,
        'training_labels_generated': 0, 'scope': 'Unseeded source evidence; no selected physical boundary, aperture or park placement.'}
    atomic_json(output, result)
    print(json.dumps({'status': result['status'], 'views': len(rows), 'counts': result['counts'], 'checked': result['checked']}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, help='Optional prior component pack for native/raw preservation checks')
    args = parser.parse_args(); audit(args.job, args.output, args.baseline)
