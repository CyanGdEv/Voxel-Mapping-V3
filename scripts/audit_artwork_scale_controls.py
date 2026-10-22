"""Independent original reference, similarity coefficient and holdout checks."""
import math

import numpy as np
import pymupdf
from shapely.geometry import LineString, MultiPoint, shape

from voxel_mapper import automatic_artwork_controls
from voxel_mapper.drawing_page_tools import native_inverse
from voxel_mapper.glyph_visibility import screen_architectural_span
from voxel_mapper.reconstruction_evidence_queue import digest


def verify(corpus, source_pages, inventories, buildings, levels, scale, returns, evidence, checked, max_checks):
    fresh=automatic_artwork_controls.run(corpus,source_pages,inventories,buildings,levels,scale,returns,max_checks=max_checks)
    assert digest(fresh)==digest(evidence)
    assert not evidence['physical_scale_verified'] and not evidence['target_artwork_application_verified']
    assert evidence['world_geometry_additions']==evidence['training_labels_generated']==0
    if evidence['status']!='independent_non_target_artwork_controls_only':return
    pages={};markers={}
    for source in evidence['pages']:
        key=(source['document_sha256'],source['page']);pages[key]=source
        with pymupdf.open(corpus.root/'files'/(key[0]+'.pdf')) as document:
            page=document[key[1]-1];paths=page.get_drawings();traces=page.get_texttrace();matrix=native_inverse(page)
            assert list(matrix)==source['unrotated_mupdf_to_pdf_native_matrix']
            for marker in source['markers']:
                path=paths[marker['source_circle_path_index']]
                assert path['type']=='s' and path['seqno']==marker['source_circle_paint_seqno']
                assert marker['circle_source_beziers']==[[list(p) for p in item[1:]] for item in path['items']]
                assert list(path['rect'])==marker['circle_bbox_page_points']
                rect=path['rect'];center=(rect.tl+rect.br)*.5
                assert list(center*matrix)==marker['center_pdf_native']
                assert (rect.width+rect.height)/4==marker['radius_page_points']
                inside=traces[marker['sheet_trace_index']]
                if marker['key'] is not None:
                    outside=traces[marker['outside_trace_indices'][0]]
                    assert marker['key'][1:]==[int(''.join(chr(c[0]) for c in t['chars']).strip()) for t in (inside,outside)]
                    for span,receipt in zip((inside,outside),marker['glyph_screens']):
                        assert digest(screen_architectural_span(page,span))==digest(receipt)
                        checked['original_artwork_reference_glyphs']+=1
                markers[marker['id']]=marker;checked['original_artwork_circles']+=1
    families={f['id']:f for v in levels['views'] for f in v['families']};level_views={v['view_id']:v for v in levels['views']}
    records={r['id']:r for r in buildings['frames']};lookup={v['view_id']:v for v in inventories}
    for pair in evidence['pairs']:
        for row in pair['controls']:
            assert row['key'][:2] not in evidence['excluded_target_sheet_keys']
            for field in ('subject','reference'):
                originals=[markers[i] for i in row[field+'_marker_ids']]
                assert all(m['key']==row['key'] and m['status']=='original_numbered_artwork_reference_candidate' for m in originals)
                assert all(m['center_pdf_native']==row[field+'_center'] for m in originals)
                assert row[field+'_fonts']==originals[0]['font_sizes_points']
                assert row[field+'_radii']==[m['radius_page_points'] for m in originals]
            checked['independent_artwork_controls']+=1
        if pair['status']!='supported_non_target_artwork_layout_only':continue
        ordered=sorted(pair['controls'],key=lambda r:tuple(r['key']))
        assert [r['role'] for r in ordered]==['holdout' if i%2==0 else 'fit' for i in range(len(ordered))]
        fit=[r for r in ordered if r['role']=='fit'];holdouts=[r for r in ordered if r['role']=='holdout']
        assert len(fit)>=2 and len(holdouts)>=3 and len({tuple(r['key'][:2]) for r in ordered})>=2
        design=[];target=[]
        for row in fit:
            x,y=row['reference_center'];sx,sy=row['subject_center']
            design.extend([[x,-y,1,0],[y,x,0,1]]);target.extend([sx,sy])
        coefficients=np.linalg.lstsq(np.asarray(design),np.asarray(target),rcond=None)[0]
        a,b,tx,ty=coefficients;matrix=np.asarray([[a,b],[-b,a]]);translation=np.asarray([tx,ty])
        assert np.allclose(matrix,pair['reference_to_subject_linear_row_matrix'],atol=1e-9,rtol=1e-10)
        assert np.allclose(translation,pair['reference_to_subject_translation'],atol=1e-8,rtol=1e-10)
        assert abs(math.hypot(a,b)-pair['apparent_subject_artwork_scale'])<1e-9
        for row in ordered:
            error=float(np.linalg.norm(np.asarray(row['reference_center'])@matrix+translation-row['subject_center']))
            assert abs(error-row['residual_pdf_points'])<1e-8 and error<=.25
            ratios=[s/r for s,r in zip(row['subject_fonts'],row['reference_fonts'])]
            ratios.extend(s/r for s in row['subject_radii'] for r in row['reference_radii'])
            assert all(abs(r/pair['apparent_subject_artwork_scale']-1)<=.015 for r in ratios)
            checked['independent_artwork_holdouts' if row['role']=='holdout' else 'independent_artwork_fit_controls']+=1
        hull=MultiPoint([r['subject_center'] for r in fit]).convex_hull
        all_hull=MultiPoint([r['subject_center'] for r in ordered]).convex_hull
        assert hull.equals(shape(pair['fit_control_hull_pdf_native'])) and all_hull.equals(shape(pair['all_control_hull_pdf_native']))
        inverse=np.linalg.inv(np.asarray(pair['reference_to_subject_linear_row_matrix']))
        for d in evidence['diagnostics']:
            if d['pair_id']!=pair['id']:continue
            original=next(r for r in returns['diagnostics'] if digest(r)==d['source_return_diagnostic_sha256'])
            assert original['source_points_pdf_native']==d['source_points_pdf_native']
            axis=np.asarray(d['source_axis_pdf_native'])@inverse;axis/=np.linalg.norm(axis)
            span=abs(float((np.asarray(d['source_points_pdf_native'][1])-d['source_points_pdf_native'][0])@inverse@axis))*d['nominal_metres_per_pdf_point']
            assert abs(span-d['nominal_span_m'])<1e-9
            line=LineString(d['source_points_pdf_native'])
            assert d['outside_fit_control_hull']==(not hull.covers(line))
            assert d['outside_all_control_hull']==(not all_hull.covers(line))
            assert not d['target_artwork_application_verified'] and not d['source_geometry_changed']
            target=records[original['facade_record_id']]['target_elevation_view_ids'][0]
            for comparison in d['width_comparisons']:
                parent=families[comparison['parent_family_review_id']]
                for source,witness in zip(parent['witnesses'],comparison['witnesses']):
                    width=(source['source_bounds_pixels'][2]-source['source_bounds_pixels'][0])*level_views[target]['pixel_edge_to_source_display_matrix'][0]*lookup[target]['nominal_metres_per_pdf_point']
                    assert width==witness['nominal_elevation_width_m']
                    assert abs((width-span)-witness['elevation_minus_plan_width_m'])<1e-9
                    assert witness['within_discovery_tolerance']==(abs(width-span)<=.25)
                    checked['independent_artwork_extent_witnesses']+=1
            checked['independent_artwork_corner_spans']+=1
