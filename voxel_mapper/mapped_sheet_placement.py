"""Bounded full-boundary map placement proposals, never surveyed registration."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import MultiPoint, mapping, shape
from shapely.strtree import STRtree

from .boundary_registration import file_hash, fit_boundary, similarity
from .footprint_matching import descriptor, lines, references, NativeNames

VERSION = 'mapped-sheet-placement-v1'


def placed(geometry, fit):
    m, t = fit['matrix'], fit['translation_m']
    return affine_transform(geometry, [m[0][0], m[0][1], m[1][0], m[1][1], *t])


def propose(objects, refs, *, max_seed_fits=512, min_iou=.7, tolerance_m=10.):
    """Map agreement is estimated placement evidence, not survey acceptance.

    Full boundaries seed fits; all page objects and spatial reference neighbours
    verify them. This avoids top-three descriptor and first-64 object starvation.
    """
    if type(max_seed_fits) is not int or not 1 <= max_seed_fits <= 2000:
        raise ValueError('Seed fit budget must be 1..2000')
    if not math.isfinite(min_iou) or not .5 <= min_iou <= 1 or not math.isfinite(tolerance_m) or not 0 < tolerance_m <= 25:
        raise ValueError('Invalid mapped review thresholds')
    if len(objects)>20000 or len(refs)>5000:raise ValueError('Page/reference budget exceeded')
    if len({o['candidate_id'] for o in objects})!=len(objects) or len({r['id'] for r in refs})!=len(refs):raise ValueError('Unique object/reference IDs required')
    for o in objects:descriptor(o['geometry'])
    for r in refs:descriptor(r['geometry'])
    reference_index=STRtree([r['geometry'] for r in refs]);by_id={o['candidate_id']:o for o in objects};ref_ids={r['id']:r for r in refs}
    # Distinctive large nonrectangular objects first; seed selection never limits
    # verification objects. Rectangles remain available as fallback seeds.
    seeds=sorted(objects,key=lambda o:(len(o['geometry'].exterior.coords)<=5 if o['geometry'].geom_type=='Polygon' else True,-o['geometry'].area,o['candidate_id']))[:64]
    edges=[]
    for o in seeds:
        if o['geometry'].geom_type!='Polygon':continue
        a=descriptor(o['geometry']);pool=[]
        for r in refs:
            g=r['geometry']
            if g.geom_type!='Polygon' or len(g.interiors)!=len(o['geometry'].interiors):continue
            error=sum(abs(x-y) for x,y in zip(a,descriptor(g)))
            if error<=.2:pool.append((error,r['id'],r))
        # More than the original three alternatives, followed by actual shape fit.
        for rank,(_,_,r) in enumerate(sorted(pool)[:8]):edges.append((rank,-o['geometry'].area,o['candidate_id'],o,r))
    edges.sort(key=lambda e:e[:3]);attempted=0;hypotheses=[]
    def support(fit):
        hits=[]
        for o in objects:
            p=placed(o['geometry'],fit)
            for index in reference_index.query(p):
                r=refs[int(index)];g=r['geometry']
                if p.geom_type!=g.geom_type or p.geom_type!='Polygon' or len(p.interiors)!=len(g.interiors):continue
                distance=p.centroid.distance(g.centroid)
                if distance>tolerance_m:continue
                iou=p.intersection(g).area/p.union(g).area
                if iou>=min_iou:hits.append({'candidate_id':o['candidate_id'],'reference_id':r['id'],'intersection_over_union':iou,'centroid_error_m':distance,'identity_verified':False})
        hits.sort(key=lambda h:(-h['intersection_over_union'],h['centroid_error_m'],h['candidate_id'],h['reference_id']))
        selected=[];used_o=set();used_r=set()
        for h in hits:
            if h['candidate_id'] in used_o or h['reference_id'] in used_r:continue
            a,b=by_id[h['candidate_id']]['geometry'],ref_ids[h['reference_id']]['geometry'];overlap=False
            for old in selected:
                for left,right in ((a,by_id[old['candidate_id']]['geometry']),(b,ref_ids[old['reference_id']]['geometry'])):
                    if left.intersection(right).area/min(left.area,right.area)>.1:overlap=True
            if overlap:continue
            selected.append(h);used_o.add(h['candidate_id']);used_r.add(h['reference_id'])
        return selected
    for _,_,_,o,r in edges:
        if attempted>=max_seed_fits:break
        attempted+=1;boundary=fit_boundary(o['geometry'],r['geometry'])
        if 'best_fit' not in boundary:continue
        seed=boundary['best_fit']
        if seed['intersection_over_union']<.8:continue
        supports=support(seed)
        if len(supports)<3:continue
        fit=seed
        for _ in range(2):
            local=np.asarray([by_id[h['candidate_id']]['geometry'].centroid.coords[0] for h in supports]);target=np.asarray([ref_ids[h['reference_id']]['geometry'].centroid.coords[0] for h in supports])
            if np.linalg.matrix_rank(local-local.mean(axis=0))<2:break
            m,t,s,rms=similarity(local,target);fit={'matrix':m,'translation_m':t,'scale_metres_per_pdf_point':s,'centroid_rms_m':rms};supports=support(fit)
            if len(supports)<3:break
        if len(supports)<3 or 'centroid_rms_m' not in fit:continue
        # Recompute metrics for the final transform and expose map disagreement.
        supports=support(fit)
        local=np.asarray([by_id[h['candidate_id']]['geometry'].centroid.coords[0] for h in supports])
        if len(supports)<3 or np.linalg.matrix_rank(local-local.mean(axis=0))<2:continue
        fit.update(centroid_rms_m=float(np.sqrt(np.mean([h['centroid_error_m']**2 for h in supports]))),max_centroid_error_m=max(h['centroid_error_m'] for h in supports),supports=supports,seed_candidate_id=o['candidate_id'],seed_reference_id=r['id'])
        # Domain uses whole supported outlines, and is explicitly unverified.
        hull=MultiPoint([xy for h in supports for xy in placed(by_id[h['candidate_id']]['geometry'],fit).exterior.coords]).convex_hull
        fit['mapped_support_envelope']=mapping(hull)
        if any(np.allclose(fit['matrix'],h['matrix'],rtol=0,atol=fit['scale_metres_per_pdf_point']*.001) and np.allclose(fit['translation_m'],h['translation_m'],rtol=0,atol=1.) for h in hypotheses):continue
        hypotheses.append(fit)
    hypotheses.sort(key=lambda h:(-len(h['supports']),h['centroid_rms_m'],h['seed_candidate_id'],h['seed_reference_id']))
    # Fits at the same location may differ within map uncertainty. Different
    # locations remain separate alternatives, never silently auto-selected.
    best=[]
    for h in hypotheses:
        if any(max(placed(by_id[o['candidate_id']]['geometry'],h).centroid.distance(placed(by_id[o['candidate_id']]['geometry'],b).centroid) for o in seeds[:8])<=tolerance_m for b in best):continue
        best.append(h)
        if len(best)>=12:break
    flags=[]
    if len(edges)>max_seed_fits:flags.append('seed_fit_budget_exhausted')
    if len(objects)>len(seeds):flags.append('seed_selection_truncated; all_objects_verified')
    if len(best)>1:flags.append('multiple_mapped_placements')
    return {'status':'provisional_mapped_placement' if best else 'withheld','hypotheses':best,'seed_fit_attempts':attempted,'seed_objects':len(seeds),'verification_objects':len(objects),'review_flags':flags,'min_iou':min_iou,'tolerance_m':tolerance_m,'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0,'limitations':['Mapped agreement is not independently surveyed registration','Map and drawing may differ in date, generalisation or extent','Support envelope is not a validated registration domain']}


def run(candidates, reference_file, reference_crs, target_crs, output, corpus, *, sheets=None, max_seed_fits=512, min_iou=.7, tolerance_m=10., max_records=2500000):
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    propose([],[],max_seed_fits=max_seed_fits,min_iou=min_iou,tolerance_m=tolerance_m)
    if sheets is not None and (not isinstance(sheets,list) or len(sheets)>10000 or any(not isinstance(s,list) or len(s)!=2 or not isinstance(s[0],str) or len(s[0])!=64 or type(s[1]) is not int or s[1]<1 for s in sheets)):raise ValueError('Bounded PDF/page sheet selection required')
    rows,refhash,_=references(reference_file,reference_crs,target_crs)
    contract={'version':VERSION,'candidate_sha256':file_hash(candidates),'reference_sha256':refhash,'reference_crs':reference_crs,'target_crs':target_crs,'sheets':sheets,'max_seed_fits':max_seed_fits,'min_iou':min_iou,'tolerance_m':tolerance_m,'max_records':max_records}
    output=Path(output);receipt=output/'placement-report.json'
    if output.exists():
        if not receipt.exists():raise ValueError('Incomplete placement output; use a fresh directory')
        report=json.loads(receipt.read_text())
        if any(report.get(k)!=v for k,v in contract.items()):raise ValueError('Placement inputs changed')
        for name,digest in report['output_sha256'].items():
            if file_hash(output/name)!=digest:raise ValueError('Placement output checksum mismatch')
        for sha in report['source_documents']:
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    output.mkdir(parents=True);db=sqlite3.connect(output/'page-index.sqlite');db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE candidates(pdf TEXT,page INTEGER,id TEXT UNIQUE,payload TEXT)');db.execute('CREATE INDEX pages ON candidates(pdf,page)')
    names=NativeNames(corpus,rows);counts=Counter();documents=set();selection=None if sheets is None else {tuple(s) for s in sheets}
    try:
        for count,c in enumerate(lines(candidates),1):
            if count>max_records:raise ValueError('Record budget exceeded')
            if selection is not None and (c['document_sha256'],c['page']) not in selection:continue
            names.get(c);documents.add(c['document_sha256']);counts['candidates_checked']+=1
            db.execute('INSERT INTO candidates VALUES(?,?,?,?)',(c['document_sha256'],c['page'],c['id'],json.dumps(c)))
            if count%1000==0:db.commit()
        db.commit()
        with (output/'sheet-placements.jsonl.partial').open('w') as proposals,(output/'placed-review-geometry.jsonl.partial').open('w') as geometry:
            for pdf,page,total in db.execute('SELECT pdf,page,count(*) FROM candidates GROUP BY pdf,page ORDER BY pdf,page'):
                if total>20000:raise ValueError('Placement page budget exceeded')
                records=[json.loads(p) for p, in db.execute('SELECT payload FROM candidates WHERE pdf=? AND page=? ORDER BY id',(pdf,page))];objects=[{'candidate_id':c['id'],'geometry':shape(c['geometry'])} for c in records if c['geometry']['type'] in ('Polygon','MultiPolygon')]
                result=propose(objects,rows,max_seed_fits=max_seed_fits,min_iou=min_iou,tolerance_m=tolerance_m);result.update(document_sha256=pdf,page=page,reference_sha256=refhash,target_crs=target_crs);counts[result['status']]+=1;counts['seed_fit_attempts']+=result['seed_fit_attempts']
                proposals.write(json.dumps(result)+'\n')
                if len(result['hypotheses'])!=1:
                    if result['hypotheses']:counts['ambiguous_sheets_not_exported']+=1
                    continue
                fit=result['hypotheses'][0];domain=shape(fit['mapped_support_envelope']);placement_id=hashlib.sha256(json.dumps({'pdf':pdf,'page':page,'fit':fit,'contract':contract},sort_keys=True).encode()).hexdigest()
                for c in records:
                    g=placed(shape(c['geometry']),fit)
                    if not domain.buffer(1e-7).covers(g):counts['outside_support_envelope']+=1;continue
                    geometry.write(json.dumps({'type':'Feature','id':c['id'],'geometry':mapping(g),'properties':{'status':'provisional_mapped_review_geometry','geometry_role':'unclassified_drawing_geometry','placement_id':placement_id,'candidate_id':c['id'],'source_candidate_sha256':contract['candidate_sha256'],'document_sha256':pdf,'page':page,'extraction_contract':c['extraction_contract'],'parent_references':c.get('parent_references',[]),'geometry_crs':target_crs,'reference_sha256':refhash,'curve_approximation':c.get('curve_approximation'),'registration_verified':False,'physical_identity_verified':False,'world_geometry_additions':0}})+'\n');counts['positioned_review_records']+=1
            for stream in (proposals,geometry):stream.flush();os.fsync(stream.fileno())
        for filename in ('sheet-placements.jsonl','placed-review-geometry.jsonl'):(output/(filename+'.partial')).replace(output/filename)
        if file_hash(candidates)!=contract['candidate_sha256'] or file_hash(reference_file)!=refhash:raise ValueError('Placement inputs changed during run')
        report={**contract,'counts':dict(counts),'source_documents':sorted(documents),'output_sha256':{name:file_hash(output/name) for name in ('sheet-placements.jsonl','placed-review-geometry.jsonl')},'status':'provisional_map_review_only','world_geometry_additions':0}
        temporary=receipt.with_suffix('.partial');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(receipt);return report
    finally:names.close();db.close()


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('candidates','references','reference-crs','target-crs','output','corpus'):p.add_argument('--'+key,required=True)
    p.add_argument('--sheets');p.add_argument('--max-seed-fits',type=int,default=512)
    a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(a.candidates,a.references,a.reference_crs,a.target_crs,a.output,corpus,sheets=json.loads(Path(a.sheets).read_text()) if a.sheets else None,max_seed_fits=a.max_seed_fits),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
