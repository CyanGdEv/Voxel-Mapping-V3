"""Automatic contextual outline matching against retained registered landmarks.

Shape consensus proposes horizontal frames. It never proves physical identity,
construction state, independent checkpoints or geographic placement by itself.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
from pyproj import CRS
from shapely.geometry import shape
from .evidence_memory import EvidenceMemory,identity
from .footprint_matching import descriptor
from .generation_cycles import atomic_json,file_hash
from .reconstruction.registration import require_accepted_review,registration_domain
from .sheet_alignment import fit_sheet
from .alignment_uncertainty import horizontal_scope

VERSION='cross-drawing-context-matching-v2'
# Landmark extraction is unchanged; avoid duplicate anchors on matcher upgrades.
LANDMARK_VERSION='cross-drawing-context-matching-v1'


def collect_landmarks(memory):
    """Only original bridge-checked polygons can become matching references."""
    landmarks=[]
    for fact in memory.retained('drawing_page',limit=1000):
        payload=fact['payload'];source=payload.get('source')
        if not source or source.get('registration_status')!='accepted':continue
        review=source.get('metadata',{}).get('horizontal_registration_review')
        require_accepted_review(review)
        domain=registration_domain(review)
        roots=sorted({p['source_sha256'] for p in review['control_pairs']+review['checkpoint_pairs']})
        for feature in payload['features']:
            geometry=shape(feature['geometry'])
            if geometry.geom_type not in ('Polygon','MultiPolygon'):continue
            descriptor(geometry)
            if feature['geometry_source']!=source['id'] or not domain.buffer(1e-7).covers(geometry):
                raise ValueError('Registered landmark must retain its source and checked domain')
            if not re.fullmatch('[0-9a-f]{64}',source['sha256']):raise ValueError('Pinned landmark drawing required')
            value={'feature':feature,'target_crs':source['crs'],'document_sha256':source['sha256'],
                   'registration':review,'independent_root_sha256s':roots,
                   'trust_scope':'original bridge-checked semantics; matching does not upgrade this scope'}
            identifier=memory.put('registered_landmark',{'version':LANDMARK_VERSION,'feature_sha256':identity(feature)},value,[fact['id']])
            landmarks.append({'id':identifier,**value})
            if len(landmarks)>1000:raise ValueError('Registered landmark budget exceeded')
    # Retain prior-cycle landmarks too; rejection propagation removes descendants.
    return [{'id':f['id'],**f['payload']} for f in memory.retained('registered_landmark',limit=1000)]


def match_page(candidates,landmarks,*,document_sha256,target_crs,expected_scale,
               scale_tolerance=.02,shape_tolerance=.08,max_pair_fits=2000):
    """Generate shape associations automatically and test shared sheet geometry."""
    if not re.fullmatch('[0-9a-f]{64}',document_sha256):raise ValueError('Pinned drawing hash required')
    crs=CRS.from_user_input(target_crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info[:2]):
        raise ValueError('Projected metre target CRS required')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (expected_scale,scale_tolerance,shape_tolerance)) or expected_scale<=0 or not 0<scale_tolerance<=.02 or not 0<shape_tolerance<=.08:
        raise ValueError('Bounded scale and shape tolerances required')
    if type(max_pair_fits) is not int or not 1<=max_pair_fits<=10000:raise ValueError('Bounded pair-fit budget required')
    if len(landmarks)>1000:raise ValueError('Bounded landmark inventory required')
    result={'version':VERSION,'document_sha256':document_sha256,'target_crs':target_crs,
        'status':'awaiting_registered_landmarks','registration_verified':False,'physical_identity_verified':False,
        'world_geometry_additions':0,'training_labels_generated':0,'associations':[],'hypotheses':[],'review_flags':[]}
    result.update(unique_contextual_proposal=False,eligible_landmarks=0)
    if len(candidates)>64:
        return {**result,'status':'matching_budget_withheld','review_flags':['source_object_budget_exceeded']}
    seen=set();local=[]
    for candidate in candidates:
        if candidate['id'] in seen:raise ValueError('Distinct source candidates required')
        seen.add(candidate['id']);geometry=shape(candidate['geometry']);aspect,fill=descriptor(geometry)
        if len(geometry.wkb)>1000000:raise ValueError('Bounded source polygon required')
        local.append((candidate,geometry,aspect,fill))
    refs=[];landmark_ids=set()
    for landmark in landmarks:
        if landmark['id'] in landmark_ids:raise ValueError('Distinct landmark identities required')
        landmark_ids.add(landmark['id'])
        if CRS.from_user_input(landmark['target_crs'])!=crs:continue
        # A drawing or a derived descendant cannot independently align itself.
        if document_sha256 in [landmark['document_sha256'],*landmark['independent_root_sha256s']]:continue
        geometry=shape(landmark['feature']['geometry']);aspect,fill=descriptor(geometry)
        if len(geometry.wkb)>1000000:raise ValueError('Bounded landmark polygon required')
        refs.append({'id':landmark['id'],'source_sha256':landmark['document_sha256'],'geometry':geometry,
                     'aspect':aspect,'fill':fill,'family':landmark['feature']['family']})
    result['eligible_landmarks']=len(refs)
    if not refs:return result
    objects=[];truncated=False
    for candidate,geometry,aspect,fill in local:
        matches=[]
        for ref in refs:
            if candidate.get('family') and candidate['family']!=ref['family']:continue
            shape_error=abs(aspect-ref['aspect'])+abs(fill-ref['fill'])
            area_scale=math.sqrt(ref['geometry'].area/geometry.area)
            scale_error=abs(area_scale/expected_scale-1)
            if shape_error<=shape_tolerance and scale_error<=scale_tolerance:
                matches.append({'reference_id':ref['id'],'source_sha256':ref['source_sha256'],
                    'shape_descriptor_error':shape_error,'area_scale_error':scale_error})
        matches.sort(key=lambda m:(m['shape_descriptor_error'],m['area_scale_error'],m['reference_id']))
        if len(matches)>3:truncated=True
        result['associations'].append({'candidate_id':candidate['id'],'eligible_matches':len(matches),'matches':matches[:3]})
        objects.append({'candidate_id':candidate['id'],'geometry':geometry,'matches':matches[:3]})
    fit=fit_sheet(objects,refs,max_pair_fits=max_pair_fits,tolerance_m=1.,min_iou=.9)
    result.update(status='contextual_alignment_hypotheses' if fit.get('hypotheses') else 'no_contextual_consensus',
        hypotheses=fit.get('hypotheses',[]),hypothesis_count=fit.get('hypothesis_count',0),
        pair_fit_attempts=fit.get('pair_fit_attempts',0),review_flags=fit.get('review_flags',[]))
    if truncated:result['review_flags'].append('association_shortlist_truncated')
    if any(abs(h['scale_metres_per_pdf_point']/expected_scale-1)>scale_tolerance for h in result['hypotheses']):
        result['review_flags'].append('contextual_fit_scale_disagreement')
    result['unique_contextual_proposal']=len(result['hypotheses'])==1 and not result['review_flags']
    for hypothesis in result['hypotheses']:
        hypothesis['horizontal_scope_review']=horizontal_scope(hypothesis,candidates,landmarks)
    result['remaining_requirements']=['verified_source_view_scope','physical_landmark_correspondence',
        'independent_source_bound_checkpoints','bounded_accumulated_uncertainty','construction_state_review']
    return result


def run(corpus,drawing_directory,memory_path,output,*,target_crs,max_pages=1000):
    if type(max_pages) is not int or not 1<=max_pages<=1000:raise ValueError('Bounded cross-drawing page budget required')
    from .mapped_alignment_checks import printed_scale_review,VERSION as scale_version
    drawing_directory=Path(drawing_directory);output=Path(output)
    extraction=json.loads((drawing_directory/'geometry-report.json').read_text())
    feed=drawing_directory/'geometry-candidates.jsonl'
    if file_hash(feed)!=extraction['file_sha256']['geometry']:raise ValueError('Native source geometry changed')
    source_pages=corpus.db.execute('SELECT sha,page FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',
        (extraction['version'],extraction['contract'])).fetchall()
    if len(source_pages)>max_pages:raise ValueError('Cross-drawing page budget exceeded')
    source_hashes=sorted({sha for sha,page in source_pages})
    for sha in source_hashes:
        if not re.fullmatch('[0-9a-f]{64}',sha) or file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:
            raise ValueError('Pinned source PDF required')
    crs=CRS.from_user_input(target_crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info[:2]):
        raise ValueError('Projected metre target CRS required')
    with EvidenceMemory(memory_path) as memory:
        landmarks=collect_landmarks(memory)
        parents=sorted(l['id'] for l in landmarks)
        contract={'version':VERSION,'scale_review_version':scale_version,'target_crs':target_crs,
            'source_geometry_sha256':file_hash(feed),'source_pages':source_pages,'landmark_facts':parents,'max_pages':max_pages}
        # Growing retained knowledge creates a new audit, never overwrites one.
        run_id=identity(contract);output=output/run_id
        contract=json.loads(json.dumps(contract))
        if output.exists():
            report=json.loads((output/'matching-report.json').read_text())
            if report['contract']!=contract or file_hash(output/'page-proposals.jsonl')!=report['output_sha256']:
                raise ValueError('Cross-drawing matching inputs or outputs changed; use a fresh run')
            for fact in report['page_facts']:
                if memory.get('cross_drawing_hypothesis',fact['inputs'],parents) is None:
                    raise ValueError('Cross-drawing evidence memory missing')
            return {**report,'run_pages':0,'reused_pages':report['pages']}
        # Existing page extraction is bounded. Only polygons are considered.
        groups={key:[] for key in source_pages}
        with feed.open() as stream:
            for line in stream:
                if len(line)>8000000:raise ValueError('Bounded native geometry record required')
                row=json.loads(line)
                key=(row['document_sha256'],row['page'])
                if key not in groups:raise ValueError('Native candidate page absent from retained extraction')
                if key not in groups and len(groups)>=max_pages:raise ValueError('Cross-drawing page budget exceeded')
                if row['geometry']['type'] in ('Polygon','MultiPolygon'):
                    if len(groups[key])<65:groups[key].append({'id':row['id'],'geometry':row['geometry']})
                else:groups.setdefault(key,[])
        output.mkdir(parents=True);counts=Counter();facts=[];computed=reused=0
        with (output/'page-proposals.jsonl').open('w') as stream:
            for (sha,page),candidates in sorted(groups.items()):
                pdf=corpus.root/'files'/f'{sha}.pdf'
                if not re.fullmatch('[0-9a-f]{64}',sha) or file_hash(pdf)!=sha:raise ValueError('Pinned source PDF required')
                scale=printed_scale_review(pdf,page)
                # Adding unrelated pages must not invalidate an unchanged page.
                inputs={'version':VERSION,'scale_review_version':scale_version,'target_crs':target_crs,
                    'document_sha256':sha,'page':page,'source_candidates_sha256':identity(candidates),
                    'scale_review_sha256':identity(scale)}
                cached=memory.get('cross_drawing_hypothesis',inputs,parents)
                if cached is not None:proposal=cached['payload'];reused+=1
                else:
                    if scale['status']!='one_visible_printed_scale':
                        proposal={'status':'awaiting_visible_unambiguous_scale','hypotheses':[],
                            'world_geometry_additions':0,'registration_verified':False,'scale_review':scale}
                    else:
                        proposal=match_page(candidates,landmarks,document_sha256=sha,target_crs=target_crs,
                            expected_scale=scale['expected_metres_per_pdf_point'])
                    computed+=1
                identifier=memory.put('cross_drawing_hypothesis',inputs,proposal,parents)
                facts.append({'id':identifier,'inputs':inputs});counts[proposal['status']]+=1
                stream.write(json.dumps({'document_sha256':sha,'page':page,**proposal},sort_keys=True)+'\n')
        for sha in source_hashes:
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF changed during contextual matching')
        for fact in facts:
            if memory.get('cross_drawing_hypothesis',fact['inputs'],parents) is None:
                raise ValueError('Contextual evidence memory changed before report commit')
        report={'contract':contract,'pages':len(groups),'page_statuses':dict(counts),'landmarks':len(landmarks),
            'page_facts':facts,'output_sha256':file_hash(output/'page-proposals.jsonl'),
            'run_id':run_id,'world_geometry_additions':0,'registrations_accepted':0,'training_labels_generated':0}
        atomic_json(output/'matching-report.json',report)
        return {**report,'run_pages':computed,'reused_pages':reused}


def main():
    from .planning_bulk import Corpus
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','geometry','store','output','target-crs'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args();corpus=Corpus(args.corpus)
    try:
        result=run(corpus,args.geometry,args.store,args.output,target_crs=args.target_crs)
        print(json.dumps({k:result[k] for k in ('run_id','pages','page_statuses','landmarks','run_pages','reused_pages',
            'registrations_accepted','world_geometry_additions','training_labels_generated')},sort_keys=True))
    finally:corpus.close()


if __name__=='__main__':main()
