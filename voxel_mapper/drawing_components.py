"""Traceable disconnected paint components for object-level alignment review."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

from shapely.geometry import mapping,shape

VERSION='drawing-components-v1'


def identity(parent_contract):
    return hashlib.sha256(json.dumps({'version':VERSION,'parent_contract':parent_contract,'max_page_components':20000},sort_keys=True).encode()).hexdigest()


def split_page(parents):
    """Preserve holes and source paints; merge equal parts without losing parents."""
    from .drawing_geometry import VERSION as parent_version
    if len(parents)>10000:raise ValueError('Parent page candidate budget exceeded')
    if len({(p['document_sha256'],p['page'],p['extraction_contract']) for p in parents})>1:raise ValueError('One source page and parent contract required')
    result={}
    for parent in parents:
        if parent.get('extraction_kind')!='drawing_geometry' or parent.get('extraction_version')!=parent_version:raise ValueError('Current geometry parents required')
        geom=shape(parent['geometry']);parts=list(geom.geoms) if geom.geom_type=='MultiPolygon' else [geom]
        for index,part in enumerate(parts):
            if part.is_empty or not part.is_valid or part.geom_type not in ('Polygon','LineString'):raise ValueError('Invalid component geometry')
            sha,page=parent['document_sha256'],parent['page'];digest=hashlib.sha256((sha+'/'+str(page)+'/'+part.normalize().wkb_hex).encode()).hexdigest()
            link={'candidate_id':parent['id'],'component_index':index if geom.geom_type=='MultiPolygon' else None,'extraction_contract':parent['extraction_contract']}
            if digest not in result:
                if len(result)>=20000:raise ValueError('Component page budget exceeded')
                record=copy.deepcopy(parent);record.update(id=digest,geometry=json.loads(json.dumps(mapping(part))),extraction_kind='drawing_components',extraction_version=VERSION,extraction_contract=identity(parent['extraction_contract']),parent_references=[],component_semantics_verified=False)
                result[digest]=record
            record=result[digest]
            if len(record['parent_references'])>=256:raise ValueError('Component parent reference budget exceeded')
            record['parent_references'].append(link)
            if len(record['parent_references'])>1:
                for paint in parent['paint_references']:
                    if paint not in record['paint_references']:
                        if len(record['paint_references'])>=256:record['paint_reference_truncated']=True;break
                        record['paint_references'].append(copy.deepcopy(paint))
                record['paint_reference_truncated']=record.get('paint_reference_truncated',False) or parent.get('paint_reference_truncated',False)
                for key in ('cubic_segments','chord_error_bound_pdf_points'):
                    record['curve_approximation'][key]=max(record['curve_approximation'][key],parent['curve_approximation'][key])
                if parent['curve_approximation']['cubic_segments']:record['rendering_status']=record['rendering_status'].replace('supported_straight','supported_curved')
    return list(result.values())


def retained_components(corpus,candidate):
    from .drawing_geometry import VERSION as parent_version
    if candidate.get('extraction_version')!=VERSION or not candidate.get('parent_references'):raise ValueError('Current component parents required')
    contracts={p['extraction_contract'] for p in candidate['parent_references']}
    if len(contracts)!=1:raise ValueError('One retained parent contract required')
    contract=next(iter(contracts))
    if candidate['extraction_contract']!=identity(contract):raise ValueError('Component contract changed')
    row=corpus.db.execute('SELECT result FROM geometry_pages WHERE sha=? AND page=? AND version=? AND contract=?',(candidate['document_sha256'],candidate['page'],parent_version,contract)).fetchone()
    if not row:raise ValueError('Retained parent page required')
    return split_page(json.loads(row[0])['candidates'])


def run(corpus,candidates,output,*,max_records=2500000):
    from .drawing_footprints import retained_page_candidates
    from .footprint_matching import lines
    from .boundary_registration import file_hash
    if type(max_records) is not int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);source_hash=file_hash(candidates)
    counts=Counter();key=None;parents=[];parent_ids=set();seen=set();pages=0;total=0
    streams={kind:(output/(kind+'-candidates.jsonl.partial')).open('w') for kind in ('component','polygon','line')}
    def emit():
        nonlocal total,pages
        if not parents:return
        sha,page=parents[0]['document_sha256'],parents[0]['page']
        if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Source PDF checksum mismatch')
        retained={c['id']:c for c in retained_page_candidates(corpus,parents[0])}
        if {p['id'] for p in parents}!=set(retained):raise ValueError('Complete retained parent page required')
        if any(retained.get(c['id'])!=c for c in parents):raise ValueError('Parent differs from retained extraction')
        records=split_page(parents);counts['multipart_parents']+=sum(c['geometry']['type']=='MultiPolygon' for c in parents);counts['parent_records']+=len(parents);pages+=1
        for record in records:
            total+=1
            if total>max_records:raise ValueError('Component record budget exceeded')
            kind='line' if record['geometry']['type']=='LineString' else 'polygon';counts[kind]+=1
            encoded=json.dumps(record,sort_keys=True)+'\n';streams['component'].write(encoded);streams[kind].write(encoded)
    try:
        for parent in lines(candidates):
            current=(parent['document_sha256'],parent['page'],parent['extraction_contract'])
            if current!=key:
                emit();parents=[];parent_ids=set()
                if current in seen:raise ValueError('Parent feed must be grouped by page/contract')
                if len(seen)>=10000:raise ValueError('Component page budget exceeded')
                seen.add(current);key=current
            if len(parents)>=10000:raise ValueError('Parent page candidate budget exceeded')
            if parent['id'] in parent_ids:raise ValueError('Duplicate parent candidate')
            parent_ids.add(parent['id'])
            parents.append(parent)
        emit()
    finally:
        for stream in streams.values():stream.close()
    if file_hash(candidates)!=source_hash:raise ValueError('Parent feed changed during decomposition')
    for kind in streams:(output/(kind+'-candidates.jsonl.partial')).replace(output/(kind+'-candidates.jsonl'))
    report={'version':VERSION,'source_candidate_sha256':source_hash,'pages':pages,'components':total,'counts':dict(counts),'max_records':max_records,'file_sha256':{kind:file_hash(output/(kind+'-candidates.jsonl')) for kind in streams},'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}
    (output/'component-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('corpus','candidates','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.candidates,a.output),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
