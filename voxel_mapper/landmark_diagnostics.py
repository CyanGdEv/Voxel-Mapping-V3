"""Explicit boundary-seed diagnostics; never accept registration or generate blocks."""
import math
import numpy as np
from shapely.geometry import shape
from .boundary_registration import fit_boundary
from .footprint_matching import descriptor
from .mapped_sheet_placement import placed

VERSION='landmark-diagnostics-v1'


def diagnose(objects, references, candidate_id, reference_id, *, min_iou=.7, tolerance_m=10.):
    if not 1<=len(objects)<=20000 or not 1<=len(references)<=5000:
        raise ValueError('Bounded object and reference collections required')
    if not math.isfinite(min_iou) or not .5<=min_iou<=1 or not math.isfinite(tolerance_m) or not 0<tolerance_m<=25:
        raise ValueError('Bounded comparison thresholds required')
    if len({o['candidate_id'] for o in objects})!=len(objects) or len({r['id'] for r in references})!=len(references):
        raise ValueError('Unique object and reference identities required')
    by_id={o['candidate_id']:o for o in objects}; refs={r['id']:r for r in references}
    if candidate_id not in by_id or reference_id not in refs: raise ValueError('Selected identities must exist')
    obj=by_id[candidate_id]; ref=refs[reference_id]
    if obj['geometry'].geom_type!='Polygon' or ref['geometry'].geom_type!='Polygon': raise ValueError('Polygon landmark required')
    order=sorted(objects,key=lambda o:(len(o['geometry'].exterior.coords)<=5 if o['geometry'].geom_type=='Polygon' else True,-o['geometry'].area,o['candidate_id']))
    pool=sorted((sum(abs(a-b) for a,b in zip(descriptor(obj['geometry']),descriptor(r['geometry']))),r['id']) for r in references if r['geometry'].geom_type=='Polygon' and len(r['geometry'].interiors)==len(obj['geometry'].interiors))
    rank=next(i for i,o in enumerate(order,1) if o['candidate_id']==candidate_id)
    fit=fit_boundary(obj['geometry'],ref['geometry']); trials=[]
    if 'best_fit' in fit:
        alternatives=[fit['best_fit']]+fit.get('equivalent_orientations',[])
        for seed in alternatives:
            if any(np.allclose(seed['matrix'],t['fit']['matrix'],rtol=0,atol=1e-9) and np.allclose(seed['translation_m'],t['fit']['translation_m'],rtol=0,atol=1e-7) for t in trials):continue
            hits=[];near=[]
            for o in objects:
                g=placed(o['geometry'],seed)
                for r in references:
                    h=r['geometry']
                    if g.geom_type!='Polygon' or h.geom_type!='Polygon' or len(g.interiors)!=len(h.interiors):continue
                    distance=g.centroid.distance(h.centroid)
                    if distance>tolerance_m:continue
                    iou=g.intersection(h).area/g.union(h).area
                    row={'candidate_id':o['candidate_id'],'reference_id':r['id'],'reference_name':r.get('name',''),'intersection_over_union':iou,'centroid_error_m':distance}
                    near.append(row)
                    if iou>=min_iou:hits.append(row)
            hits.sort(key=lambda h:(-h['intersection_over_union'],h['centroid_error_m'],h['candidate_id'],h['reference_id']))
            selected=[];used_o=set();used_r=set()
            for h in hits:
                if h['candidate_id'] in used_o or h['reference_id'] in used_r:continue
                a,b=by_id[h['candidate_id']]['geometry'],refs[h['reference_id']]['geometry']
                if any(left.intersection(right).area/min(left.area,right.area)>.1 for old in selected for left,right in ((a,by_id[old['candidate_id']]['geometry']),(b,refs[old['reference_id']]['geometry']))):continue
                selected.append(h);used_o.add(h['candidate_id']);used_r.add(h['reference_id'])
            trials.append({'fit':seed,'distinct_nonoverlapping_outline_matches':selected,'nearby_subthreshold_comparisons':sorted([h for h in near if h['intersection_over_union']<min_iou],key=lambda h:-h['intersection_over_union'])[:20]})
    return {'version':VERSION,'status':'explicit_seed_diagnostic_only','candidate_id':candidate_id,'reference_id':reference_id,'default_seed_rank':rank,'outside_default_seed_selection':rank>64,'descriptor_reference_rank':next(i for i,(_,rid) in enumerate(pool,1) if rid==reference_id),'min_iou':min_iou,'tolerance_m':tolerance_m,'orientation_trials':trials,'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0,'limitations':['Explicit correspondence is a review hypothesis, not physical identity proof','Multiple corners of one object are not independent controls','Mapped outline comparison is not independent checkpoint evidence','No placement is accepted or exported by this diagnostic']}


def main():
    import argparse,json
    from pathlib import Path
    from .planning_bulk import Corpus
    from .boundary_registration import file_hash
    from .drawing_footprints import retained_page_candidates
    from .footprint_matching import references as load_references,lines
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','candidates','references','target-crs','document-sha256','candidate-id','reference-id','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--page',type=int,default=1);p.add_argument('--reference-crs',default='EPSG:4326');a=p.parse_args()
    corpus=Corpus(a.corpus)
    try:
        source_hash=file_hash(corpus.root/'files'/f'{a.document_sha256}.pdf')
        if source_hash!=a.document_sha256:raise ValueError('Source PDF checksum mismatch')
        candidate_hash=file_hash(a.candidates);objects=[];cache={}
        for c in lines(a.candidates):
            if (c['document_sha256'],c['page'])!=(a.document_sha256,a.page):continue
            key=(c.get('extraction_kind'),c['extraction_contract'])
            if key not in cache:cache[key]={r['id']:r for r in retained_page_candidates(corpus,c)}
            if cache[key].get(c['id'])!=c:raise ValueError('Candidate differs from retained page extraction')
            if c['geometry']['type']=='Polygon':objects.append({'candidate_id':c['id'],'geometry':shape(c['geometry'])})
        refs,refhash,rejected=load_references(a.references,a.reference_crs,a.target_crs)
        result=diagnose(objects,refs,a.candidate_id,a.reference_id)
        if file_hash(a.candidates)!=candidate_hash or file_hash(a.references)!=refhash:raise ValueError('Diagnostic input changed')
        result.update(document_sha256=a.document_sha256,page=a.page,candidate_feed_sha256=candidate_hash,reference_sha256=refhash,reference_crs=a.reference_crs,target_crs=a.target_crs,rejected_references=rejected,checked_polygon_objects=len(objects))
        Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'seed_rank':result['default_seed_rank'],'match_counts':[len(t['distinct_nonoverlapping_outline_matches']) for t in result['orientation_trials']],'world_geometry_additions':0}))
    finally:corpus.close()

if __name__=='__main__':main()
