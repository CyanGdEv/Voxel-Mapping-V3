"""Source-bound landmark triage; geometric/text hints never verify buildings."""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import pymupdf
from shapely.geometry import Point, Polygon, shape
from shapely.strtree import STRtree
from shapely import get_coordinates
from .drawing_geometry import native_inverse
from .drawing_components import split_page
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_span

VERSION = 'landmark-context-v2'
ROOM = re.compile(r'^(?:toilets?|w\.?c\.?|office|kitchen|store(?:room)?|plant room|rooflights?)$',re.I)
VIEW = re.compile(r'^(?:existing\s+)?(?:(ground|first|second)\s+floor\s+plan|roof\s+plan)$',re.I)
DEFAULTS = {'min_area_m2':4.,'min_continuation_m':3.,'continuation_ratio':2.}


def options(overrides=None):
    result={**DEFAULTS,**(overrides or {})}
    if set(result)!=set(DEFAULTS):raise ValueError('Unknown landmark context option')
    for key,value in result.items():
        bounds={'min_area_m2':(.25,100),'min_continuation_m':(1,20),'continuation_ratio':(1,10)}[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not bounds[0]<=value<=bounds[1]:
            raise ValueError('Bounded landmark context thresholds required')
    return result


def page_context(page,sha,page_number,parents,records,scale_review,*,context_options=None):
    opts=options(context_options)
    if (scale_review.get('document_sha256')!=sha or scale_review.get('page')!=page_number
            or scale_review.get('status')!='one_visible_printed_scale'):
        raise ValueError('Source-bound visible scale required for landmark context')
    factor=scale_review.get('expected_metres_per_pdf_point')
    if type(factor) not in (int,float) or not math.isfinite(factor) or not 0<factor<=10000*.0254/72:
        raise ValueError('Bounded landmark metre scale required')
    if len(records)>20000 or len(parents)>10000:raise ValueError('Landmark context page budget exceeded')
    if any(r.get('document_sha256')!=sha or r.get('page')!=page_number
           or r.get('coordinate_frame')!='pdf_native_points_y_up' for r in parents+records):
        raise ValueError('Landmark context records must bind one native page')
    candidates={r['id']:r for r in records if r['geometry']['type']=='Polygon'}
    if len(candidates)!=sum(r['geometry']['type']=='Polygon' for r in records):
        raise ValueError('Unique landmark candidate identifiers required')
    geometries={k:shape(r['geometry']) for k,r in candidates.items()}
    if any(not g.is_valid or g.is_empty for g in geometries.values()):raise ValueError('Valid landmark polygons required')
    components=split_page(parents)
    lines=[r for r in components if r['geometry']['type']=='LineString'
           and not r.get('curve_approximation',{}).get('cubic_segments')
           and r.get('paint_references') and not r.get('paint_reference_truncated')
           and all(isinstance(p['stroke_style'].get('dashes_pdf'),str) and
               re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf'])
               for p in r['paint_references'])]
    line_geometries=[shape(r['geometry']) for r in lines];line_index=STRtree(line_geometries)
    atomic={r['id']:r for r in records if r['geometry']['type']=='Polygon'
            and r.get('extraction_kind')!='linework_envelopes'}
    atom_ids=list(atomic);atom_geometries=[shape(atomic[k]['geometry']) for k in atom_ids]
    atom_index=STRtree(atom_geometries);room_hints={};labels=[];views=set()
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Landmark text budget exceeded')
    inverse=native_inverse(page)
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        room=bool(ROOM.fullmatch(text));view=bool(VIEW.fullmatch(text))
        if not room and not view:continue
        if len(labels)>=100:raise ValueError('Landmark context label budget exceeded')
        screen=screen_span(page,run,zoom=24 if run['size']<4 else 6)
        visible=screen['status']=='raster_consistent_candidate'
        label={'text':text,'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
               'glyph_screen':screen,'association':'none'}
        if visible and view:views.add('roof_plan' if 'roof' in text.lower() else 'floor_plan')
        if visible and room:
            rect=pymupdf.Rect(run['bbox']);points=[pymupdf.Point(x,y)*inverse for x,y in
                [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
            label_polygon=Polygon([(p.x,p.y) for p in points])
            hits=[int(i) for i in atom_index.query(label_polygon,predicate='intersects') if atom_geometries[int(i)].contains(label_polygon)]
            if len(hits)==1:
                identifier=atom_ids[hits[0]];room_hints.setdefault(identifier,[]).append(text)
                label.update(association='unique_contained_atomic_face',candidate_id=identifier)
            elif hits:label['association']='ambiguous_atomic_faces'
        labels.append(label)
    decisions=[];eligible=[]
    for identifier,record in candidates.items():
        polygon=geometries[identifier];area=polygon.area*factor*factor;reasons=[];continuations=[]
        if area<opts['min_area_m2']:reasons.append('below_landmark_area_threshold')
        if identifier in room_hints:reasons.append('contained_room_or_roof_detail_label')
        for i in line_index.query(polygon.boundary,predicate='intersects'):
            i=int(i);line=line_geometries[i]
            if len(line.coords)!=2:continue
            shared=line.intersection(polygon.boundary).length
            if shared*factor<1:continue
            outside=line.difference(polygon).length
            if outside*factor<opts['min_continuation_m'] or outside<=shared*opts['continuation_ratio']:continue
            a,b=list(line.coords);length=math.dist(a,b)
            projections=[line.project(Point(p)) for p in get_coordinates(line.intersection(polygon))]
            margins=[min(projections)*factor,(length-max(projections))*factor] if projections else [0,0]
            continuations.append({'source_component_id':lines[i]['id'],'shared_boundary_m':shared*factor,
                'outside_candidate_m':outside*factor,'direction':[(b[0]-a[0])/length,(b[1]-a[1])/length],
                'line_origin_pdf':list(a),'extensions_beyond_candidate_m':margins})
        parallel=any(abs(sum(x*y for x,y in zip(a['direction'],b['direction'])))>.995
            and abs(a['direction'][0]*(b['line_origin_pdf'][1]-a['line_origin_pdf'][1])
                -a['direction'][1]*(b['line_origin_pdf'][0]-a['line_origin_pdf'][0]))>1e-7
            for i,a in enumerate(continuations) for b in continuations[:i])
        if parallel:reasons.append('parallel_through_line_boundary_candidate')
        if any(min(c['extensions_beyond_candidate_m'])>=opts['min_continuation_m']/2 for c in continuations):
            reasons.append('bidirectional_through_line_boundary_candidate')
        status='withheld_landmark_context' if reasons else 'eligible_landmark_candidate'
        decisions.append({'candidate_id':identifier,'document_sha256':sha,'page':page_number,
            'status':status,'reasons':reasons,'area_m2':area,'room_or_detail_labels':room_hints.get(identifier,[]),
            'boundary_continuations':continuations[:32],'continuation_count':len(continuations),
            'outline_basis':'adjacent_face_envelope' if record.get('extraction_kind')=='linework_envelopes' else 'primitive_enclosure',
            'page_view_hints':sorted(views),'physical_identity_verified':False,'world_geometry_additions':0})
        if not reasons:eligible.append(record)
    return eligible,{'version':VERSION,'document_sha256':sha,'page':page_number,'options':opts,
        'status':'landmark_context_hints_only','decisions':decisions,'labels':labels,'page_view_hints':sorted(views),
        'candidate_count':len(candidates),'eligible_candidates':len(eligible),
        'reason_counts':dict(Counter(reason for d in decisions for reason in d['reasons'])),
        'physical_identity_verified':False,'world_geometry_additions':0,
        'limitations':['Area thresholds can exclude genuine small structures; original geometry is retained.',
                       'Room/detail text and continuing lines are triage evidence, not proof of wall/roof identity.',
                       'Remaining candidates require physical-object and geographic registration evidence.']}


def run(corpus,parents_feed,candidates_feed,output,*,context_options=None):
    """Retain exact source records; emit only a diagnostic landmark selection."""
    from .drawing_footprints import retained_page_candidates
    from .footprint_matching import lines
    from .mapped_alignment_checks import printed_scale_review
    from .glyph_visibility import VERSION as glyph_version
    def digest(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    contract={'version':VERSION,'glyph_version':glyph_version,'options':options(context_options),
        'parent_feed_sha256':digest(parents_feed),'candidate_feed_sha256':digest(candidates_feed)}
    output=Path(output)
    if output.exists():
        report=json.loads((output/'landmark-report.json').read_text())
        if any(report.get(k)!=v for k,v in contract.items()):raise ValueError('Landmark context inputs changed')
        for name,sha in report['output_sha256'].items():
            if digest(output/name)!=sha:raise ValueError('Landmark context output changed')
        for sha in report['source_documents']:
            if digest(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    def grouped(feed,limit):
        groups={}
        for count,row in enumerate(lines(feed),1):
            if count>100000:raise ValueError('Landmark feed budget exceeded; partition by area')
            key=(row['document_sha256'],row['page']);group=groups.setdefault(key,[])
            if len(groups)>10000 or len(group)>=limit:raise ValueError('Landmark page budget exceeded')
            group.append(row)
        return groups
    # Bounded total input keeps the grouping finite; every record is replay-checked.
    parent_pages=grouped(parents_feed,10000);candidate_pages=grouped(candidates_feed,20000)
    output.mkdir(parents=True);counts=Counter();documents=set()
    feeds=('landmark-candidates.jsonl','landmark-context.jsonl')
    streams={name:(output/(name+'.partial')).open('w') for name in feeds}
    try:
        for (sha,page_number),rows in candidate_pages.items():
            path=corpus.root/'files'/f'{sha}.pdf'
            if not re.fullmatch('[0-9a-f]{64}',sha) or digest(path)!=sha:raise ValueError('Source PDF checksum mismatch')
            parents=parent_pages.get((sha,page_number),[])
            if not parents:raise ValueError('Retained source parents required')
            retained=retained_page_candidates(corpus,parents[0])
            if parents!=retained:raise ValueError('Complete exact retained parent page required')
            cache={}
            for row in rows:
                key=(row.get('extraction_kind'),row.get('extraction_contract'))
                if key not in cache:cache[key]={r['id']:r for r in retained_page_candidates(corpus,row)}
                if cache[key].get(row['id'])!=row:raise ValueError('Candidate differs from retained extraction')
            review=printed_scale_review(path,page_number)
            with pymupdf.open(path) as doc:
                if review['status']=='one_visible_printed_scale':
                    eligible,context=page_context(doc[page_number-1],sha,page_number,parents,rows,review,context_options=contract['options'])
                else:
                    eligible=[];context={'document_sha256':sha,'page':page_number,'status':'visible_scale_required',
                        'candidate_count':len(rows),'eligible_candidates':0,'physical_identity_verified':False,'world_geometry_additions':0}
            context['printed_scale_review']=review
            counts['input_candidates']+=len(rows);counts['eligible_candidates']+=len(eligible)
            counts.update(context.get('reason_counts',{}));documents.add(sha)
            for row in eligible:streams[feeds[0]].write(json.dumps(row,sort_keys=True)+'\n')
            streams[feeds[1]].write(json.dumps(context,sort_keys=True)+'\n')
            if digest(path)!=sha:raise ValueError('Source PDF changed during context review')
        for stream in streams.values():stream.flush();os.fsync(stream.fileno())
    finally:
        for stream in streams.values():stream.close()
    if digest(parents_feed)!=contract['parent_feed_sha256'] or digest(candidates_feed)!=contract['candidate_feed_sha256']:
        raise ValueError('Landmark input feed changed')
    for name in feeds:(output/(name+'.partial')).replace(output/name)
    report={**contract,'counts':dict(counts),'pages':len(candidate_pages),'source_documents':sorted(documents),
        'output_sha256':{name:digest(output/name) for name in feeds},'physical_identity_verified':False,
        'world_geometry_additions':0,'status':'landmark_context_hints_only'}
    (output/'landmark-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
