"""Model-free native PDF discovery for the shared building reconstruction feed."""
import hashlib
import json
import re
from pathlib import Path
import pymupdf
from .building_spec import digest
from .generation_cycles import atomic_json
from .drawing_geometry import extract_page, VERSION as GEOMETRY_VERSION
from .architectural_graph import build, VERSION as GRAPH_VERSION
from .architectural_view_layout import review, VERSION as LAYOUT_VERSION
from .linework_boundaries import recover_page, VERSION as BOUNDARY_VERSION
from .building_raster_views import placements, VERSION as RASTER_VERSION

VERSION='raw-pdf-building-discovery-v1'
LIMITS={'max_total_pages':128,'max_document_pages':32,'max_records':200000,'max_document_output_bytes':32000000,'max_output_bytes':128000000}


def discover_page(page,sha,number,*,max_candidates=10000):
    """Retain raw candidates and claims; no caption band authorizes a building."""
    parents,extraction=extract_page(page,sha,number,min_line_length_points=.25,max_candidates=max_candidates)
    row={'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'extraction':extraction,'source_geometry':[],'closed_source_faces':[],
        'shared_spec_generated':False,'physical_identity_verified':False,'world_placement_eligible':False}
    row['source_image_placements']=placements(page,sha,number)
    if extraction['status']!='unplaced_geometry_candidates':
        row['status']='complete_geometry_extraction_required';return row
    graph=build(parents)
    if not parents:
        # Bind the empty graph to this inspected page so raster-only drawings
        # still retain native captions without inventing linework.
        graph.update(document_sha256=sha,page=number)
    if graph['status']!='source_drawing_topology_only':
        row.update(status='complete_source_topology_required',graph_review=graph);return row
    layout=review(page,sha,number,graph)
    if not parents:
        row.update(status='no_native_geometry_candidates',caption_layout=layout,
            counts={'source_primitives':0,'closed_source_faces':0,'view_captions':len(layout['view_captions'])})
        return row
    recovered,recovery=recover_page(parents,recovery_options={'max_face_provenance':2048})
    # Partial source-network recovery cannot become an enclosed source outline.
    faces=[r for r in recovered if r.get('extraction_kind')=='linework_boundaries'] if recovery['status']=='enclosed_faces_only' else []
    states=sorted({r['printed_claim']['printed_state'] for r in layout['view_captions']+layout['sheet_titles']
        if r['glyph_screen']['status']=='raster_consistent_candidate' and r['printed_claim'].get('printed_state')})
    row.update(status='native_drawing_candidates_discovered',source_geometry=parents,closed_source_faces=faces,
        source_graph_sha256=digest(graph),source_graph_counts=graph['counts'],caption_layout=layout,
        recovery=recovery,visible_printed_states=states,
        assembly_state='mixed' if {'existing','proposed'}.issubset(states) else
            states[0] if len(states)==1 and states[0] in ('existing','proposed') else 'unknown',
        counts={'source_primitives':len(parents),'closed_source_faces':len(faces),'view_captions':len(layout['view_captions'])},
        blockers=['drawing_view_scope_unverified','physical_component_identity_unverified',
                  'cross_view_dimensions_and_heights_unresolved','geographic_registration_unresolved'])
    return row


def prepare(config,resolve,output):
    if not isinstance(config,dict) or config.get('version')!=VERSION:raise ValueError('Versioned raw PDF discovery feed required')
    overrides=config.get('options',{})
    if not isinstance(overrides,dict):raise ValueError('PDF discovery options must be an object')
    options={**LIMITS,**overrides}
    if set(options)!=set(LIMITS) or any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in options.items()):
        raise ValueError('Bounded PDF discovery options required')
    buildings=config.get('buildings')
    if not isinstance(buildings,list) or not 1<=len(buildings)<=1000:raise ValueError('Bounded building discovery feed required')
    if any(not isinstance(b,dict) for b in buildings):raise ValueError('Building discovery entries must be objects')
    ids=[b.get('building_id') for b in buildings]
    if any(not isinstance(i,str) or not i or len(i)>256 for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Unique bounded building IDs required')
    # Validate request structure before creating an immutable output directory.
    for building in buildings:
        sources=building.get('sources')
        if not isinstance(sources,list) or not 1<=len(sources)<=128:raise ValueError('Bounded PDF source list required')
        seen=set()
        for source in sources:
            if not isinstance(source,dict):raise ValueError('PDF source entries must be objects')
            sha=source.get('sha256');path=source.get('path')
            if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha) or sha in seen:raise ValueError('Unique pinned PDF hashes required per building')
            seen.add(sha)
            if not isinstance(path,str) or not path:raise ValueError('Original PDF path required')
            pages=source.get('pages')
            if pages is not None and (not isinstance(pages,list) or not pages or len(pages)>options['max_document_pages']
                    or any(type(p) is not int or not 1<=p<=10000 for p in pages) or len(set(pages))!=len(pages)):
                raise ValueError('Unique bounded source pages required')
    root=Path(output)
    if root.exists():raise ValueError('Fresh PDF discovery directory required')
    root.mkdir(parents=True)
    contract={'version':VERSION,'config_sha256':digest(config),'options':options,
        'geometry_version':GEOMETRY_VERSION,'graph_version':GRAPH_VERSION,'layout_version':LAYOUT_VERSION,
        'boundary_version':BOUNDARY_VERSION,'raster_version':RASTER_VERSION}
    atomic_json(root/'contract.json',contract)
    pages_used=records_used=bytes_used=0;reports=[];index=[];queue=[]
    with (root/'discovery-pages.jsonl.partial').open('wb') as stream:
        for building in buildings:
            documents=[];page_rows=[]
            for source in sorted(building['sources'],key=lambda r:r['sha256']):
                sha=source['sha256'];receipt={'document_sha256':sha,'status':'invalid_source_input','pages':[]}
                try:
                    path=Path(resolve(source['path']))
                    if path.stat().st_size>32000000:raise ValueError('Original PDF byte budget exceeded')
                    data=path.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Original PDF checksum mismatch')
                    with pymupdf.open(stream=data,filetype='pdf') as document:
                        if len(document)>10000:raise ValueError('PDF page-count budget exceeded')
                        selected=sorted(source.get('pages',range(1,len(document)+1)))
                        if len(selected)>options['max_document_pages'] or pages_used+len(selected)>options['max_total_pages']:
                            raise ValueError('PDF discovery page budget exceeded; select bounded pages')
                        if not selected or selected[-1]>len(document):raise ValueError('Requested original page is absent')
                        # Stage the entire document before committing any page records.
                        staged=[];record_count=document_bytes=0
                        for number in selected:
                            row=discover_page(document[number-1],sha,number)
                            row['building_id']=building['building_id']
                            record_count+=len(row['source_geometry'])+len(row['closed_source_faces'])+len(row['source_image_placements']['placements'])
                            if records_used+record_count>options['max_records']:raise ValueError('PDF discovery record budget exceeded')
                            raw=(json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode()
                            document_bytes+=len(raw)
                            if document_bytes>options['max_document_output_bytes'] or bytes_used+document_bytes>options['max_output_bytes']:
                                raise ValueError('PDF discovery output byte budget exceeded')
                            staged.append((row,raw))
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Original PDF changed during discovery')
                    for row,raw in staged:
                        start=stream.tell();stream.write(raw)
                        pointer={'building_id':building['building_id'],'document_sha256':sha,'page':row['page'],
                            'offset_bytes':start,'length_bytes':len(raw),'record_sha256':hashlib.sha256(raw).hexdigest(),
                            'status':row['status'],'counts':row.get('counts',{}),'assembly_state':row.get('assembly_state','unknown')}
                        pointer['image_inventory_status']=row['source_image_placements']['status']
                        index.append(pointer);page_rows.append(pointer);receipt['pages'].append(row['page'])
                    pages_used+=len(staged);records_used+=record_count;bytes_used+=document_bytes
                    receipt['status']='verified_original_pdf_discovered'
                except (ValueError,RuntimeError,OSError,KeyError,TypeError) as error:
                    receipt['reason']=str(error)
                documents.append(receipt)
            complete=all(d['status']=='verified_original_pdf_discovered' for d in documents) and all(
                p['status']=='native_drawing_candidates_discovered' and
                p['image_inventory_status']=='source_image_placements_only' for p in page_rows)
            states=sorted({p['assembly_state'] for p in page_rows})
            report={'building_id':building['building_id'],'status':'source_inventory_prepared' if complete else 'incomplete_source_inventory',
                    'documents':documents,'discovered_pages':len(page_rows),'source_states':states,
                    'shared_specs_generated':0,'accepted_park_blocks':0}
            reports.append(report)
            queue.append({'building_id':building['building_id'],'source_sha256':sorted(s['sha256'] for s in building['sources']),
                'source_pages':page_rows,'source_inventory_complete':complete,
                'status':'awaiting_source_interpretation' if complete else 'awaiting_complete_pdf_discovery',
                'requirements':['verified_view_scopes','physical_component_identity','cross_view_dimensions_and_heights',
                                'materials_and_openings','geographic_registration'],
                'mixed_source_states_withheld':{'existing','proposed'}.issubset(states) or 'mixed' in states,
                'unresolved_source_state':'unknown' in states or not states,
                'shared_spec_generated':False,'outcome':None})
    (root/'discovery-pages.jsonl.partial').replace(root/'discovery-pages.jsonl')
    with (root/'discovery-pages.jsonl').open('rb') as stream:feed_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    atomic_json(root/'discovery-index.json',{'version':VERSION,'pages_sha256':feed_sha,'pages':index})
    atomic_json(root/'source-queue.json',{'version':VERSION,'records':queue,'training_labels_generated':0})
    report={**contract,'buildings':reports,'discovered_pages':pages_used,'source_records':records_used,'output_bytes':bytes_used,
        'pages_sha256':feed_sha,'shared_specs_generated':0,'training_labels_generated':0,'park_world_blocks_added':0}
    atomic_json(root/'report.json',report)
    return report
