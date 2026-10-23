"""Original site-plan primitives and all fixed-scale compound-roof registrations."""
import math

import numpy as np
import pymupdf

from .drawing_page_tools import native_inverse
from .reconstruction_evidence_queue import digest

VERSION = 'original-site-compound-roof-correspondence-v1'
TOLERANCE_M = .1
CONTEXT_MARGIN_PDF_POINTS = 350


def primitive_edges(item):
    """Explicit straight item edges only; no implicit closing line or curve fit."""
    if item[0]=='l':
        return [(0,[list(item[1]),list(item[2])])]
    if item[0]=='qu':
        q=item[1];points=[q[0],q[1],q[3],q[2]]
    elif item[0]=='re':
        r=pymupdf.Rect(item[1]);points=[r.tl,r.tr,r.br,r.bl]
    else:
        return []
    return [(i,[list(points[i]),list(points[(i+1)%4])]) for i in range(4)]


def original_lines(page,sha,words,unit,charge):
    if not math.isfinite(unit) or unit<=0:raise ValueError('Positive original site scale required')
    if len(words)>16:raise OverflowError('site_context_word_budget')
    regions={w['id']:pymupdf.Rect(w['source_bbox_pdf_unrotated'])+(-350,-350,350,350)
             for w in words if w['status']=='source_numeric_glyph_candidate'}
    matrix=native_inverse(page);paths=page.get_cdrawings(extended=True)
    if len(paths)>150000:raise OverflowError('site_original_path_budget')
    result=[]
    for pi,path in enumerate(paths):
        charge()
        if (path['type'] not in ('s','fs') or path.get('layer') or path.get('stroke_opacity')!=1
                or path.get('dashes')!='[] 0'):continue
        box=pymupdf.Rect(path['rect'])
        if not any(box.intersects(r) for r in regions.values()):continue
        if len(path['items'])>10000:raise OverflowError('site_original_item_budget')
        for ii,item in enumerate(path['items']):
            charge()
            for ei,points in primitive_edges(item):
                charge()
                if not np.isfinite(points).all():raise ValueError('Finite original site endpoints required')
                memberships=[wid for wid,r in regions.items() if all(r.contains(pymupdf.Point(p)) for p in points)]
                length=math.dist(*points)
                if not memberships or not 1<=length*unit<=40:continue
                native=[list(pymupdf.Point(p)*matrix) for p in points]
                row={'document_sha256':sha,'page':page.number+1,'path_index':pi,'item_index':ii,
                     'original_primitive':item[0],'original_primitive_edge_index':ei,
                     'path_record_sha256':digest(path),'source_endpoints_pdf_unrotated':points,
                     'source_endpoints_pdf_native':native,'color_rgb':list(path['color']),
                     'stroke_width_pdf_points':path['width'],'paint_seqno':path['seqno'],
                     'context_word_ids':memberships,'source_line_clipped_or_extended':False,
                     'implicit_closing_edge_invented':False}
                row['id']=digest([VERSION,row]);row['source_component_id']=row['id'];result.append(row)
                if len(result)>4096:raise OverflowError('site_local_line_budget')
    return sorted(result,key=lambda l:l['source_component_id'])


def registrations(source,target,source_unit,target_unit,ridge,lines,charge):
    """All D4 mappings, fixed original scales and apex/one-edge anchor only."""
    a=np.array(source['source_corners_pdf_native'],float);b=np.array(target['source_corners_pdf_native'],float)
    A=np.array(source['source_apex_pdf_native'],float);B=np.array(target['source_apex_pdf_native'],float)
    ridge_points=np.array(ridge['source_endpoints_pdf_native'],float)
    if (a.shape!=(4,2) or b.shape!=(4,2) or A.shape!=(2,) or B.shape!=(2,) or ridge_points.shape!=(2,2)
            or not all(np.isfinite(p).all() for p in (a,b,A,B,ridge_points))
            or not all(math.isfinite(u) and u>0 for u in (source_unit,target_unit))):
        raise ValueError('Finite original four-corner plans, whole ridge and positive source scales required')
    def basis(points):
        edges=np.roll(points,-1,axis=0)-points;lengths=np.linalg.norm(edges,axis=1)
        if min(lengths)<=0:raise ValueError('Nonzero original plan edges required')
        area=sum(np.cross(points[i],points[(i+1)%4]).item() for i in range(4))
        if area==0:raise ValueError('Nondegenerate original plan required')
        return edges/lengths[:,None],1 if area>0 else -1
    av,aw=basis(a);bv,bw=basis(b);axis=av[0];normal=np.array([-axis[1],axis[0]])
    rows=[]
    for start in range(4):
        for direction in (-1,1):
            charge();mapping=[(start+direction*i)%4 for i in range(4)]
            edge=b[mapping[1]]-b[mapping[0]];u=edge/np.linalg.norm(edge)
            v=np.array([-u[1],u[0]])*(direction*bw/aw)
            rotation=np.outer(u,axis)+np.outer(v,normal)
            scale=source_unit/target_unit
            projected=B+(a-A)@rotation.T*scale;predicted_ridge=B+(ridge_points-A)@rotation.T*scale
            residuals=(projected-b[mapping])*target_unit
            comparisons=[]
            for line in lines:
                charge();ends=np.array(line['source_endpoints_pdf_native'])
                for order in ([0,1],[1,0]):
                    vectors=(predicted_ridge-ends[order])*target_unit
                    errors=np.linalg.norm(vectors,axis=1)
                    comparisons.append({'site_source_line_id':line['id'],'original_site_endpoint_order':order,
                        'endpoint_residual_vectors_nominal_m':vectors.tolist(),'maximum_endpoint_residual_nominal_m':float(max(errors)),
                        'whole_ridge_endpoints_compatible':bool(max(errors)<=TOLERANCE_M)})
            row={'architectural_plan_candidate_id':source['id'],'site_plan_candidate_id':target['id'],
                 'original_architectural_ridge_source_id':ridge['source_component_id'],
                 'architectural_to_site_corner_indices':mapping,'orthogonal_matrix':rotation.tolist(),
                 'matrix_determinant':float(np.linalg.det(rotation)),'reflection_candidate':bool(np.linalg.det(rotation)<0),
                 'original_architectural_apex_anchor_pdf_native':A.tolist(),'original_site_apex_anchor_pdf_native':B.tolist(),
                 'fixed_original_source_scale_ratio':scale,'predicted_site_corners_pdf_native':projected.tolist(),
                 'corner_residual_vectors_nominal_m':residuals.tolist(),
                 'maximum_corner_residual_nominal_m':float(max(np.linalg.norm(residuals,axis=1))),
                 'predicted_site_ridge_endpoints_pdf_native':predicted_ridge.tolist(),'ridge_comparisons':comparisons,
                 'tolerance_nominal_m':TOLERANCE_M,'original_source_coordinates_changed':False,
                 'scale_or_least_squares_translation_fitted':False,'best_residual_candidate_selected':False,
                 'physical_component_identity_verified':False,'geographic_registration_verified':False,
                 'world_export_authorized':False}
            row['id']=digest([VERSION,row]);rows.append(row)
    return rows


def support(rows,site_candidates,pixels):
    supported={p['line_id'] for p in pixels if p['all_samples_supported']};result=[]
    for row in rows:
        candidate=next(c for c in site_candidates if c['id']==row['site_plan_candidate_id'])
        groups=candidate['source_perimeter_ids_per_edge']+candidate['source_spoke_ids_per_corner']
        # Duplicate paints remain independent witnesses; every geometric edge
        # needs at least one sampled original paint, without deleting failures.
        roof_supported=all(any(sid in supported for sid in group) for group in groups)
        matches=[c for c in row['ridge_comparisons'] if c['whole_ridge_endpoints_compatible'] and c['site_source_line_id'] in supported]
        good=roof_supported and row['maximum_corner_residual_nominal_m']<=TOLERANCE_M and bool(matches)
        result.append({'registration_id':row['id'],'status':'conditional_compound_roof_registration_supported' if good else 'site_roof_registration_held',
            'site_roof_original_pixel_support':roof_supported,'supported_whole_ridge_matches':matches,
            'reflection_candidate':row['reflection_candidate'],'physical_component_identity_verified':False,
            'geographic_registration_verified':False,'world_export_authorized':False})
    return result
