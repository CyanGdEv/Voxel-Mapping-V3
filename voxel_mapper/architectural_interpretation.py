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
from .glyph_visibility import screen_span

VERSION='architectural-interpretation-v1'
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
    opts=options(interpretation_options);components=split_page(parents)
    if type(factor) not in (int,float) or not math.isfinite(factor) or not 0<factor<=10000*.0254/72:
        raise ValueError('Bounded source metre scale required')
    rows=[r for r in components if r['geometry']['type']=='LineString' and len(r['geometry']['coordinates'])==2
        and not r.get('curve_approximation',{}).get('cubic_segments') and not r.get('paint_reference_truncated')
        and r.get('paint_references') and all(isinstance(p['stroke_style'].get('dashes_pdf'),str)
            and re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf']) for p in r['paint_references'])]
    geometries=[shape(r['geometry']) for r in rows];index=STRtree(geometries);pairs=[];degree=Counter();cost=0;neighbors=0
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
            pairs.append((i,j,polygon,widths,(hi-lo)*factor));degree[i]+=1;degree[j]+=1
    result=[]
    for i,j,polygon,widths,length_m in pairs:
        # Rails, hatch families and alternative offsets remain ambiguous; no nearest pair wins.
        if degree[i]!=1 or degree[j]!=1:continue
        refs=sorted([{'component_id':rows[k]['id'],'component_contract':rows[k]['extraction_contract'],
            'parent_references':rows[k]['parent_references']} for k in (i,j)],key=lambda r:r['component_id'])
        identifier=hashlib.sha256(json.dumps([VERSION,refs,mapping(polygon)],sort_keys=True).encode()).hexdigest()
        result.append({'id':identifier,'document_sha256':rows[i]['document_sha256'],'page':rows[i]['page'],
            'coordinate_frame':'pdf_native_points_y_up','geometry':mapping(polygon),'role_candidate':'wall_band',
            'extraction_kind':'architectural_wall_band','extraction_version':VERSION,
            'source_line_references':refs,'width_range_m':widths,'overlap_m':length_m,
            'wall_type':'interior_or_exterior_unresolved','physical_identity_verified':False,'world_geometry_additions':0})
    result.sort(key=lambda r:r['id'])
    return result,{'status':'paired_source_line_hints','comparisons':cost,'neighbor_checks':neighbors,'eligible_pairs':len(pairs),
        'unique_pairs':len(result),'ambiguous_pairs_withheld':len(pairs)-len(result)}


def interpret_page(page,sha,number,parents,polygons,scale_review,*,interpretation_options=None):
    opts=options(interpretation_options)
    if len(polygons)>20000 or any(r['document_sha256']!=sha or r['page']!=number
            or r.get('coordinate_frame')!='pdf_native_points_y_up' for r in parents+polygons):
        raise ValueError('One bounded native architectural page required')
    if (scale_review.get('document_sha256')!=sha or scale_review.get('page')!=number
            or scale_review.get('status')!='one_visible_printed_scale'):
        raise ValueError('Source-bound visible scale required')
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
        labels.append(row)
    return {'version':VERSION,'document_sha256':sha,'page':number,'options':opts,
        'source_parent_records_sha256':hashlib.sha256(json.dumps(parents,sort_keys=True).encode()).hexdigest(),
        'source_polygon_records_sha256':hashlib.sha256(json.dumps(polygons,sort_keys=True).encode()).hexdigest(),
        'status':'architectural_component_candidates_only','wall_band_candidates':bands,'network_review':network,
        'printed_claims':labels,'role_counts':dict(Counter(r['printed_claim']['role'] for r in labels)),
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
    from .glyph_visibility import VERSION as glyph_version
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
        'recovery_version':recovery_version,'alignment_version':alignment_version,'glyph_version':glyph_version}
    if output.exists():
        report=json.loads((output/'architectural-report.json').read_text())
        if any(report.get(k)!=v for k,v in contract.items()):raise ValueError('Architectural interpretation inputs changed')
        if digest(output/'architectural-pages.jsonl')!=report['output_sha256']:raise ValueError('Architectural output changed')
        for sha in report['source_documents']:
            if digest(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    output.mkdir(parents=True);counts=Counter();documents=set();pages=0
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
                if parent_report['status']!='unplaced_geometry_candidates' or scale['status']!='one_visible_printed_scale':
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
                        page_report.update(extraction=parent_report,recovery=recovery)
            if digest(path)!=sha:raise ValueError('Source PDF changed during architectural review')
            stream.write(json.dumps(page_report,sort_keys=True)+'\n');pages+=1;documents.add(sha)
            counts[page_report['status']]+=1;counts['wall_band_candidates']+=len(page_report['wall_band_candidates'])
            counts['printed_claims']+=len(page_report['printed_claims']);counts['bound_roof_labels']+=page_report.get('bound_roof_labels',0)
    if digest(feed)!=contract['source_feed_sha256'] or extraction_pin(json.loads((drawing_directory/'geometry-report.json').read_text()))!=contract['geometry_report_contract_sha256']:
        raise ValueError('Architectural source feed changed')
    temporary.replace(target)
    report={**contract,'status':'architectural_component_candidates_only','pages':pages,'counts':dict(counts),
        'source_documents':sorted(documents),'output_sha256':digest(target),
        'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
    (output/'architectural-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
