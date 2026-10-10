"""Exact, source-traceable enclosed faces from solid straight planning linework."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

from shapely.geometry import LineString,mapping,shape
from shapely.ops import polygonize_full,unary_union
from shapely.strtree import STRtree

from .drawing_components import split_page
from .boundary_registration import file_hash

VERSION='linework-boundaries-v1'
DEFAULTS={'max_segments':20000,'max_intersection_pairs':100000,'max_faces':4000,'max_noded_points':200000}


def options(values=None):
    result={**DEFAULTS,**(values or {})}
    if set(result)!=set(DEFAULTS) or any(type(v) is not int or not 1<=v<=DEFAULTS[k] for k,v in result.items()):raise ValueError('Bounded linework recovery options required')
    return result


def identity(parent_contract,opts):
    return hashlib.sha256(json.dumps({'version':VERSION,'parent_contract':parent_contract,'options':opts,'provenance_epsilon_pdf_points':1e-7},sort_keys=True).encode()).hexdigest()


def recover_page(parents,*,recovery_options=None):
    opts=options(recovery_options);components=split_page(parents);lines=[];segments=[];counts=Counter()
    for c in components:
        if c['geometry']['type']!='LineString':continue
        if c['curve_approximation']['cubic_segments']:counts['curved_lines_deferred']+=1;continue
        paints=c['paint_references']
        if not paints or c.get('paint_reference_truncated') or any(not isinstance(p['stroke_style'].get('dashes_pdf'),str) or not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',p['stroke_style']['dashes_pdf']) for p in paints):counts['dashed_or_unknown_lines_deferred']+=1;continue
        g=shape(c['geometry']);lines.append((c,g))
        for a,b in zip(g.coords,list(g.coords)[1:]):
            if a!=b:segments.append(LineString([a,b]))
            if len(segments)>opts['max_segments']:return components,{'status':'network_budget_withheld','reason':'segment_budget','counts':dict(counts),'recovered_faces':0}
    counts['solid_straight_lines']=len(lines);counts['segments']=len(segments)
    if not segments:return components,{'status':'no_eligible_linework','counts':dict(counts),'recovered_faces':0}
    index=STRtree(segments);pairs=0
    for i,g in enumerate(segments):
        pairs+=sum(int(j)>i for j in index.query(g,predicate='intersects'))
        if pairs>opts['max_intersection_pairs']:return components,{'status':'network_budget_withheld','reason':'intersection_pair_budget','counts':dict(counts),'recovered_faces':0}
    counts['intersection_pairs']=pairs;network=unary_union(segments)
    parts=list(network.geoms) if hasattr(network,'geoms') else [network]
    if sum(len(g.coords) for g in parts)>opts['max_noded_points']:return components,{'status':'network_budget_withheld','reason':'noded_point_budget','counts':dict(counts),'recovered_faces':0}
    faces,cuts,dangles,invalid=polygonize_full(network);counts.update(cut_edges=len(cuts.geoms),dangles=len(dangles.geoms),invalid_rings=len(invalid.geoms))
    if len(faces.geoms)>opts['max_faces']:return components,{'status':'network_budget_withheld','reason':'face_budget','counts':dict(counts),'recovered_faces':0}
    source_index=STRtree([g for _,g in lines]);seen={c['id'] for c in components};recovered=[]
    for face in sorted(faces.geoms,key=lambda g:g.normalize().wkb_hex):
        if face.area<16:counts['small_faces_deferred']+=1;continue
        if len(face.exterior.coords)+sum(len(r.coords) for r in face.interiors)>10000:counts['face_vertex_budget']+=1;continue
        boundary=face.boundary;links=[];coverage=[];paints=[];ancestor_contract=parents[0]['extraction_contract']
        for i in source_index.query(boundary.buffer(1e-7)):
            c,g=lines[int(i)];length=g.buffer(1e-7,cap_style=2).intersection(boundary).length
            if length<=1e-6:continue
            links.append({'candidate_id':c['id'],'extraction_contract':c['extraction_contract'],'boundary_length_pdf_points':length,'raw_parent_references':c['parent_references']});coverage.append(g)
            for p in c['paint_references']:
                if p not in paints:paints.append(p)
        if len(links)>256 or len(paints)>256:counts['provenance_budget_deferred']+=1;continue
        # Buffer only compensates floating-point overlay in provenance checks.
        # It never participates in joining or polygonizing the source network.
        if not coverage or not unary_union(coverage).buffer(1e-7).covers(boundary):counts['incomplete_source_coverage']+=1;continue
        sha,page=parents[0]['document_sha256'],parents[0]['page'];digest=hashlib.sha256((sha+'/'+str(page)+'/'+face.normalize().wkb_hex).encode()).hexdigest()
        if digest in seen:counts['existing_polygon_duplicates']+=1;continue
        if len(components)+len(recovered)>=20000:counts['combined_page_budget_deferred']+=1;continue
        seen.add(digest);links.sort(key=lambda p:p['candidate_id']);record={'id':digest,'document_sha256':sha,'page':page,'geometry':json.loads(json.dumps(mapping(face))),'coordinate_frame':'pdf_native_points_y_up','extraction_kind':'linework_boundaries','extraction_version':VERSION,'extraction_contract':identity(ancestor_contract,opts),'parent_extraction_contract':ancestor_contract,'recovery_options':opts,'provenance_comparison_epsilon_pdf_points':1e-7,'line_parent_references':links,'paint_references':paints,'curve_approximation':{'method':'exact_straight_line_network','cubic_segments':0,'chord_error_bound_pdf_points':0},'rendering_status':'derived_enclosed_linework_face; fill_and_visibility_unverified','semantic_status':'unclassified_enclosed_face','physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0};recovered.append(record)
    counts['recovered_faces']=len(recovered)
    return components+recovered,{'status':'enclosed_faces_only','counts':dict(counts),'recovered_faces':len(recovered)}


def retained_boundaries(corpus,candidate):
    from .drawing_geometry import VERSION as parent_version
    opts=options(candidate.get('recovery_options'));contract=candidate.get('parent_extraction_contract')
    if candidate.get('extraction_version')!=VERSION or candidate.get('extraction_contract')!=identity(contract,opts):raise ValueError('Current linework recovery contract required')
    row=corpus.db.execute('SELECT result FROM geometry_pages WHERE sha=? AND page=? AND version=? AND contract=?',(candidate['document_sha256'],candidate['page'],parent_version,contract)).fetchone()
    if not row:raise ValueError('Retained linework parents required')
    return recover_page(json.loads(row[0])['candidates'],recovery_options=opts)[0]


def run(corpus,candidates,output,*,sheets=None,recovery_options=None,max_records=2500000):
    from .drawing_footprints import retained_page_candidates
    from .footprint_matching import lines
    opts=options(recovery_options)
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    if sheets is not None and (not isinstance(sheets,list) or len(sheets)>10000 or any(not isinstance(s,list) or len(s)!=2 or not re.fullmatch('[0-9a-f]{64}',str(s[0])) or type(s[1]) is not int or s[1]<1 for s in sheets)):raise ValueError('Bounded source page selection required')
    contract={'version':VERSION,'source_candidate_sha256':file_hash(candidates),'options':opts,'provenance_comparison_epsilon_pdf_points':1e-7,'sheets':sheets,'max_records':max_records};output=Path(output)
    if output.exists():
        if not (output/'boundary-report.json').exists():raise ValueError('Incomplete boundary recovery output; use a fresh directory')
        report=json.loads((output/'boundary-report.json').read_text())
        if any(report.get(k)!=v for k,v in contract.items()):raise ValueError('Boundary recovery inputs changed')
        for name,digest in report['output_sha256'].items():
            if file_hash(output/name)!=digest:raise ValueError('Boundary recovery output changed')
        for sha in report['source_documents']:
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        return report
    output.mkdir(parents=True);selection=None if sheets is None else {tuple(s) for s in sheets};counts=Counter();pages=[];seen=set();parents=[];key=None;total=0;documents=set()
    feeds=('boundary-candidates.jsonl','polygon-candidates.jsonl','page-recovery.jsonl');streams={name:(output/(name+'.partial')).open('w') for name in feeds}
    def emit():
        nonlocal total
        if not parents:return
        sha,page=parents[0]['document_sha256'],parents[0]['page']
        if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        retained=retained_page_candidates(corpus,parents[0]);by_id={p['id']:p for p in retained}
        if len(parents)!=len(by_id) or {p['id'] for p in parents}!=set(by_id) or any(by_id.get(p['id'])!=p for p in parents):raise ValueError('Complete exact retained parent page required')
        records,result=recover_page(retained,recovery_options=opts);documents.add(sha);pages.append((sha,page));counts.update(result['counts']);counts[result['status']]+=1;result.update(document_sha256=sha,page=page);streams['page-recovery.jsonl'].write(json.dumps(result)+'\n')
        for record in records:
            total+=1
            if total>max_records:raise ValueError('Boundary recovery record budget exceeded')
            encoded=json.dumps(record,sort_keys=True)+'\n';streams['boundary-candidates.jsonl'].write(encoded)
            if record['geometry']['type']=='Polygon':streams['polygon-candidates.jsonl'].write(encoded)
    try:
        for count,parent in enumerate(lines(candidates),1):
            if count>2500000:raise ValueError('Parent record budget exceeded')
            current=(parent['document_sha256'],parent['page'],parent['extraction_contract'])
            if current!=key:
                emit();parents=[]
                if current in seen or len(seen)>=10000:raise ValueError('Bounded grouped parent pages required')
                seen.add(current);key=current
            if selection is not None and current[:2] not in selection:continue
            if len(parents)>=10000:raise ValueError('Parent page budget exceeded')
            parents.append(parent)
        emit()
        for stream in streams.values():stream.flush();os.fsync(stream.fileno())
    finally:
        for stream in streams.values():stream.close()
    if file_hash(candidates)!=contract['source_candidate_sha256']:raise ValueError('Parent feed changed')
    for name in feeds:(output/(name+'.partial')).replace(output/name)
    report={**contract,'pages':len(pages),'records':total,'counts':dict(counts),'source_documents':sorted(documents),'output_sha256':{name:file_hash(output/name) for name in feeds},'world_geometry_additions':0,'limitations':['Enclosed linework is not a verified physical footprint or fill','No endpoint snapping, gap filling or automatic state/material acceptance','Curved and dashed lines are withheld from recovery']}
    (output/'boundary-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','candidates','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--sheets');a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.candidates,a.output,sheets=json.loads(Path(a.sheets).read_text()) if a.sheets else None),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
