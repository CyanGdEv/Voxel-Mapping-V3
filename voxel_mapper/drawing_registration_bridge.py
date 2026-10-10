"""Automatic named-mark registration and explicit-leader semantic reconstruction.

This narrow adapter consumes verified source policy and independent survey marks.
It does not turn generic OCR labels or mapped boundary matches into survey controls.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
import re
from pathlib import Path
import numpy as np
from pyproj import CRS
from pypdf import PdfReader
from shapely.geometry import Point, shape, mapping
from shapely.ops import transform
from .coordinate_text import coordinate_runs
from .drawing_marks import extract_marks, mark_for_label
from .drawing_geometry import extract_page
from .reconstruction.model import Source, Feature
from .reconstruction.registration import review_registration, apply_registration, registration_domain

VERSION = 'explicit-drawing-bridge-v1'
MARK = re.compile(r'^CP:([A-Za-z0-9_.-]{1,64})$')
OBJECT = re.compile(r'^(PATH|PLAZA|WALL|ROOF):([A-Za-z0-9_.-]{1,64})(?:\s+(.*))?$')
SCALE = re.compile(r'^(?:Scale\s+)?1\s*:\s*(\d{1,5})$', re.I)
SHA = re.compile(r'^[0-9a-f]{64}$')


def file_hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def named_registration(runs, marks, references, sources, document_source, *, tolerance_m=1.):
    if (document_source.metadata.get('reuse_allowed') is not True or document_source.license=='copyright-consultation-only'
            or document_source.metadata.get('reuse_status')=='consultation_only'):
        raise ValueError('Source geometry reuse is not permitted')
    if document_source.kind not in ('cad','planning') or not SHA.fullmatch(str(document_source.sha256)):
        raise ValueError('Pinned drawing source required')
    crs=CRS.from_user_input(document_source.crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info[:2]):
        raise ValueError('Projected metre target CRS required')
    if not math.isfinite(tolerance_m) or not 0<tolerance_m<=1:
        raise ValueError('Automatic bridge cannot exceed one-metre registration tolerance')
    scales={int(m[1]) for r in runs if (m:=SCALE.fullmatch(r['text'].strip()))}
    if len(scales)!=1 or not 1<=next(iter(scales))<=10000:
        raise ValueError('One explicit unambiguous printed scale required')
    expected=next(iter(scales))*.0254/72
    if len(references)>1000: raise ValueError('Survey landmark budget exceeded')
    by_id={}
    for ref in references:
        if ref.get('id') in by_id: raise ValueError('Ambiguous duplicate survey landmark identity')
        by_id[ref['id']]=ref
    observations={};controls=[];checks=[];accuracies={'control':[], 'checkpoint':[]}
    for run in runs:
        match=MARK.fullmatch(run['text'].strip())
        if not match: continue
        identity=match[1]
        if identity in observations: raise ValueError('Repeated drawing survey-mark label')
        point=mark_for_label(marks,run['origin'])
        if point is None: raise ValueError('Survey label has no unique explicit leader to a crosshair')
        observations[identity]=point
        ref=by_id.get(identity)
        if ref is None: continue
        source=sources.get(ref.get('source_id'))
        if (source is None or source.kind!='survey' or source.registration_status!='accepted'
                or source.metadata.get('physical_landmarks_verified') is not True
                or not SHA.fullmatch(str(source.sha256)) or source.sha256==document_source.sha256):
            raise ValueError('Trusted independent surveyed landmark source required')
        if CRS.from_user_input(source.crs)!=crs: raise ValueError('Survey landmark target CRS mismatch')
        role=ref.get('role');accuracy=ref.get('accuracy_m')
        if role not in accuracies or isinstance(accuracy,bool) or not isinstance(accuracy,(int,float)) or not math.isfinite(accuracy) or not 0<=accuracy<=1:
            raise ValueError('Survey landmark role and bounded accuracy required')
        pair={'id':identity,'local':point,'target':ref['target'],'source_id':source.id,
              'source_sha256':source.sha256,'independent':role=='checkpoint','accuracy_m':accuracy}
        (controls if role=='control' else checks).append(pair);accuracies[role].append(accuracy)
    if len(controls)<3 or len(checks)<2:
        raise ValueError('Three identified controls and two separately sourced checkpoints required')
    control_ids={p['source_id'] for p in controls};control_hashes={p['source_sha256'] for p in controls}
    if any(p['source_id'] in control_ids or p['source_sha256'] in control_hashes for p in checks):
        raise ValueError('Checkpoints reuse control source identity or bytes')
    alignment=review_registration(controls,checks,tolerance_m=tolerance_m,expected_scale=expected)
    if alignment['status']!='accepted_horizontal_fit': raise ValueError('Independent registration failed: '+','.join(alignment['reasons']))
    bound=alignment['checkpoint_error']['max_m']+max(accuracies['control'])+max(accuracies['checkpoint'])+expected
    if bound>tolerance_m: raise ValueError('Reference accuracy plus attachment/fit errors exceeds registration budget')
    alignment.update(target_crs=document_source.crs,expected_scale_metres_per_pdf_point=expected,
                     reference_and_attachment_error_budget_m=bound,
                     correspondence_method='exact CP identifier and unique explicit leader; no nearest-mark snapping')
    return alignment


def attributes(text, kind):
    allowed={'PATH':{'surface','width_m'},'PLAZA':{'surface'},'WALL':{'height_m','material'},
             'ROOF':{'elevation_m','slope_x','slope_y','thickness_m','material'}}[kind]
    parsed={}
    for token in (text or '').split():
        if '=' not in token: raise ValueError('Explicit key=value object attributes required')
        key,value=token.split('=',1)
        if key not in allowed or key in parsed or not value: raise ValueError('Unknown or repeated object attribute')
        if key.endswith('_m') or key.startswith('slope_'):
            try: value=float(value)
            except ValueError as error: raise ValueError('Finite numeric object attribute required') from error
            if not math.isfinite(value): raise ValueError('Finite numeric object attribute required')
        parsed[key]=value
    required={'PATH':{'surface'},'PLAZA':{'surface'},'WALL':{'height_m','material'},'ROOF':allowed}[kind]
    if not required<=parsed.keys(): raise ValueError('Required explicit object dimensions/materials missing')
    return parsed


def semantic_features(runs, marks, candidates, source, alignment):
    if (source.metadata.get('semantic_annotation_contract')!='explicit_object_leader_v1'
            or source.metadata.get('semantic_annotation_identity_verified') is not True):
        raise ValueError('Verified explicit-object annotation convention required')
    state=source.metadata.get('drawing_state')
    if state not in ('existing','as_built') or source.metadata.get('drawing_state_verified') is not True or not source.metadata.get('state_verification_reference'):
        raise ValueError('Verified existing/as-built source state required')
    eligible=[]
    for candidate in candidates:
        if candidate.get('rendering_status')!='supported_straight_unclipped_polygon' or candidate.get('paint_reference_truncated'):
            continue
        polygon=shape(candidate['geometry'])
        if polygon.geom_type=='Polygon' and polygon.is_valid and not polygon.is_empty and not polygon.has_z:
            eligible.append((candidate,polygon))
    if len(eligible)>2000: raise ValueError('Semantic page polygon budget exceeded')
    features=[];decisions=[];seen=set();used=set()
    for run in runs:
        match=OBJECT.fullmatch(run['text'].strip())
        if not match: continue
        kind,identifier,raw=match.groups()
        if identifier in seen: raise ValueError('Repeated object callout identity')
        seen.add(identifier)
        try:
            point=mark_for_label(marks,run['origin'])
            if point is None: raise ValueError('Object has no unique explicit leader/crosshair attachment')
            matches=[(c,p) for c,p in eligible if p.contains(Point(point))]
            if len(matches)!=1: raise ValueError('Object mark must identify one unambiguous unclipped polygon')
            candidate,polygon=matches[0]
            if candidate['id'] in used: raise ValueError('Multiple callouts claim the same polygon')
            attrs=attributes(raw,kind)
            def move(x,y,z=None):
                output=apply_registration(np.column_stack((np.atleast_1d(x),np.atleast_1d(y))).tolist(),alignment)
                return tuple(zip(*output))
            placed=transform(move,polygon)
            parameters={k:{'value':v,'source':source.id,'status':'documented'} for k,v in attrs.items()}
            family={'PATH':'path','PLAZA':'plaza','WALL':'wall','ROOF':'roof_surface'}[kind]
            if kind=='ROOF':
                if source.metadata.get('vertical_datum_verified') is not True or not source.vertical_datum:
                    raise ValueError('Roof elevation requires verified source vertical datum')
                if abs(attrs['slope_x'])>3 or abs(attrs['slope_y'])>3 or not .05<=attrs['thickness_m']<=2:
                    raise ValueError('Roof slope/thickness exceeds bounded planar reconstruction')
                anchor=apply_registration([point],alignment)[0]
                rotation=np.asarray(alignment['matrix'])/alignment['scale']
                slope=rotation@np.array([attrs['slope_x'],attrs['slope_y']])
                parameters={'plane':{'value':{'origin_xy':anchor,'elevation_m':attrs['elevation_m'],'slope_xy':slope.tolist()},'source':source.id,'status':'documented'},
                            'thickness_m':parameters['thickness_m'],'material':parameters['material']}
            feature=Feature('drawing/'+source.sha256+'/'+str(source.metadata['registration_page'])+'/'+identifier,
                            family,mapping(placed),source.id,parameters,
                            {'drawing_state':state,'document_sha256':source.sha256,'page':source.metadata['registration_page'],
                             'candidate_id':candidate['id'],'geometry_crs':source.crs,'annotation_text':run['text'],
                             'physical_verification_reference':'source explicit_object_leader_v1 convention and retained unique leader',
                             'state_verification_reference':source.metadata['state_verification_reference']})
            feature.validate({source.id:source},source.vertical_datum)
            features.append(feature);used.add(candidate['id'])
            decisions.append({'object_id':identifier,'family':family,'status':'registered_semantic_feature','feature_id':feature.id})
        except (ValueError,KeyError,TypeError) as error:
            decisions.append({'object_id':identifier,'status':'withheld','reason':str(error)})
    return features,decisions


def bridge_page(pdf,page_number,source,references,sources):
    if file_hash(pdf)!=source.sha256: raise ValueError('Source PDF checksum mismatch')
    reader=PdfReader(pdf)
    if not 1<=page_number<=len(reader.pages) or len(reader.pages)>1000: raise ValueError('Bounded source page required')
    page=reader.pages[page_number-1]
    content=page.get_contents()
    if content is not None and any(op in (b'BMC',b'BDC') or (op==b'Tr' and int(args[0])==3) for args,op in content.operations):
        raise ValueError('Invisible or layered text requires a separate visibility-aware adapter')
    runs=coordinate_runs(page);marks=extract_marks(page,reuse_allowed=source.metadata.get('reuse_allowed') is True)
    alignment=named_registration(runs,marks,references,sources,source)
    metadata={**source.metadata,'horizontal_registration_review':alignment,
              'registration_document_sha256':source.sha256,'registration_page':page_number}
    registered=replace(source,registration_status='accepted',metadata=metadata)
    import pymupdf as fitz
    with fitz.open(pdf) as document: candidates,extraction=extract_page(document[page_number-1],source.sha256,page_number)
    features,decisions=semantic_features(runs,marks,candidates,registered,alignment)
    return registered,features,{'status':'registered_semantic_features' if features else 'registered_no_supported_semantics',
            'document_sha256':source.sha256,'page':page_number,'registration':alignment,'semantic_decisions':decisions,
            'feature_count':len(features),'extraction_status':extraction['status'], 'world_geometry_additions':0,
            'limitations':['Exact named marks and verified structured object callouts only; not generic PDF interpretation.',
                           'Registered features still require compile, conflict and native export checks.',
                           'Roof surfaces do not supply missing walls, openings or support geometry.']}


def run(pdf,page_number,manifest_file,references_file,source_id,output):
    manifest=json.loads(Path(manifest_file).read_text());refs=json.loads(Path(references_file).read_text())
    sources={s['id']:Source(**s) for s in manifest['sources']};source=sources[source_id]
    if source.crs!=manifest['crs']:raise ValueError('Drawing and manifest CRS mismatch')
    output=Path(output)
    if output.exists(): raise ValueError('Use a fresh bridge output directory')
    temporary=output.with_name(output.name+'.partial')
    if temporary.exists(): raise ValueError('Incomplete bridge output; use a fresh output directory')
    temporary.mkdir(parents=True)
    inputs={k:file_hash(p) for k,p in [('pdf',pdf),('manifest',manifest_file),('references',references_file)]}
    try:
        registered,features,report=bridge_page(pdf,page_number,source,refs['landmarks'],sources)
    except (ValueError,KeyError,TypeError) as error:
        report={'status':'withheld','reason':str(error),'feature_count':0,'world_geometry_additions':0};registered=None;features=[]
    report.update(version=VERSION,input_sha256=inputs)
    (temporary/'features.jsonl').write_text(''.join(json.dumps(f.__dict__,sort_keys=True)+'\n' for f in features))
    if registered:
        manifest={**manifest,'sources':[registered.__dict__ if s['id']==source_id else s for s in manifest['sources']]}
    (temporary/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report['output_sha256']={n:file_hash(temporary/n) for n in ['features.jsonl','manifest.json']}
    (temporary/'bridge-report.json').write_text(json.dumps(report,indent=2)+'\n');temporary.replace(output)
    return report


def run_batch(documents_file,manifest_file,references_file,output,*,max_pages=10000,max_features=2500000):
    """Stream page features into one compiler-ready manifest; cache exact input/output hashes."""
    if type(max_pages) is not int or not 1<=max_pages<=10000 or type(max_features) is not int or not 1<=max_features<=2500000:
        raise ValueError('Bridge page/feature budget exceeded')
    document_path=Path(documents_file);documents=json.loads(document_path.read_text())
    if not isinstance(documents,list) or len(documents)>1000:raise ValueError('Bounded document list required')
    manifest=json.loads(Path(manifest_file).read_text());sources={s['id']:Source(**s) for s in manifest['sources']}
    references=json.loads(Path(references_file).read_text())['landmarks']
    resolved=[];identities=set()
    for item in documents:
        source=sources[item['source_id']];pdf=(document_path.parent/item['file']).resolve()
        if source.crs!=manifest['crs']:raise ValueError('Drawing and manifest CRS mismatch')
        pages=item.get('pages')
        if pages is not None and (not isinstance(pages,list) or not pages or len(pages)>1000 or any(type(p) is not int or p<1 for p in pages) or len(set(pages))!=len(pages)):
            raise ValueError('Distinct bounded document pages required')
        if source.sha256 in identities:raise ValueError('One batch entry per distinct drawing PDF required')
        identities.add(source.sha256)
        resolved.append((pdf,source,pages,file_hash(pdf)))
    contract={'version':VERSION,'input_sha256':{k:file_hash(p) for k,p in [('documents',documents_file),('manifest',manifest_file),('references',references_file)]},
              'document_content_sha256':[digest for _,_,_,digest in resolved],'max_pages':max_pages,'max_features':max_features}
    output=Path(output)
    if output.exists():
        report=json.loads((output/'bridge-report.json').read_text())
        if report.get('contract')!=contract:raise ValueError('Bridge batch inputs changed')
        for name,sha in report['output_sha256'].items():
            if file_hash(output/name)!=sha:raise ValueError('Bridge batch output checksum mismatch')
        return report
    temporary=output.with_name(output.name+'.partial')
    if temporary.exists():raise ValueError('Incomplete bridge batch; use a fresh output directory')
    temporary.mkdir(parents=True);total=0;page_count=0;registered_sources=[];counts={}
    with (temporary/'features.jsonl').open('w') as features_out,(temporary/'pages.jsonl').open('w') as page_out:
        for pdf,source,pages,digest in resolved:
            if pages is None:
                if digest!=source.sha256:raise ValueError('Batch source PDF checksum mismatch')
                reader=PdfReader(pdf)
                if len(reader.pages)>1000:raise ValueError('Drawing PDF page budget exceeded')
                pages=range(1,len(reader.pages)+1)
            for page in pages:
                page_count+=1
                if page_count>max_pages:raise ValueError('Bridge batch page budget exceeded')
                page_source=replace(source,id=source.id+'/page-'+str(page))
                if page_source.id in sources:raise ValueError('Generated page source ID collides with original manifest')
                try:
                    registered,features,review=bridge_page(pdf,page,page_source,references,sources)
                except (ValueError,KeyError,TypeError) as error:
                    registered=None;features=[];review={'status':'withheld','reason':str(error),'document_sha256':source.sha256,'page':page,'feature_count':0,'world_geometry_additions':0}
                if total+len(features)>max_features:raise ValueError('Bridge feature budget exceeded')
                for feature in features:features_out.write(json.dumps(feature.__dict__,sort_keys=True)+'\n')
                if registered:registered_sources.append(registered.__dict__)
                total+=len(features);counts[review['status']]=counts.get(review['status'],0)+1
                page_out.write(json.dumps(review,sort_keys=True)+'\n')
    manifest={**manifest,'sources':manifest['sources']+registered_sources}
    (temporary/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report={'status':'registered_semantic_features' if total else 'withheld_no_registered_semantics',
            'contract':contract,'pages':page_count,'page_statuses':counts,'feature_count':total,
            'accepted_page_sources':len(registered_sources),'world_geometry_additions':0,
            'output_sha256':{n:file_hash(temporary/n) for n in ['features.jsonl','manifest.json','pages.jsonl']}}
    (temporary/'bridge-report.json').write_text(json.dumps(report,indent=2)+'\n');temporary.replace(output)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['manifest','references','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--pdf');p.add_argument('--source-id');p.add_argument('--documents')
    p.add_argument('--page',type=int,default=1);a=p.parse_args()
    if a.documents:result=run_batch(a.documents,a.manifest,a.references,a.output)
    else:
        if not a.pdf or not a.source_id:p.error('Supply --documents or --pdf and --source-id')
        result=run(a.pdf,a.page,a.manifest,a.references,a.source_id,a.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
