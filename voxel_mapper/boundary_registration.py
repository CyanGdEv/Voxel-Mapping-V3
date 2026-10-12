"""Boundary/corner similarity hypotheses, separate from independent registration review."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,shape
from shapely.geometry.polygon import orient

from .footprint_matching import references,lines,NativeNames,descriptor

VERSION='boundary-registration-v1'


def corners(polygon):
    """Simplified exterior vertices for fitting only; original geometry is retained."""
    simplified=polygon.simplify(math.sqrt(polygon.area)*.002,preserve_topology=True)
    points=np.asarray(orient(simplified,sign=1).exterior.coords[:-1],dtype=float)
    if len(points)>64:return None
    selected=[]
    for i,p in enumerate(points):
        a=p-points[i-1];b=points[(i+1)%len(points)]-p
        denominator=np.linalg.norm(a)*np.linalg.norm(b)
        if denominator and math.degrees(math.acos(float(np.clip(np.dot(a,b)/denominator,-1,1))))>=20:selected.append(p)
    return np.asarray(selected) if len(selected)>=3 else None


def samples(polygon,count=32):
    ring=orient(polygon,sign=1).exterior
    return np.asarray([ring.interpolate(i*ring.length/count).coords[0] for i in range(count)])


def similarity(local,target):
    a=local[:,0]+1j*local[:,1];b=target[:,0]+1j*target[:,1]
    ac=a-a.mean();bc=b-b.mean();denominator=np.vdot(ac,ac).real
    if denominator<=0:raise ValueError('Degenerate boundary sample')
    coefficient=np.vdot(ac,bc)/denominator;offset=b.mean()-coefficient*a.mean()
    scale=abs(coefficient)
    if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid boundary fit')
    matrix=[[coefficient.real,-coefficient.imag],[coefficient.imag,coefficient.real]]
    translation=[offset.real,offset.imag]
    rms=float(np.sqrt(np.mean(np.abs(coefficient*a+offset-b)**2)))
    return matrix,translation,scale,rms


def fit_boundary(local,reference,*,scale_denominators=()):
    descriptor(local);descriptor(reference)
    if local.geom_type!='Polygon' or reference.geom_type!='Polygon':return {'status':'withheld','reason':'Multipart correspondence requires component review','registration_verified':False}
    if len(local.interiors)!=len(reference.interiors):return {'status':'withheld','reason':'Hole topology mismatch','registration_verified':False}
    if len(local.exterior.coords)>10000 or len(reference.exterior.coords)>10000:return {'status':'withheld','reason':'Boundary vertex budget exceeded','registration_verified':False}
    local_corners=corners(local);reference_corners=corners(reference);pairs=[('boundary_samples',samples(local),samples(reference))]
    if local_corners is not None and reference_corners is not None and len(local_corners)==len(reference_corners):pairs.append(('corner_vertices',local_corners,reference_corners))
    fits=[]
    for method,a,b in pairs:
        for shift in range(len(b)):
            target=np.roll(b,shift,axis=0)
            try:matrix,translation,scale,rms=similarity(a,target)
            except ValueError:continue
            fits.append((rms/math.sqrt(reference.area),method,matrix,translation,scale,rms,a,target))
    fits.sort(key=lambda r:r[0]);unique=[]
    for fit in fits:
        if any(np.allclose(fit[2],r[2],rtol=0,atol=fit[4]*1e-5) and np.allclose(fit[3],r[3],rtol=0,atol=1e-5) for r in unique):continue
        unique.append(fit)
        if len(unique)>=12:break
    evaluated=[]
    for _,method,matrix,translation,scale,rms,a,b in unique:
        placed=affine_transform(local,[matrix[0][0],matrix[0][1],matrix[1][0],matrix[1][1],*translation])
        iou=placed.intersection(reference).area/placed.union(reference).area
        error=placed.boundary.hausdorff_distance(reference.boundary)
        evaluated.append({'method':method,'matrix':matrix,'translation_m':translation,'scale_metres_per_pdf_point':scale,'rotation_degrees':math.degrees(math.atan2(matrix[1][0],matrix[0][0])),'sample_rms_m':rms,'intersection_over_union':iou,'boundary_hausdorff_m':error,'boundary_error_fraction':error/math.sqrt(reference.area),'corner_pairs':[{'local':p.tolist(),'target':q.tolist(),'identity_verified':False} for p,q in zip(a,b)] if method=='corner_vertices' else []})
    evaluated.sort(key=lambda r:(-r['intersection_over_union'],r['boundary_error_fraction']));best=evaluated[0]
    equivalent=[r for r in evaluated if r['intersection_over_union']>=best['intersection_over_union']-.005 and r['boundary_error_fraction']<=best['boundary_error_fraction']+.005]
    scales=sorted({int(v) for v in scale_denominators if type(v)==int and 1<=v<=100000})
    if len(scales)>16:return {'status':'withheld','reason':'Printed scale candidate budget exceeded','registration_verified':False}
    comparison=[{'denominator':v,'expected_metres_per_pdf_point':v*.0254/72,'relative_scale_error':abs(best['scale_metres_per_pdf_point']/(v*.0254/72)-1)} for v in scales]
    flags=[]
    if best['intersection_over_union']<.85 or best['boundary_error_fraction']>.05:flags.append('poor_boundary_agreement')
    if len(equivalent)>1:flags.append('ambiguous_boundary_orientation')
    if not comparison:flags.append('printed_scale_missing')
    elif min(r['relative_scale_error'] for r in comparison)>.02:flags.append('printed_scale_disagreement')
    elif len(comparison)>1:flags.append('printed_scale_ambiguous')
    return {'status':'boundary_hypothesis_only','best_fit':best,'equivalent_orientations':[{k:r[k] for k in ('matrix','translation_m','rotation_degrees','intersection_over_union')} for r in equivalent],'printed_scale_comparison':comparison,'review_flags':flags,'registration_verified':False,'independent_checkpoints':[],'world_geometry_additions':0}


def checked_registration(hypothesis,candidate,spec,page):
    """Recompute external checked controls; boundary self-fit is never a check."""
    from .drawing_batch import reviewed_alignment
    from .reconstruction.registration import apply_registration
    geometry=shape(candidate['geometry'])
    digest=hashlib.sha256((candidate['document_sha256']+'/'+str(candidate['page'])+'/'+geometry.normalize().wkb_hex).encode()).hexdigest()
    if digest!=candidate['id'] or candidate.get('coordinate_frame')!='pdf_native_points_y_up':raise ValueError('Native candidate identity/frame mismatch')
    for key in ('candidate_id','document_sha256','page','reference_id','reference_sha256','target_crs'):
        expected=candidate['id'] if key=='candidate_id' else candidate[key] if key in ('document_sha256','page') else hypothesis[key]
        if hypothesis.get(key)!=expected or spec.get(key)!=expected:raise ValueError('Review must bind exact boundary candidate, page, reference and target frame')
    excluded={candidate['document_sha256'],hypothesis['reference_sha256']}|{r.get('source_sha256') for r in spec['controls']}
    if any(r.get('source_sha256') in excluded for r in spec['checkpoints']):raise ValueError('Checkpoints need independently sourced evidence; boundary self-fit cannot verify itself')
    result=reviewed_alignment(spec,page)
    if result['status']!='accepted_horizontal_fit':return result
    points=np.asarray([p['local'] for p in result['control_pairs']+result['checkpoint_pairs']])
    checked=points@np.asarray(result['matrix']).T+result['translation_m']
    hypotheses=[hypothesis['best_fit']]+hypothesis.get('equivalent_orientations',[])
    error=min(float(np.linalg.norm(points@np.asarray(fit['matrix']).T+fit['translation_m']-checked,axis=1).max()) for fit in hypotheses)
    if error>result['tolerance_m']:return {'status':'withheld','reason':'Boundary fit disagrees with independently reviewed registration','max_disagreement_m':error}
    # The reviewed transform must also cover the entire original candidate.
    polygons=[geometry] if geometry.geom_type=='Polygon' else list(geometry.geoms)
    for polygon in polygons:
        apply_registration(list(polygon.exterior.coords),result)
        for ring in polygon.interiors:apply_registration(list(ring.coords),result)
    result.update(boundary_hypothesis_disagreement_m=error,candidate_id=candidate['id'],document_sha256=candidate['document_sha256'],page=candidate['page'])
    return result


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def run(candidates,matching_directory,reference_file,reference_crs,target_crs,output,corpus,*,max_fits=10000,registration_reviews=None):
    if type(max_fits)!=int or not 1<=max_fits<=100000:raise ValueError('Fit budget must be 1..100000')
    matching_directory=Path(matching_directory);receipt=json.loads((matching_directory/'matching-report.json').read_text());associations=matching_directory/'associations.jsonl'
    rows,refhash,_=references(reference_file,reference_crs,target_crs)
    if receipt['candidate_sha256']!=file_hash(candidates) or receipt['associations.jsonl_sha256']!=file_hash(associations) or receipt['reference_sha256']!=refhash or receipt['target_crs']!=target_crs or receipt['reference_crs']!=reference_crs:raise ValueError('Matching inputs or output changed')
    reviews=registration_reviews or []
    if not isinstance(reviews,list) or len(reviews)>10000:raise ValueError('Bounded registration review list required')
    review_index={}
    for review in reviews:
        key=(review['candidate_id'],review['reference_id'])
        if key in review_index:raise ValueError('Duplicate boundary registration review')
        review_index[key]=review
    used_reviews=set()
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh boundary output directory')
    output.mkdir(parents=True);references_by_id={r['id']:r for r in rows};names=NativeNames(corpus,rows);counts=Counter();attempted=0
    from .drawing_batch import SCALE
    page=None;scales=[]
    try:
        decisions=iter(lines(associations))
        with (output/'boundary-hypotheses.jsonl').open('w') as target:
            for candidate in lines(candidates):
                association=next(decisions,None)
                if association is None or association.get('candidate_id')!=candidate['id']:raise ValueError('Candidate/association ordering or identity changed')
                names.get(candidate) # Current retained extraction and PDF checksum.
                key=(candidate['document_sha256'],candidate['page'])
                if key!=page:
                    text=names.document[key[1]-1].get_text()
                    if len(text)>1000000:raise ValueError('Native scale text budget exceeded')
                    scales=sorted({int(v) for v in SCALE.findall(text) if 1<=int(v)<=100000});page=key
                for match in association['matches']:
                    if attempted>=max_fits:counts['fit_budget_deferred']+=1;continue
                    reference=references_by_id[match['reference_id']]
                    if match['source_sha256']!=refhash:raise ValueError('Reference source pin mismatch')
                    result=fit_boundary(shape(candidate['geometry']),reference['geometry'],scale_denominators=scales);attempted+=1;counts[result['status']]+=1;counts.update(result.get('review_flags',[]))
                    result.update(candidate_id=candidate['id'],document_sha256=key[0],page=key[1],reference_id=reference['id'],reference_sha256=refhash,target_crs=target_crs,coordinate_frame='pdf_native_points_y_up',physical_identity_verified=False)
                    review_key=(candidate['id'],reference['id'])
                    if review_key in review_index:
                        used_reviews.add(review_key)
                        try:
                            if result['status']!='boundary_hypothesis_only':raise ValueError('Supported boundary hypothesis required')
                            from types import SimpleNamespace
                            from .drawing_page_tools import native_inverse
                            native_page=names.document[key[1]-1];angle=native_page.rotation
                            try:
                                native_page.set_rotation(0);crop=native_page.rect*native_inverse(native_page)
                            finally:native_page.set_rotation(angle)
                            checked=checked_registration(result,candidate,review_index[review_key],SimpleNamespace(cropbox=list(crop)))
                        except (ValueError,KeyError,TypeError) as exc:checked={'status':'withheld','reason':str(exc)}
                        result['independent_review']=checked
                        result['registration_verified']=checked['status']=='accepted_horizontal_fit'
                        counts['accepted_independent_reviews' if result['registration_verified'] else 'withheld_independent_reviews']+=1
                    target.write(json.dumps(result)+'\n')
            if next(decisions,None) is not None:raise ValueError('Association stream contains extra records')
        report={'version':VERSION,'status':'boundary_review_only','counts':dict(counts),'fit_attempts':attempted,'max_fits':max_fits,'candidate_sha256':receipt['candidate_sha256'],'association_sha256':receipt['associations.jsonl_sha256'],'reference_sha256':refhash,'output_sha256':file_hash(output/'boundary-hypotheses.jsonl'),'accepted_independent_reviews':counts['accepted_independent_reviews'],'unused_review_keys':[list(k) for k in sorted(set(review_index)-used_reviews)],'review_sha256':hashlib.sha256(json.dumps(reviews,sort_keys=True).encode()).hexdigest(),'target_crs':target_crs,'reference_crs':reference_crs,'world_geometry_additions':0}
        (output/'boundary-report.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:names.close()


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('candidates','matching-directory','references','reference-crs','target-crs','output','corpus'):p.add_argument('--'+key,required=True)
    p.add_argument('--max-fits',type=int,default=10000);p.add_argument('--registration-reviews');a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(a.candidates,a.matching_directory,a.references,a.reference_crs,a.target_crs,a.output,corpus,max_fits=a.max_fits,registration_reviews=json.loads(Path(a.registration_reviews).read_text()) if a.registration_reviews else None),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
