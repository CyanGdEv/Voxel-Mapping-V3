"""Bounded multi-object sheet placement hypotheses; never promotes geometry."""
import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import sqlite3

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import shape

from .boundary_registration import file_hash, similarity
from .footprint_matching import NativeNames, descriptor, lines, references

VERSION = 'sheet-alignment-v2'


def fit_sheet(objects, reference_rows, *, max_pair_fits=2000, tolerance_m=2., min_iou=.85):
    """Fit pairs, then require three unique polygon correspondences to agree.

    Centroids and outline overlap are matching evidence, never survey controls.
    Ambiguous assignments and equivalent placements remain visible for review.
    """
    if type(max_pair_fits) is not int or not 1 <= max_pair_fits <= 10000:
        raise ValueError('Pair fit budget must be 1..10000')
    if not math.isfinite(tolerance_m) or not 0 < tolerance_m <= 100:
        raise ValueError('Tolerance must be finite and 0..100 metres')
    if not math.isfinite(min_iou) or not .5 <= min_iou <= 1:
        raise ValueError('Minimum IoU must be .5..1')
    if len(objects) > 64:
        return {'status':'withheld', 'reason':'Sheet object budget exceeded', 'registration_verified':False, 'world_geometry_additions':0}
    refs={r['id']:r for r in reference_rows}; edges=[]; seen=set()
    centres={r['id']:np.asarray(r['geometry'].centroid.coords[0]) for r in reference_rows}
    local_centres=[]
    for obj in objects:
        if obj['candidate_id'] in seen:raise ValueError('Duplicate sheet candidate')
        seen.add(obj['candidate_id']);descriptor(obj['geometry'])
        local_centres.append(obj['geometry'].centroid.coords[0])
        if len(obj['matches']) > 3:raise ValueError('At most three associations per object')
        match_ids=set()
        for match in obj['matches']:
            rid=match['reference_id']
            if rid in match_ids:raise ValueError('Duplicate object reference')
            match_ids.add(rid);ref=refs[rid]
            if match['source_sha256']!=ref['source_sha256']:raise ValueError('Reference source pin mismatch')
            edges.append((obj,ref))
    local_centres=np.asarray(local_centres,dtype=float).reshape((-1,2))
    local_by_id={obj['candidate_id']:local_centres[i] for i,obj in enumerate(objects)}
    object_indices={obj['candidate_id']:i for i,obj in enumerate(objects)}
    edge_indices=np.asarray([object_indices[obj['candidate_id']] for obj,ref in edges],dtype=int)
    edge_targets=np.asarray([centres[ref['id']] for obj,ref in edges],dtype=float).reshape((-1,2))
    hypotheses=[]; attempted=0; exhausted=False
    for (a,ra),(b,rb) in combinations(edges,2):
        if a['candidate_id']==b['candidate_id'] or ra['id']==rb['id']:continue
        if attempted >= max_pair_fits:exhausted=True;break
        attempted+=1
        local=np.asarray([local_by_id[a['candidate_id']], local_by_id[b['candidate_id']]])
        target=np.asarray([centres[ra['id']], centres[rb['id']]])
        try:matrix,translation,scale,_=similarity(local,target)
        except ValueError:continue
        if any(np.allclose(matrix,h['matrix'],rtol=0,atol=scale*1e-6) and np.allclose(translation,h['translation_m'],rtol=0,atol=1e-5) for h in hypotheses):continue
        supports=[]; ambiguous=False
        placed_centres=local_centres@np.asarray(matrix).T+translation
        delta=placed_centres[edge_indices]-edge_targets
        eligible=np.flatnonzero(np.einsum('ij,ij->i',delta,delta)<=(tolerance_m+1e-6)**2)
        near_objects={}
        for index in eligible:
            obj,ref=edges[int(index)];near_objects.setdefault(object_indices[obj['candidate_id']],[]).append(ref)
        for index,nearby in near_objects.items():
            obj=objects[index]
            placed=affine_transform(obj['geometry'],[matrix[0][0],matrix[0][1],matrix[1][0],matrix[1][1],*translation]);hits=[]
            for ref in nearby:
                geom=ref['geometry']
                if placed.centroid.distance(geom.centroid)>tolerance_m:continue
                if len(getattr(placed,'interiors',()))!=len(getattr(geom,'interiors',())):continue
                iou=placed.intersection(geom).area/placed.union(geom).area
                if iou>=min_iou:hits.append({'candidate_id':obj['candidate_id'],'reference_id':ref['id'],'intersection_over_union':iou,'centroid_error_m':placed.centroid.distance(geom.centroid),'identity_verified':False})
            if len(hits)==1:supports.append(hits[0])
            elif len(hits)>1:ambiguous=True
        counts=Counter(s['reference_id'] for s in supports)
        if any(v>1 for v in counts.values()):ambiguous=True
        supports=[s for s in supports if counts[s['reference_id']]==1]
        if len(supports)<3:continue
        # Refit all supporting centroids, and validate every outline again.
        selected={o['candidate_id']:o for o in objects}
        points=np.asarray([selected[s['candidate_id']]['geometry'].centroid.coords[0] for s in supports])
        targets=np.asarray([refs[s['reference_id']]['geometry'].centroid.coords[0] for s in supports])
        if np.linalg.matrix_rank(points-points.mean(axis=0),tol=1e-8)<2:continue
        # Nested paint outlines cannot stand in for several distinct objects.
        overlap=False
        for left,right in combinations(supports,2):
            for geoms in ((selected[left['candidate_id']]['geometry'],selected[right['candidate_id']]['geometry']), (refs[left['reference_id']]['geometry'],refs[right['reference_id']]['geometry'])):
                g,h=geoms
                if g.intersection(h).area/min(g.area,h.area)>.1:overlap=True
        if overlap:continue
        matrix,translation,scale,rms=similarity(points,targets)
        valid=True
        for s in supports:
            placed=affine_transform(selected[s['candidate_id']]['geometry'],[matrix[0][0],matrix[0][1],matrix[1][0],matrix[1][1],*translation]);ref=refs[s['reference_id']]['geometry']
            s['intersection_over_union']=placed.intersection(ref).area/placed.union(ref).area
            s['centroid_error_m']=placed.centroid.distance(ref.centroid)
            valid &= s['intersection_over_union']>=min_iou and s['centroid_error_m']<=tolerance_m
        if valid:
            duplicate=next((h for h in hypotheses if np.allclose(matrix,h['matrix'],rtol=0,atol=scale*1e-6) and np.allclose(translation,h['translation_m'],rtol=0,atol=1e-5)),None)
            if duplicate is not None:duplicate['assignment_ambiguous'] |= ambiguous
            else:hypotheses.append({'matrix':matrix,'translation_m':translation,'scale_metres_per_pdf_point':scale,'centroid_rms_m':rms,'supports':supports,'assignment_ambiguous':ambiguous})
    hypotheses.sort(key=lambda h:(-len(h['supports']),h['centroid_rms_m'],json.dumps(h['supports'],sort_keys=True)))
    best=hypotheses[:12]
    flags=[]
    if exhausted:flags.append('pair_fit_budget_exhausted')
    if len(best)>1:flags.append('multiple_sheet_placements')
    if any(h['assignment_ambiguous'] for h in best):flags.append('ambiguous_object_assignment')
    return {'status':'sheet_hypotheses_only' if best else 'withheld','reason':None if best else 'Fewer than three distinct noncollinear outline correspondences agree','hypotheses':best,'hypothesis_count':len(hypotheses),'pair_fit_attempts':attempted,'review_flags':flags,'registration_verified':False,'independent_checkpoints':[],'physical_identity_verified':False,'world_geometry_additions':0}


def run(candidates, matching_directory, reference_file, reference_crs, target_crs, output, corpus, *, max_pair_fits=2000, max_records=2500000):
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    # Validate numerical options even for an empty corpus.
    fit_sheet([],[],max_pair_fits=max_pair_fits)
    matching_directory=Path(matching_directory);receipt=json.loads((matching_directory/'matching-report.json').read_text())
    associations=matching_directory/'associations.jsonl';rows,refhash,_=references(reference_file,reference_crs,target_crs)
    contract={'version':VERSION,'candidate_sha256':file_hash(candidates),'association_sha256':file_hash(associations),'reference_sha256':refhash,'reference_crs':reference_crs,'target_crs':target_crs,'max_pair_fits':max_pair_fits,'max_records':max_records}
    if any(receipt.get(k)!=contract[k] for k in ('candidate_sha256','reference_sha256','reference_crs','target_crs')) or receipt['associations.jsonl_sha256']!=contract['association_sha256']:raise ValueError('Matching inputs or output changed')
    output=Path(output)
    if output.exists():
        report=json.loads((output/'sheet-report.json').read_text())
        if any(report.get(k)!=v for k,v in contract.items()) or file_hash(output/'sheet-hypotheses.jsonl')!=report['output_sha256']:raise ValueError('Sheet alignment inputs or output changed')
        for sha in report['source_documents']:
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    output.mkdir(parents=True);db=sqlite3.connect(output/'sheet-index.sqlite');names=NativeNames(corpus,rows);counts=Counter()
    db.execute('CREATE TABLE objects(pdf TEXT,page INTEGER,id TEXT UNIQUE,named INTEGER,error REAL,payload TEXT)');db.execute('CREATE INDEX pages ON objects(pdf,page)')
    source_documents=set();document=None;opened_sha=None
    try:
        decisions=iter(lines(associations))
        for count,candidate in enumerate(lines(candidates),1):
            if count>max_records:raise ValueError('Record budget exceeded')
            association=next(decisions,None)
            if association is None or any(association.get(k)!=candidate[v] for k,v in [('candidate_id','id'),('document_sha256','document_sha256'),('page','page')]):raise ValueError('Candidate/association identity or ordering changed')
            names.get(candidate);source_documents.add(candidate['document_sha256']);counts['candidates_checked']+=1
            if association['matches']:
                named=int(any(m['metrics']['exact_interior_name'] for m in association['matches']))
                error=min(m['metrics']['shape_descriptor_error'] for m in association['matches'])
                if not math.isfinite(error):raise ValueError('Finite association shape score required')
                db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)',(candidate['document_sha256'],candidate['page'],candidate['id'],named,error,json.dumps({'candidate_id':candidate['id'],'geometry':candidate['geometry'],'matches':association['matches']})))
            if count%1000==0:db.commit()
        if next(decisions,None) is not None:raise ValueError('Extra association records')
        db.commit()
        with (output/'sheet-hypotheses.jsonl').open('w') as stream:
            for pdf,page,total in db.execute('SELECT pdf,page,count(*) FROM objects GROUP BY pdf,page ORDER BY pdf,page'):
                objects=[]
                for raw, in db.execute('SELECT payload FROM objects WHERE pdf=? AND page=? ORDER BY named DESC,error,id LIMIT 64',(pdf,page)):
                    obj=json.loads(raw);obj['geometry']=shape(obj['geometry']);objects.append(obj)
                result=fit_sheet(objects,rows,max_pair_fits=max_pair_fits)
                result['selected_objects']=len(objects);result['deferred_objects']=total-len(objects)
                if total>len(objects):result['review_flags'].append('object_selection_truncated')
                import pymupdf
                from .drawing_batch import SCALE
                if pdf!=opened_sha:
                    if document:document.close()
                    document=pymupdf.open(corpus.root/'files'/f'{pdf}.pdf');opened_sha=pdf
                text=document[page-1].get_text()
                if len(text)>1000000:raise ValueError('Native scale text budget exceeded')
                denominators=sorted({int(v) for v in SCALE.findall(text) if 1<=int(v)<=100000})
                flags=result.setdefault('review_flags',[])
                if not denominators:flags.append('printed_scale_missing')
                elif len(denominators)>1:flags.append('printed_scale_ambiguous')
                for fit in result.get('hypotheses',[]):
                    fit['printed_scale_comparison']=[{'denominator':v,'relative_scale_error':abs(fit['scale_metres_per_pdf_point']/(v*.0254/72)-1)} for v in denominators[:16]]
                    if denominators and min(r['relative_scale_error'] for r in fit['printed_scale_comparison'])>.02:flags.append('printed_scale_disagreement')
                result['review_flags']=sorted(set(flags))
                result.update(document_sha256=pdf,page=page,target_crs=target_crs,reference_sha256=refhash,associated_objects=total)
                counts[result['status']]+=1;counts.update(result.get('review_flags',[]));stream.write(json.dumps(result)+'\n')
        report={**contract,'status':'sheet_review_only','counts':dict(counts),'source_documents':sorted(source_documents),'output_sha256':file_hash(output/'sheet-hypotheses.jsonl'),'world_geometry_additions':0}
        (output/'sheet-report.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:
        if document:document.close()
        names.close();db.close()


def main():
    from .planning_bulk import Corpus
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('candidates','matching-directory','references','reference-crs','target-crs','output','corpus'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--max-pair-fits',type=int,default=2000);args=parser.parse_args();corpus=Corpus(args.corpus)
    try:print(json.dumps(run(args.candidates,args.matching_directory,args.references,args.reference_crs,args.target_crs,args.output,corpus,max_pair_fits=args.max_pair_fits),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
