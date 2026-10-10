"""Bind verified PDF component mentions through the existing registration adapter."""
import json
import math
from pathlib import Path
from .drawing_footprints import promote, retained_page_candidates
from .generation_cycles import atomic_json, file_hash
from .planning_components import page_mentions

VERSION='planning-component-bindings-v1'
FAMILIES={'queue':{'path','plaza'},'fence':{'wall','fence','wood_fence','metal_fence'}}


def run(corpus,mentions_file,candidates_file,bindings_file,manifest_file,output):
    import pymupdf
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    bindings=json.loads(Path(bindings_file).read_text())
    if not isinstance(bindings,list) or len(bindings)>10000:raise ValueError('Bounded component binding list required')
    mentions={};wanted={b['mention_id'] for b in bindings}
    with Path(mentions_file).open() as stream:
        for line in stream:
            if len(line)>8000000:raise ValueError('Component mention line budget exceeded')
            row=json.loads(line)
            if row['id'] in wanted:
                if row['id'] in mentions:raise ValueError('Duplicate mention identity')
                mentions[row['id']]=row
    candidates={};ids={b['candidate_id'] for b in bindings}
    with Path(candidates_file).open() as stream:
        for line in stream:
            if len(line)>8000000:raise ValueError('Candidate line budget exceeded')
            row=json.loads(line)
            if row['id'] in ids:
                if row['id'] in candidates:raise ValueError('Duplicate candidate identity')
                candidates[row['id']]=row
    decisions=[];reviews=[];links={};seen=set();verified={}
    for binding in bindings:
        identifier=binding['feature_id']
        if identifier in seen:raise ValueError('Duplicate component feature identity')
        seen.add(identifier)
        try:
            mention=mentions[binding['mention_id']];candidate=candidates[binding['candidate_id']]
            role=binding['component_role']
            if role not in mention['printed_claims']['roles'] or binding['family'] not in FAMILIES.get(role,set()):
                raise ValueError('Unsupported label role/family; stairs require a separate measured 3D recipe')
            if binding.get('label_geometry_verified') is not True or not isinstance(binding.get('label_geometry_verification_reference'),str) or not binding['label_geometry_verification_reference'].strip():
                raise ValueError('Explicit label-to-geometry association evidence required')
            if (mention['document_sha256'],mention['page'])!=(candidate['document_sha256'],candidate['page']):
                raise ValueError('Mention and candidate must bind the same PDF page')
            printed=mention['printed_claims']
            if role=='fence' and printed.get('height_units')=='m' and 'printed_height_value' in printed:
                height=binding.get('parameters',{}).get('height_m',{}).get('value')
                if isinstance(height,bool) or not isinstance(height,(int,float)) or not math.isclose(height,printed['printed_height_value'],rel_tol=0,abs_tol=1e-6):
                    raise ValueError('Fence height contradicts its bound printed metre dimension')
            sha=candidate['document_sha256'];page=candidate['page'];key=(sha,page,candidate.get('extraction_contract'))
            if key not in verified:
                retained=retained_page_candidates(corpus,candidate)
                pdf_path=corpus.root/'files'/f'{sha}.pdf'
                if file_hash(pdf_path)!=sha:raise ValueError('PDF checksum mismatch')
                with pymupdf.open(pdf_path) as pdf:actual,_=page_mentions(pdf[page-1],sha,page,retained)
                verified[key]={r['id']:r for r in actual}
            if verified[key].get(mention['id'])!=mention:raise ValueError('Mention differs from current native PDF extraction')
            if candidate.get('extraction_kind')!='drawing_geometry':raise ValueError('Current native drawing geometry candidate required')
            review={k:v for k,v in binding.items() if k not in ('mention_id','component_role','label_geometry_verified','label_geometry_verification_reference')}
            reviews.append(review);links[identifier]=(mention,binding)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            decisions.append({'feature_id':identifier,'status':'withheld','reason':str(exc)})
    review_path=output/'candidate-reviews.json';atomic_json(review_path,reviews)
    staging=output/'promoted.jsonl'
    if staging.exists():staging.unlink()
    promoted=promote(candidates_file,review_path,manifest_file,staging,corpus)
    for decision in promoted['decisions']:decisions.append(decision)
    target=output/'features.jsonl';temporary=target.with_suffix('.jsonl.partial');accepted=[]
    with staging.open() as stream,temporary.open('w') as sink:
        for line in stream:
            feature=json.loads(line);mention,binding=links[feature['id']]
            feature['metadata'].update(component_mention_id=mention['id'],component_role=binding['component_role'],
                printed_component_claims=mention['printed_claims'],
                label_geometry_verification_reference=binding['label_geometry_verification_reference'])
            sink.write(json.dumps(feature,sort_keys=True)+'\n');accepted.append(feature['id'])
    temporary.replace(target)
    inputs={name:file_hash(path) for name,path in [('mentions',mentions_file),('candidates',candidates_file),('bindings',bindings_file),('manifest',manifest_file)]}
    report={'version':VERSION,'inputs':inputs,'accepted_component_ids':accepted,'accepted_records':len(accepted),
            'decisions':decisions,'output_sha256':file_hash(target),'world_geometry_additions':0,
            'status':'registered_feature_records; compiler dimensions and native placement checks remain required'}
    atomic_json(output/'binding-report.json',report);return report
