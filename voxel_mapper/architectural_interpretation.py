"""Source-bound architectural claims and paired-line hints; review candidates only."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import pymupdf
from shapely.geometry import Point,Polygon,shape,mapping
from shapely.strtree import STRtree
from .drawing_components import split_page
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span as screen_span

VERSION='architectural-interpretation-v15'
DEFAULTS={'min_band_width_m':.08,'max_band_width_m':1.2,'min_overlap_m':1.5,'max_pair_comparisons':100000}


def options(values=None):
    if values is not None and not isinstance(values,dict):raise ValueError('Architectural options must be an object')
    result={**DEFAULTS,**(values or {})}
    if set(result)!=set(DEFAULTS):raise ValueError('Unknown architectural interpretation option')
    for key in ('min_band_width_m','max_band_width_m','min_overlap_m'):
        value=result[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not .02<=value<=10:
            raise ValueError('Bounded finite architectural distances required')
    if result['min_band_width_m']>=result['max_band_width_m']:raise ValueError('Ordered wall-band widths required')
    if type(result['max_pair_comparisons']) is not int or not 1<=result['max_pair_comparisons']<=100000:
        raise ValueError('Bounded architectural pair budget required')
    return result


def claim(text):
    """Do not equate drawing levels with ODN, or underside values with ridges."""
    if not isinstance(text,str) or len(text)>256:return None
    text=' '.join(text.lower().split())
    match=re.fullmatch(r'(eaves?|ridge)\s+(level|u/s)\s+(-?\d+(?:\.\d+)?)(?:\s*(mm|m))?',text)
    if match:
        base='eaves' if match[1].startswith('eave') else 'ridge'
        return {'role':base+('_underside' if match[2]=='u/s' else '_level'),
            'printed_value':float(match[3]),'printed_units':match[4] or 'unspecified','vertical_datum':'unspecified',
            'height_application_verified':False}
    match=re.fullmatch(r'(?:(brick|stone|timber|rendered|themed)\s+)?(?:(ret|retaining)\s+)?wall(?:\s+(\d+(?:\.\d+)?)\s*(m|mm)?\s*ht)?',text)
    if match:
        result={'role':'retaining_wall' if match[2] else 'wall'}
        if match[1]:result['printed_material']=match[1]
        if match[3]:result.update(printed_height=float(match[3]),printed_units=match[4] or 'unspecified',vertical_datum='local_height_unspecified')
        return result
    if text=='flat roof':return {'role':'flat_roof','printed_roof_form':'flat'}
    match=re.fullmatch(r'(tiled|tile|slate|timber|corrugated)\s+roof',text)
    if match:return {'role':'roof','printed_material':match[1]}
    return None


def wall_bands(parents,factor,*,interpretation_options=None):
    return wall_bands_from_components(split_page(parents),factor,interpretation_options=interpretation_options)


def wall_bands_from_components(components,factor,*,interpretation_options=None):
    """Shared pairing kernel; caller owns complete original component provenance."""
    opts=options(interpretation_options)
    if type(factor) not in (int,float) or not math.isfinite(factor) or not 0<factor<=10000*.0254/72:
        raise ValueError('Bounded source metre scale required')
    rows=[r for r in components if r['geometry']['type']=='LineString' and len(r['geometry']['coordinates'])==2
        and not r.get('curve_approximation',{}).get('cubic_segments') and not r.get('paint_reference_truncated')
        and r.get('paint_references') and all(isinstance(p['stroke_style'].get('dashes_pdf'),str)
            and re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf']) for p in r['paint_references'])]
    rows.sort(key=lambda r:r['id'])
    geometries=[shape(r['geometry']) for r in rows];index=STRtree(geometries);pairs=[];cost=0;neighbors=0
    for i,line in enumerate(geometries):
        a,b=line.coords;length=line.length;u=((b[0]-a[0])/length,(b[1]-a[1])/length)
        for j in index.query(line.buffer(opts['max_band_width_m']/factor)):
            j=int(j)
            if j<=i:continue
            neighbors+=1
            if neighbors>1000000:
                return [],{'status':'neighbor_budget_withheld','neighbor_checks':neighbors,'partial_candidates_discarded':len(pairs)}
            other=geometries[j];c,d=other.coords;other_length=other.length
            v=((d[0]-c[0])/other_length,(d[1]-c[1])/other_length)
            if abs(u[0]*v[1]-u[1]*v[0])>1e-5 or line.intersects(other):continue
            cost+=1
            if cost>opts['max_pair_comparisons']:
                return [],{'status':'pair_budget_withheld','comparisons':cost,'neighbor_checks':neighbors,'partial_candidates_discarded':len(pairs)}
            offsets=[u[0]*(p[1]-a[1])-u[1]*(p[0]-a[0]) for p in (c,d)]
            widths=[abs(x)*factor for x in offsets]
            if offsets[0]*offsets[1]<=0 or min(widths)<opts['min_band_width_m'] or max(widths)>opts['max_band_width_m']:continue
            projections=[(p[0]-a[0])*u[0]+(p[1]-a[1])*u[1] for p in (c,d)]
            lo=max(0,min(projections));hi=min(length,max(projections))
            if (hi-lo)*factor<opts['min_overlap_m']:continue
            def on_second(t):
                ratio=(t-projections[0])/(projections[1]-projections[0])
                return (c[0]+ratio*(d[0]-c[0]),c[1]+ratio*(d[1]-c[1]))
            polygon=Polygon([(a[0]+lo*u[0],a[1]+lo*u[1]),(a[0]+hi*u[0],a[1]+hi*u[1]),on_second(hi),on_second(lo)])
            if not polygon.is_valid or polygon.is_empty:continue
            intervals={i:[lo/length,hi/length],j:sorted([(lo-projections[0])/(projections[1]-projections[0]),(hi-projections[0])/(projections[1]-projections[0])])}
            pairs.append((i,j,polygon,widths,(hi-lo)*factor,intervals))
    # A long source line may support separate opposite fragments. Only
    # positive interior overlap on that same source interval is competition.
    spans={};ambiguous=set();span_checks=0
    for pair_index,pair in enumerate(pairs):
        for component,interval in pair[5].items():
            spans.setdefault(component,[]).append((*interval,pair_index))
    for intervals in spans.values():
        intervals.sort()
        for offset,(lo,hi,pair_index) in enumerate(intervals):
            for following in range(offset+1,len(intervals)):
                other_lo,other_hi,other_index=intervals[following]
                if other_lo>=hi:break
                span_checks+=1
                if cost+span_checks>opts['max_pair_comparisons']:
                    return [],{'status':'span_pair_budget_withheld','comparisons':cost,
                        'span_comparisons':span_checks,'partial_candidates_discarded':len(pairs)}
                if min(hi,other_hi)>max(lo,other_lo):ambiguous.update((pair_index,other_index))
    result=[]
    for pair_index,(i,j,polygon,widths,length_m,intervals) in enumerate(pairs):
        # Rails, hatches and overlapping offsets remain withheld; no nearest pair wins.
        if pair_index in ambiguous:continue
        refs=sorted([{'component_id':rows[k]['id'],'component_contract':rows[k]['extraction_contract'],
            'parent_references':rows[k]['parent_references'],
            'source_interval_fraction':[max(0.,min(1.,t)) for t in intervals[k]]} for k in (i,j)],key=lambda r:r['component_id'])
        identifier=hashlib.sha256(json.dumps([VERSION,refs,mapping(polygon)],sort_keys=True).encode()).hexdigest()
        result.append({'id':identifier,'document_sha256':rows[i]['document_sha256'],'page':rows[i]['page'],
            'coordinate_frame':'pdf_native_points_y_up','geometry':mapping(polygon),'role_candidate':'wall_band',
            'extraction_kind':'architectural_wall_band','extraction_version':VERSION,
            'source_line_references':refs,'width_range_m':widths,'overlap_m':length_m,
            'wall_type':'interior_or_exterior_unresolved','physical_identity_verified':False,'world_geometry_additions':0})
    result.sort(key=lambda r:r['id'])
    return result,{'status':'paired_source_line_hints','comparisons':cost,'neighbor_checks':neighbors,'eligible_pairs':len(pairs),
        'span_comparisons':span_checks,'unique_pairs':len(result),'ambiguous_pairs_withheld':len(ambiguous),
        'ambiguity_basis':'positive_interior_overlap_on_original_source_interval'}


def component_links(parents,bands,associations,labels,factor,*,max_checks=100000):
    """Exact same-page source topology; no nearest-object or height application."""
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded component-link checks required')
    if type(factor) not in (int,float) or not math.isfinite(factor) or not 0<factor<=10000*.0254/72:
        raise ValueError('Bounded source metre scale required')
    records=parents+bands+[r['source_candidate'] for r in associations]
    if (len(associations)>500 or len(labels)>500 or len(bands)>10000
            or len({(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records})>1
            or any(r['coordinate_frame']!='pdf_native_points_y_up' for r in records)):
        raise ValueError('One bounded source page required for component links')
    components={r['id']:r for r in split_page(parents)}
    targets=[('roof_region',r['candidate_id'],shape(r['source_candidate']['geometry']),r['source_candidate']) for r in associations]
    targets += [('wall_band',r['id'],shape(r['geometry']),r) for r in bands]
    index=STRtree([t[2] for t in targets]);checks=0;roof_links=[];leader_links=[];reviews=[]
    def source_refs(record,kind):
        if kind=='wall_band':return {r['component_id']:r['component_contract'] for r in record['source_line_references']}
        return {r['candidate_id']:r['extraction_contract'] for r in record.get('line_parent_references',[])}
    for association in associations:
        roof=association['source_candidate'];polygon=shape(roof['geometry']);refs=source_refs(roof,'roof_region')
        for i in index.query(polygon,predicate='intersects'):
            kind,identifier,geometry,band=targets[int(i)]
            if kind!='wall_band':continue
            for component_id,contract in source_refs(band,kind).items():
                checks+=1
                if checks>max_checks:return {'status':'component_link_budget_withheld','checks':checks,
                    'roof_wall_links':[],'leader_associations':[],'claim_link_reviews':[]}
                component=components.get(component_id)
                if refs.get(component_id)!=contract or not component or component['extraction_contract']!=contract:continue
                overlap=polygon.boundary.intersection(shape(component['geometry'])).intersection(geometry.boundary)
                if overlap.length<=1e-7:continue
                roof_links.append({'roof_candidate_id':roof['id'],'wall_band_id':identifier,
                    'source_component':component,'shared_boundary_geometry':mapping(overlap),
                    'shared_boundary_length_m':overlap.length*factor,
                    'roof_ring_role':'exterior_ring' if polygon.exterior.intersection(overlap).length==overlap.length else 'hole_or_mixed_ring',
                    'association_status':'shared_native_boundary_component','wall_identity_verified':False,
                    'physical_identity_verified':False,'height_application_verified':False,'world_geometry_additions':0})
    boundary_components={identifier for kind,_,_,record in targets for identifier in source_refs(record,kind)}
    leaders=[];endpoints=[];owners=[]
    for component in components.values():
        if (component['id'] in boundary_components or component['geometry']['type']!='LineString' or component.get('curve_approximation',{}).get('cubic_segments')
                or component.get('paint_reference_truncated') or not component.get('paint_references')
                or any(not isinstance(p['stroke_style'].get('dashes_pdf'),str) or not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf']) for p in component['paint_references'])):continue
        line=shape(component['geometry'])
        if not 2<=len(line.coords)<=8 or not line.is_simple or line.is_ring:continue
        k=len(leaders);leaders.append((component,line))
        for end in (0,-1):endpoints.append(Point(line.coords[end]));owners.append((k,end))
    endpoint_index=STRtree(endpoints)
    for claim_index,label in enumerate(labels):
        role=label['printed_claim']['role']
        if role in ('flat_roof','roof'):continue
        if label['glyph_screen']['status']!='raster_consistent_candidate':
            reviews.append({'printed_claim_index':claim_index,'status':'glyph_screen_withheld'});continue
        label_geometry=shape(label['label_geometry']);matches=[]
        for j in endpoint_index.query(label_geometry,predicate='intersects'):
            checks+=1
            if checks>max_checks:return {'status':'component_link_budget_withheld','checks':checks,
                'roof_wall_links':[],'leader_associations':[],'claim_link_reviews':[]}
            k,end=owners[int(j)];component,line=leaders[k];other=Point(line.coords[-1 if end==0 else 0])
            if label_geometry.covers(other):continue
            for i in index.query(other,predicate='intersects'):
                kind,identifier,geometry,record=targets[int(i)]
                checks+=1
                if checks>max_checks:return {'status':'component_link_budget_withheld','checks':checks,
                    'roof_wall_links':[],'leader_associations':[],'claim_link_reviews':[]}
                if (kind=='wall_band')!=(role in ('wall','retaining_wall')):continue
                if component['id'] in source_refs(record,kind):continue
                # A roof level must reach a drawn boundary, not empty space.
                if kind=='roof_region' and not geometry.boundary.intersects(other):continue
                if kind=='roof_region' and line.intersection(geometry).length>1e-7:continue
                matches.append({'printed_claim_index':claim_index,'target_kind':kind,'candidate_id':identifier,
                    'source_leader_component':component,'label_endpoint':mapping(endpoints[int(j)]),'target_endpoint':mapping(other),
                    'association_status':'unique_source_endpoint_connection_candidate','leader_semantics_verified':False,
                    'physical_identity_verified':False,'height_application_verified':False,'world_geometry_additions':0})
        status='no_source_endpoint_connection' if not matches else 'ambiguous_source_endpoint_connections'
        if len(matches)==1:leader_links.extend(matches);status=matches[0]['association_status']
        reviews.append({'printed_claim_index':claim_index,'status':status,'connection_candidates':len(matches)})
    return {'status':'source_component_links_only','checks':checks,'roof_wall_links':roof_links,
        'leader_associations':leader_links,'claim_link_reviews':reviews,
        'physical_identity_verified':False,'height_application_verified':False,'world_geometry_additions':0}


def interpret_page(page,sha,number,parents,polygons,scale_review,*,interpretation_options=None):
    opts=options(interpretation_options)
    if len(polygons)>20000 or any(r['document_sha256']!=sha or r['page']!=number
            or r.get('coordinate_frame')!='pdf_native_points_y_up' for r in parents+polygons):
        raise ValueError('One bounded native architectural page required')
    if scale_review.get('document_sha256')!=sha or scale_review.get('page')!=number:
        raise ValueError('Source-bound visible scale required')
    from .elevation_interpretation import review_page
    from .architectural_references import review_page as reference_page
    references=reference_page(page,sha,number,polygons)
    if references['view_kind']=='plan':
        from .archway_ends import review as review_ends,occurrence_index
        references['archway_end_connections']=review_ends(parents,[references])
        for i,row in enumerate(references['reference_occurrences']):
            row.update(occurrence_index(references['archway_end_connections'],i))
    elevation=review_page(page,sha,number,polygons,scale_review)
    if elevation is not None:
        return {'version':VERSION,'document_sha256':sha,'page':number,'options':opts,
            'status':elevation['status'],'elevation_interpretation':elevation,
            'architectural_references':references,
            'wall_band_candidates':[],'printed_claims':[],'bound_roof_labels':0,
            'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
    if scale_review.get('status')!='one_visible_printed_scale':
        return {'version':VERSION,'document_sha256':sha,'page':number,'status':'complete_extraction_and_visible_scale_required',
            'architectural_references':references,
            'printed_scale_review':scale_review,'wall_band_candidates':[],'printed_claims':[],
            'physical_identity_verified':False,'world_geometry_additions':0}
    bands,network=wall_bands(parents,scale_review['expected_metres_per_pdf_point'],interpretation_options=opts)
    faces={r['id']:r for r in polygons if r['geometry']['type']=='Polygon' and r.get('extraction_kind')!='linework_envelopes'}
    if len(faces)!=sum(r['geometry']['type']=='Polygon' and r.get('extraction_kind')!='linework_envelopes' for r in polygons):
        raise ValueError('Unique architectural enclosure identities required')
    ids=list(faces);geometries=[shape(faces[k]['geometry']) for k in ids]
    if any(not g.is_valid or g.is_empty for g in geometries):raise ValueError('Valid architectural enclosures required')
    index=STRtree(geometries);labels=[];inverse=native_inverse(page)
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Architectural text budget exceeded')
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip();printed=claim(text)
        if not printed:continue
        if len(labels)>=500:raise ValueError('Architectural label budget exceeded')
        screen=screen_span(page,run,zoom=24 if run['size']<4 else 6)
        rect=pymupdf.Rect(run['bbox']);coords=[pymupdf.Point(x,y)*inverse for x,y in
            [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
        label_polygon=Polygon([(p.x,p.y) for p in coords])
        row={'text':text,'printed_claim':printed,'glyph_screen':screen,'label_geometry':mapping(label_polygon),
            'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'association_status':'unbound','candidate_id':None,'physical_identity_verified':False,'world_geometry_additions':0}
        if screen['status']=='raster_consistent_candidate' and printed['role'] in ('flat_roof','roof'):
            hits=[int(i) for i in index.query(label_polygon,predicate='intersects') if geometries[int(i)].contains(label_polygon)]
            if len(hits)==1:row.update(association_status='unique_complete_roof_label_enclosure',candidate_id=ids[hits[0]])
            elif hits:row['association_status']='ambiguous_enclosures'
            else:row['association_status']='no_complete_roof_label_enclosure'
        labels.append(row)
    associations=[{'candidate_id':identifier,'source_candidate':faces[identifier],
        'printed_claim_indices':[i for i,r in enumerate(labels) if r['candidate_id']==identifier],
        'association_status':'unique_complete_roof_label_enclosure','physical_identity_verified':False,
        'registration_verified':False,'world_geometry_additions':0}
        for identifier in sorted({r['candidate_id'] for r in labels if r['candidate_id'] is not None})]
    links=component_links(parents,bands,associations,labels,scale_review['expected_metres_per_pdf_point'])
    from .wall_region_adjacency import review as review_adjacency
    adjacency=review_adjacency(page,sha,number,parents,list(faces.values()),bands)
    from .wall_perimeter_coverage import review as review_perimeter
    perimeter=review_perimeter(parents,list(faces.values()),bands,adjacency) if adjacency['status']=='wall_side_region_evidence_only' else {'status':'complete_adjacency_required','world_geometry_additions':0}
    return {'version':VERSION,'document_sha256':sha,'page':number,'options':opts,
        'source_parent_records_sha256':hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest(),
        'source_polygon_records_sha256':hashlib.sha256(json.dumps(polygons,sort_keys=True).encode()).hexdigest(),
        'status':'architectural_component_candidates_only','wall_band_candidates':bands,'network_review':network,
        'printed_claims':labels,'role_counts':dict(Counter(r['printed_claim']['role'] for r in labels)),
        'roof_region_associations':associations,
        'architectural_references':references,
        'component_links':links,'wall_region_adjacency':adjacency,'wall_perimeter_coverage':perimeter,
        'bound_roof_labels':sum(r['candidate_id'] is not None for r in labels),
        'visible_claim_counts':dict(Counter(r['printed_claim']['role'] for r in labels if r['glyph_screen']['status']=='raster_consistent_candidate')),
        'printed_scale_review':scale_review,'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0,
        'limitations':['Parallel bands can be walls, rails or annotations; interior/exterior wall identity is unresolved.',
            'Enclosed roof labels describe candidate regions; ridges, eaves and physical openings need further source evidence.',
            'Drawing levels have no verified unit/datum or object binding; they cannot set world heights.',
            'No closest-label matching, roof pitch inference, gap filling or semantic feature export occurs.']}


def run(corpus,drawing_directory,output,*,interpretation_options=None):
    """Replay pinned extraction and source PDFs before writing a diagnostic stage."""
    from .drawing_geometry import extract_page
    from .linework_boundaries import recover_page,VERSION as recovery_version
    from .mapped_alignment_checks import printed_scale_review,VERSION as alignment_version
    from .glyph_visibility import VERSION as glyph_version,INK_VERSION as glyph_ink_version
    from .elevation_interpretation import VERSION as elevation_version
    from .architectural_references import VERSION as reference_version,link_pages
    from .archway_ends import VERSION as archway_end_version
    from .architectural_graph import VERSION as graph_version,build as build_graph
    from .architectural_view_layout import VERSION as layout_version,review as review_layout
    from .architectural_view_boundaries import VERSION as viewport_version,review as review_viewports
    from .architectural_linework_frames import VERSION as frame_version,review as review_frames
    from .wall_region_adjacency import VERSION as adjacency_version
    from .wall_perimeter_coverage import VERSION as perimeter_version
    def digest(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    drawing_directory=Path(drawing_directory);output=Path(output)
    extraction=json.loads((drawing_directory/'geometry-report.json').read_text())
    feed=drawing_directory/'geometry-candidates.jsonl'
    if digest(feed)!=extraction['file_sha256']['geometry']:raise ValueError('Native geometry feed changed')
    def extraction_pin(report):
        return hashlib.sha256(json.dumps({k:report[k] for k in ('version','contract','options')},sort_keys=True).encode()).hexdigest()
    contract={'version':VERSION,'options':options(interpretation_options),'drawing_contract':extraction['contract'],
        'geometry_report_contract_sha256':extraction_pin(extraction),'source_feed_sha256':digest(feed),
        'recovery_version':recovery_version,'alignment_version':alignment_version,'glyph_version':glyph_version,
        'glyph_ink_version':glyph_ink_version,'elevation_version':elevation_version,'reference_version':reference_version,'archway_end_version':archway_end_version,'graph_version':graph_version,'layout_version':layout_version,'viewport_version':viewport_version,'linework_frame_version':frame_version,'wall_region_adjacency_version':adjacency_version,'wall_perimeter_version':perimeter_version}
    if output.exists():
        report=json.loads((output/'architectural-report.json').read_text())
        if any(report.get(k)!=v for k,v in contract.items()):raise ValueError('Architectural interpretation inputs changed')
        if digest(output/'architectural-pages.jsonl')!=report['output_sha256']:raise ValueError('Architectural output changed')
        if digest(output/'architectural-reference-links.json')!=report['reference_links_sha256']:raise ValueError('Architectural reference links changed')
        for sha in report['source_documents']:
            if digest(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    output.mkdir(parents=True);counts=Counter();documents=set();pages=0;reference_pages=[];reference_count=0;reference_budget_exhausted=False
    target=output/'architectural-pages.jsonl';temporary=target.with_suffix('.jsonl.partial')
    with temporary.open('w') as stream:
        for sha,number,raw in corpus.db.execute('SELECT sha,page,result FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',
                (extraction['version'],extraction['contract'])):
            if pages>=10000:raise ValueError('Architectural page budget exceeded')
            path=corpus.root/'files'/f'{sha}.pdf'
            if not re.fullmatch('[0-9a-f]{64}',sha) or digest(path)!=sha:raise ValueError('Source PDF checksum mismatch')
            cached=json.loads(raw);scale=printed_scale_review(path,number)
            with pymupdf.open(path) as doc:
                parents,parent_report=extract_page(doc[number-1],sha,number,**extraction['options'])
                parents=json.loads(json.dumps(parents))
                if parents!=cached['candidates'] or parent_report!=cached['report']:raise ValueError('Retained native extraction differs from source')
                if parent_report['status']!='unplaced_geometry_candidates':
                    page_report={'version':VERSION,'document_sha256':sha,'page':number,'status':'complete_extraction_and_visible_scale_required',
                        'extraction':parent_report,'printed_scale_review':scale,'wall_band_candidates':[],'printed_claims':[],
                        'physical_identity_verified':False,'world_geometry_additions':0}
                else:
                    records,recovery=recover_page(parents)
                    if recovery['status'] not in ('enclosed_faces_only','no_eligible_linework'):
                        page_report={'version':VERSION,'document_sha256':sha,'page':number,'status':'complete_boundary_recovery_required',
                            'recovery':recovery,'wall_band_candidates':[],'printed_claims':[],
                            'physical_identity_verified':False,'world_geometry_additions':0}
                    else:
                        page_report=interpret_page(doc[number-1],sha,number,parents,
                            [r for r in records if r['geometry']['type']=='Polygon'],scale,interpretation_options=contract['options'])
                        page_report['source_geometry_graph']=build_graph(parents)
                        if page_report['source_geometry_graph']['status']=='source_drawing_topology_only':
                            page_report['view_layout_review']=review_layout(doc[number-1],sha,number,page_report['source_geometry_graph'])
                            page_report['source_linework_frame_review']=review_frames(page_report['source_geometry_graph'],page_report['view_layout_review'])
                            page_report['source_viewport_review']=review_viewports(path,sha,number,page_report['source_geometry_graph'],page_report['view_layout_review'])
                        page_report.update(extraction=parent_report,recovery=recovery)
            if digest(path)!=sha:raise ValueError('Source PDF changed during architectural review')
            stream.write(json.dumps(page_report,sort_keys=True)+'\n');pages+=1;documents.add(sha)
            graph=page_report.get('source_geometry_graph',{})
            layout=page_report.get('view_layout_review',{})
            viewports=page_report.get('source_viewport_review',{})
            counts['source_viewport_declarations']+=viewports.get('counts',{}).get('viewport_declarations',0)
            counts['source_named_viewport_candidates']+=viewports.get('counts',{}).get('named_caption_candidates',0)
            counts['layout_view_caption_candidates']+=layout.get('counts',{}).get('view_captions',0)
            counts['layout_assignment_budget_withheld_pages']+=layout.get('status')=='layout_assignment_budget_withheld'
            counts['source_graph_edges']+=graph.get('counts',{}).get('edges',0)
            counts['source_graph_subgraphs']+=graph.get('counts',{}).get('connected_subgraphs',0)
            counts['source_graph_budget_withheld_pages']+=graph.get('status')=='graph_budget_withheld'
            counts[page_report['status']]+=1;counts['wall_band_candidates']+=len(page_report['wall_band_candidates'])
            counts['printed_claims']+=len(page_report['printed_claims']);counts['bound_roof_labels']+=page_report.get('bound_roof_labels',0)
            counts['roof_wall_links']+=len(page_report.get('component_links',{}).get('roof_wall_links',[]))
            counts['leader_association_candidates']+=len(page_report.get('component_links',{}).get('leader_associations',[]))
            counts['elevation_material_regions']+=page_report.get('elevation_interpretation',{}).get('counts',{}).get('material_regions',0)
            if 'architectural_references' in page_report:
                reference=page_report['architectural_references'];reference_count+=len(reference['reference_occurrences'])
                counts['archway_end_connection_candidates']+=len(reference.get('archway_end_connections',{}).get('connections',[]))
                counts['complete_archway_source_cycle_candidates']+=reference.get('archway_end_connections',{}).get('complete_source_cycle_candidates',0)
                if reference_count>100000:reference_pages.clear();reference_budget_exhausted=True
                if not reference_budget_exhausted:
                    # Full native proofs stay in the hashed page stream; the
                    # bounded cross-page index retains only proof locations.
                    reference_pages.append({k:reference[k] for k in ('version','document_sha256','page','project_code','view_kind','printed_state')})
                    reference_pages[-1]['reference_occurrences']=[{k:r[k] for k in ('reference_id','glyph_screen','containing_candidate_ids','source_end_connection_indices','complete_source_cycle_candidates') if k in r} for r in reference['reference_occurrences']]
                    for r in reference_pages[-1]['reference_occurrences']:r['glyph_screen']={'status':r['glyph_screen']['status']}
    if digest(feed)!=contract['source_feed_sha256'] or extraction_pin(json.loads((drawing_directory/'geometry-report.json').read_text()))!=contract['geometry_report_contract_sha256']:
        raise ValueError('Architectural source feed changed')
    temporary.replace(target)
    reference_links=link_pages(reference_pages) if not reference_budget_exhausted else {
        'version':reference_version,'status':'reference_budget_withheld','links':[],
        'occurrences_examined':reference_count,'world_geometry_additions':0}
    links_target=output/'architectural-reference-links.json'
    links_target.write_text(json.dumps(reference_links,sort_keys=True)+'\n')
    counts['printed_reference_correspondences']=len(reference_links['links'])
    report={**contract,'status':'architectural_component_candidates_only','pages':pages,'counts':dict(counts),
        'source_documents':sorted(documents),'output_sha256':digest(target),
        'reference_links_sha256':digest(links_target),
        'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
    (output/'architectural-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
