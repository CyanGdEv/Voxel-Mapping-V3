"""Independent semantic investigation; never infers types from a map match."""
from collections import Counter
from pathlib import Path
import json
import re
import pymupdf
from shapely.geometry import box,shape
from shapely.strtree import STRtree
from .drawing_page_tools import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_span,VERSION as GLYPH_VERSION
from .evidence_memory import EvidenceMemory,identity
from .generation_cycles import atomic_json,file_hash

VERSION='osm-semantic-context-v1'
TAGS=('building','building:part','natural','water','waterway','highway','area:highway','area',
      'tourism','attraction','leisure','man_made','roof:shape','layer','bridge','tunnel')
ROLES={'building':('building','building_outline'),'building footprint':('building','building_footprint'),
       'roof outline':('building','roof_outline'),'water edge':('water','water_edge'),
       'edge of water':('water','water_edge'),'lake':('water','water_extent'),
       'pond':('water','water_extent'),'ride boundary':('ride','ride_extent'),
       'ride footprint':('ride','ride_extent')}


def map_semantics(properties):
    kind=properties.get('kind','unknown')
    return {'family_hint':kind,'boundary_role':'tagged_polygon_boundary_convention_unverified',
        'source_tags':{k:str(properties[k])[:256] for k in TAGS if k in properties},
        'physical_identity_verified':False,'boundary_identity_verified':False}


def review(page,sources,refs,alignment,*,max_pairs=64,max_label_screens=16):
    if (type(max_pairs) is not int or not 1<=max_pairs<=64 or type(max_label_screens) is not int or not 0<=max_label_screens<=16
            or len(sources)>30000 or len(refs)>5000):raise ValueError('Bounded semantic review inputs required')
    checks=alignment.get('alignment_checks') or {'hypotheses':[]}
    pairs=sorted({(r['candidate_id'],r['reference_id']) for h in checks['hypotheses'] for r in h['held_out_checks'] if not r['passed']})
    source_ids={};ref_ids={r['id']:r for r in refs}
    for r in sources:source_ids.setdefault(r['id'],r)
    geometries={cid:shape(source_ids[cid]['geometry']) for cid,rid in pairs[:max_pairs] if cid in source_ids}
    ids=sorted(geometries);index=STRtree([geometries[cid] for cid in ids]);hints={cid:[] for cid in ids}
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:raise ValueError('Semantic native glyph budget exceeded')
    inverse=native_inverse(page);screens=deferred=0
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        key=re.sub(r'^(existing|proposed)\s+','',text.casefold())
        if key not in ROLES:continue
        label=box(*(pymupdf.Rect(run['bbox'])*inverse))
        hits=[int(i) for i in index.query(label,predicate='intersects') if geometries[ids[int(i)]].covers(label)]
        if len(hits)!=1:continue
        if screens>=max_label_screens:deferred+=1;continue
        proof=screen_span(page,run,zoom=24 if run['size']<4 else 6);screens+=1
        if proof['status']!='raster_consistent_candidate':continue
        family,role=ROLES[key];hints[ids[hits[0]]].append({'text':text,'family_hint':family,'boundary_role_hint':role,
            'native_label_bounds':list(label.bounds),'glyph_screen':proof,'physical_identity_verified':False})
    rows=[]
    for cid,rid in pairs[:max_pairs]:
        metadata=ref_ids[rid].get('map_semantics',{'family_hint':'unknown','source_tags':{}})
        annotations=hints.get(cid,[]);families={r['family_hint'] for r in annotations}
        named=[]
        if cid in geometries:
            for label in alignment.get('landmark_labels',{}).get('labels',[]):
                if geometries[cid].covers(box(*label['native_label_bounds'])):
                    named.append({'text':label['text'],'original_association_status':label['status'],
                        'name_is_not_a_boundary_type':True,'physical_identity_verified':False})
        status='source_boundary_role_unresolved'
        if cid not in geometries:status='source_geometry_unavailable_for_semantic_review'
        elif len(families)>1:status='ambiguous_source_annotation_hints'
        elif families:
            family=next(iter(families))
            status='same_family_boundary_convention_unverified' if family==metadata['family_hint'] else 'annotation_map_family_conflict_hint'
        rows.append({'candidate_id':cid,'reference_id':rid,'status':status,'source_annotation_hints':annotations,
            'contained_named_annotation_clues':named[:16],'map_semantics':metadata,
            'physical_identity_verified':False,'boundary_identity_verified':False,'registration_verified':False})
    return {'version':VERSION,'status':'semantic_investigation_only','failed_pairs':len(pairs),'reviewed_pairs':len(rows),
        'deferred_pairs':max(0,len(pairs)-max_pairs),'label_screens':screens,'deferred_label_screens':deferred,
        'review_statuses':dict(Counter(r['status'] for r in rows)),'reviews':rows,'geometry_replacements':0,
        'registration_verified':False,'world_geometry_additions':0,
        'limitations':['Neither an OSM tag nor a contained annotation establishes physical boundary identity.',
            'Names, polygon shape and paint colour do not supply a source feature type.',
            'Role hints and conflicts are investigation evidence; they do not filter matches or train a model.']}


def run(corpus,refs,records,page_facts,pages,store,output):
    if len(records)!=len(page_facts) or len(records)!=len(pages):raise ValueError('Semantic page inventory changed')
    contract={'version':VERSION,'glyph_version':GLYPH_VERSION,'renderer':pymupdf.VersionBind,
        'map_semantics_sha256':identity({r['id']:r.get('map_semantics',{}) for r in refs}),'page_facts':page_facts}
    root=Path(output)/identity(contract);root.mkdir(parents=True,exist_ok=True)
    results=[];facts=[];computed=reused=0
    with EvidenceMemory(store) as memory:
        for alignment,parent,(sha,page,raw) in zip(records,page_facts,pages):
            if alignment['document_sha256']!=sha or alignment['page']!=page:raise ValueError('Semantic source page identity changed')
            pdf=corpus.root/'files'/(sha+'.pdf')
            if file_hash(pdf)!=sha:raise ValueError('Semantic original PDF changed')
            data=json.loads(raw);inputs={**{k:v for k,v in contract.items() if k!='page_facts'},
                'document_sha256':sha,'page':page,'native_page_sha256':identity(data),'alignment_fact':parent}
            cached=memory.get('osm_semantic_context',inputs,[parent])
            if cached:result=cached['payload'];reused+=1
            else:
                sources=data['candidates']+alignment.get('targeted_source_candidates',[])
                with pymupdf.open(pdf) as document:result=review(document[page-1],sources,refs,alignment)
                result.update(document_sha256=sha,page=page);computed+=1
            if file_hash(pdf)!=sha:raise ValueError('Semantic original PDF changed during review')
            facts.append(memory.put('osm_semantic_context',inputs,result,[parent]));results.append(result)
    feed=root/'semantic-reviews.jsonl';feed.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in results))
    report={'contract':contract,'run_pages':computed,'reused_pages':reused,'page_facts':facts,
        'review_statuses':dict(sum((Counter(r['review_statuses']) for r in results),Counter())),
        'output_directory':str(root),'output_sha256':{'semantic-reviews.jsonl':file_hash(feed)},
        'registration_verified':False,'world_geometry_additions':0}
    atomic_json(root/'semantic-report.json',report);return report
