"""Held-out printed furniture correspondence; never a physical scale correction."""
import math

import numpy as np
import pymupdf
from shapely.geometry import Polygon, box, mapping

from .building_spec import digest
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span, VERSION as GLYPH_VERSION

VERSION='source-sheet-layout-audit-v1'


def anchors(page,sha,number,terms,bounds):
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:
        raise ValueError('Sheet furniture text budget exceeded')
    inverse=native_inverse(page);scope=box(*bounds);rows={term:[] for term in terms}
    frame=page.rect*page.derotation_matrix*inverse
    if not box(*frame).covers(scope):raise ValueError('Furniture bounds outside original page')
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        if text not in rows:continue
        rect=pymupdf.Rect(run['bbox']);points=[pymupdf.Point(p)*inverse for p in (rect.tl,rect.tr,rect.br,rect.bl)]
        polygon=Polygon([(p.x,p.y) for p in points]);origin=pymupdf.Point(run['chars'][0][2])*inverse
        row={'document_sha256':sha,'page':number,'text':text,'origin_pdf_native':[origin.x,origin.y],
            'label_geometry':mapping(polygon),'trace_indices':run['trace_indices'],
            'character_indices':run['character_indices'],'font_size_points':run['size'],
            'within_declared_furniture_scope':scope.covers(polygon),
            'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
        row['id']=digest(row);rows[text].append(row)
        if sum(len(r) for r in rows.values())>256:raise ValueError('Furniture occurrence budget exceeded')
    return rows


def fit(subject,reference,terms):
    """Fit reference -> subject from declared fit terms, then test held-out terms."""
    result={'version':VERSION,'glyph_version':GLYPH_VERSION,'status':'withheld_layout_correspondence',
        'rows':[],'geometry_correction_applied':False,'physical_scale_verified':False,
        'component_scale_application_verified':False,'geographic_registration_verified':False,
        'world_geometry_additions':0}
    if not isinstance(terms,list) or not 12<=len(terms)<=64:
        raise ValueError('At least eight fit and four holdout furniture terms required')
    names=[]
    for term in terms:
        if (not isinstance(term,dict) or set(term)!={'text','role'} or term['role'] not in ('fit','holdout')
                or not isinstance(term['text'],str) or not term['text'].strip() or len(term['text'])>256):
            raise ValueError('Literal bounded fit/holdout furniture terms required')
        names.append(term['text'])
    if len(set(names))!=len(names) or sum(t['role']=='fit' for t in terms)<8 or sum(t['role']=='holdout' for t in terms)<4:
        raise ValueError('Distinct predeclared furniture fit and holdout terms required')
    for term in terms:
        a=subject.get(term['text'],[]);b=reference.get(term['text'],[])
        row={**term,'subject_occurrences':a,'reference_occurrences':b,'usable':False}
        if len(a)==len(b)==1 and all(r['within_declared_furniture_scope'] and
                r['glyph_screen']['status']=='raster_consistent_candidate' for r in (a[0],b[0])):
            row.update(usable=True,subject_origin=a[0]['origin_pdf_native'],reference_origin=b[0]['origin_pdf_native'])
        result['rows'].append(row)
    if not all(r['usable'] for r in result['rows']):
        result['reason']='Missing, duplicated, hidden or out-of-scope predeclared furniture anchor';return result
    train=[r for r in result['rows'] if r['role']=='fit'];check=[r for r in result['rows'] if r['role']=='holdout']
    x=np.array([r['reference_origin'] for r in train]);y=np.array([r['subject_origin'] for r in train])
    center=x.mean(axis=0);design=np.c_[x-center,np.ones(len(x))]
    if np.linalg.matrix_rank(design)!=3:
        result['reason']='Collinear furniture fit anchors';return result
    fitted,_,_,_=np.linalg.lstsq(design,y,rcond=None)
    linear=fitted[:2];translation=fitted[2]-center@linear
    determinant=float(np.linalg.det(linear));singular=np.linalg.svd(linear,compute_uv=False)
    result.update(reference_to_subject_linear_row_matrix=linear.tolist(),
        reference_to_subject_translation=translation.tolist(),linear_singular_values=singular.tolist(),
        determinant=determinant,fit_anchor_count=len(train),holdout_anchor_count=len(check))
    if determinant<=0 or not .5<=min(singular)<=max(singular)<=2 or max(singular)/min(singular)>1.05:
        result['reason']='Unsupported reflection, reduction or anisotropic furniture correspondence';return result
    inverse=np.linalg.inv(linear)
    residuals=[]
    for row in result['rows']:
        residual=float(np.linalg.norm(np.array(row['reference_origin'])@linear+translation-np.array(row['subject_origin'])))
        row['residual_pdf_points']=residual;residuals.append(residual)
        a=row['subject_occurrences'][0];b=row['reference_occurrences'][0]
        row['observed_font_size_ratio']=a['font_size_points']/b['font_size_points']
    fit_max=max(r['residual_pdf_points'] for r in train);holdout_max=max(r['residual_pdf_points'] for r in check)
    result.update(fit_max_residual_pdf_points=fit_max,holdout_max_residual_pdf_points=holdout_max,
        subject_to_reference_linear_row_matrix=inverse.tolist(),
        subject_to_reference_translation=(-translation@inverse).tolist(),
        anchor_scope_bounds={'reference':box(*Polygon(x).bounds).__geo_interface__,
            'subject':box(*Polygon(y).bounds).__geo_interface__},
        recipe={'maximum_fit_and_holdout_residual_pdf_points':.25,
            'maximum_font_ratio_departure_fraction':.015,'maximum_anisotropy_ratio':1.05,
            'linear_scale_range':[.5,2],'fit_selection':'all predeclared fit terms; no outlier removal'})
    if max(fit_max,holdout_max)>.25:
        result['reason']='Predeclared furniture fit or held-out anchors disagree';return result
    geometric_scale=float(np.sqrt(determinant))
    if any(abs(r['observed_font_size_ratio']/geometric_scale-1)>.015 for r in result['rows']):
        result['reason']='Original font sizes disagree with the furniture coordinate reduction';return result
    result.update(status='supported_furniture_layout_correspondence_only',
        apparent_subject_layout_scale=geometric_scale,
        limitations=['Printed page furniture and held-out labels support a layout relation, not physical drawing scale.',
            'Artwork outside the furniture anchor region requires extrapolation; local viewport scaling may differ.',
            'No building dimension, manual corner trace, historical normalization or elevation-fit target participates in this fit.',
            'The inverse transform is diagnostic only; original source geometry and printed-scale measurements are not changed.'])
    return result


def diagnostic_lengths(edges,layout,nominal_unit,target_width,*,tolerance_m=.25):
    """Keep both raw and inverse-layout length hypotheses; never transform geometry."""
    if len(edges)>20000 or type(target_width) not in (int,float) or not math.isfinite(target_width) or target_width<=0:
        raise ValueError('Bounded source edges and positive target width required')
    if not math.isfinite(nominal_unit) or nominal_unit<=0 or not 0<tolerance_m<=.25:
        raise ValueError('Positive nominal scale and bounded diagnostic tolerance required')
    if layout['status']!='supported_furniture_layout_correspondence_only':return []
    inverse=np.array(layout['subject_to_reference_linear_row_matrix']);matches=[]
    for edge in edges:
        if edge['coordinate_frame']!='unrotated_mupdf_points_y_down':raise ValueError('Original source edge coordinate frame required')
        a,b=edge['points'];delta=np.array([b[0]-a[0],-(b[1]-a[1])])
        # Both layouts use native Y up. Translation never enters a length.
        raw=float(np.linalg.norm(delta)*nominal_unit)
        corrected=float(np.linalg.norm(delta@inverse)*nominal_unit)
        if abs(corrected-target_width)<=tolerance_m:
            matches.append({'source_edge_id':edge['id'],'raw_nominal_length_m':raw,
                'inverse_layout_nominal_length_candidate_m':corrected,'target_width_m':target_width,
                'raw_residual_m':raw-target_width,'diagnostic_residual_m':corrected-target_width,
                'geometry_correction_applied':False,'physical_correspondence_verified':False,
                'layout_application_verified':False})
            if len(matches)>512:raise ValueError('Diagnostic dimensional candidate budget exceeded')
    return sorted(matches,key=lambda r:r['source_edge_id'])
