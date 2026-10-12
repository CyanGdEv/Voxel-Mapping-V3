"""Discover explicit station tables and bind them to native leader-mark evidence.

Printed station coordinates are proposals. Only separately verified survey
source policies can release them into the qualification reference registry.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import pymupdf
from pypdf import PdfReader
from pyproj import CRS
from shapely.geometry import LineString,box
from shapely.strtree import STRtree
from .coordinate_text import coordinate_runs
from .drawing_marks import extract_marks, mark_for_label
from .drawing_page_tools import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_span, VERSION as GLYPH_VERSION
from .survey_context import inspect_survey_context, VERSION as CONTEXT_VERSION
from .survey_reference import inspect_reference_notes
from .evidence_memory import EvidenceMemory, identity
from .generation_cycles import atomic_json, file_hash

VERSION='survey-station-discovery-v1'
NUMBER=r'[+-]?\d{1,9}(?:\.\d{1,6})?'
ROW=re.compile(r'^CP:([A-Za-z0-9_.-]{1,64})\s+E=('+NUMBER+r')\s+N=('+NUMBER+r')(?:\s+Z=('+NUMBER+r'))?$')
MARK=re.compile(r'^CP:([A-Za-z0-9_.-]{1,64})$')
EPSG=re.compile(r'^EPSG\s*:\s*(\d{4,6})$',re.I)


class SourcePages:
    """Keep at most one original PDF pair open across its consecutive pages."""
    def __init__(self):self.path=None;self.rendered=None;self.native=None
    def __enter__(self):return self
    def __exit__(self,*args):
        if self.rendered:self.rendered.close()
    def get(self,path,number):
        if path!=self.path:
            if self.rendered:self.rendered.close()
            self.rendered=None;self.path=None
            document=pymupdf.open(path)
            if len(document)>1000:document.close();raise ValueError('Bounded station PDF page required')
            self.rendered=document;self.native=PdfReader(path);self.path=path
        if not 1<=number<=len(self.rendered):raise ValueError('Bounded station PDF page required')
        return self.native.pages[number-1],self.rendered[number-1]


def inspect_page(native, rendered, sha, page):
    text=rendered.get_text()
    if len(text)>500000:raise ValueError('Survey page text budget exceeded')
    context=inspect_survey_context(text);notes=inspect_reference_notes(text)
    report={'version':VERSION,'document_sha256':sha,'page':page,'status':'station_candidates_only',
        'survey_context':context,'reference_notes':notes,'candidates':[],
        'visible_epsg_candidates':[],'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}
    content=native.get_contents()
    if content is not None and any(op in (b'BMC',b'BDC') or (op==b'Tr' and int(args[0])==3) for args,op in content.operations):
        return {**report,'status':'withheld_visibility_adapter','reason':'Invisible/layered native coordinate text'}
    try:runs=coordinate_runs(native)
    except ValueError as error:return {**report,'status':'unsupported_native_coordinate_text','reason':str(error)}
    tables={};marks={};declarations=[]
    for run in runs:
        label=run['text'].strip()
        if match:=ROW.fullmatch(label):tables.setdefault(match[1],[]).append((match,run))
        elif match:=MARK.fullmatch(label):marks.setdefault(match[1],[]).append(run)
        elif match:=EPSG.fullmatch(label):declarations.append((int(match[1]),run))
    if sum(len(v) for v in tables.values())>64 or sum(len(v) for v in marks.values())>64 or len(declarations)>16:
        raise ValueError('Survey station/CRS label budget exceeded')
    if not tables and not declarations:return report
    traces=rendered.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:raise ValueError('Survey glyph budget exceeded')
    glyphs={};inverse=native_inverse(rendered)
    for glyph in label_runs(traces):
        label=''.join(chr(c[0]) for c in glyph['chars']).strip()
        if ROW.fullmatch(label) or MARK.fullmatch(label) or EPSG.fullmatch(label):glyphs.setdefault(label,[]).append(glyph)
    def visible(run):
        matches=glyphs.get(run['text'].strip(),[])
        if len(matches)!=1:return False
        glyph=matches[0];point=pymupdf.Point(glyph['chars'][0][2])*inverse
        if math.dist([point.x,point.y],run['origin'])>1e-4:return False
        return screen_span(rendered,glyph,zoom=24 if glyph['size']<4 else 6)['status']=='raster_consistent_candidate'
    report['visible_epsg_candidates']=sorted({code for code,run in declarations if visible(run)})
    attachments=extract_marks(native,reuse_allowed=True)
    # Retain only source strokes that remain visible after subsequent fills.
    # Glyph visibility alone cannot establish that a leader or crosshair survived.
    paths=rendered.get_drawings(extended=True);paints=rendered.get_bboxlog()
    if len(paths)>100000 or len(paints)>500000:raise ValueError('Survey attachment paint budget exceeded')
    strokes={};fills=[]
    def segment_key(segment):return tuple(sorted(tuple(round(v,4) for v in point) for point in segment))
    for path in paths:
        if (path['type'] not in ('s','fs') or path.get('stroke_opacity',1)<.95
                or not path.get('color') or min(path['color'])>.95):continue
        for item in path['items']:
            if item[0]!='l':continue
            segment=[]
            for point in item[1:3]:
                p=point*inverse;segment.append([p.x,p.y])
            strokes.setdefault(segment_key(segment),[]).append(path['seqno'])
    for seq,(kind,bounds) in enumerate(paints):
        if kind not in ('fill-path','fill-image','fill-shade'):continue
        rectangle=pymupdf.Rect(bounds)*inverse
        fills.append((seq,box(rectangle.x0,rectangle.y0,rectangle.x1,rectangle.y1)))
    fill_index=STRtree([g for _,g in fills]) if fills else None
    def attachment_visible(point,run):
        found=[m for m in attachments.get('marks',[]) if math.dist(m['page_point'],point)<1e-6]
        if len(found)!=1:return False
        required=set(found[0]['stroke_indices'])
        for i,segment in enumerate(attachments.get('segments',[])):
            if i in required:continue
            if any(math.dist(start,run['origin'])<=1 and math.dist(end,point)<1e-6 for start,end in (segment,segment[::-1])):
                required.add(i)
        if len(required)<3:return False
        for i in required:
            segment=attachments['segments'][i];sequences=strokes.get(segment_key(segment),[])
            if len(sequences)!=1:return False
            overlaps=[] if fill_index is None else fill_index.query(LineString(segment),predicate='intersects')
            if any(fills[int(j)][0]>sequences[0] for j in overlaps):return False
        return True
    for station,rows in sorted(tables.items()):
        record={'station_id':station,'document_sha256':sha,'page':page,
            'coordinate_frame':'pdf_native_points_y_up','status':'withheld_ambiguous_station_identity',
            'registration_verified':False,'world_geometry_additions':0}
        if len(rows)==1 and len(marks.get(station,[]))==1:
            match,row=rows[0];mark=marks[station][0]
            if visible(row) and visible(mark):
                point=mark_for_label(attachments,mark['origin'])
                if point is not None and attachment_visible(point,mark):
                    record.update(status='source_bound_station_coordinate_candidate',local=point,
                        target=[float(match[2]),float(match[3])],printed_level=float(match[4]) if match[4] else None,
                        table_text=row['text'],table_text_origin=row['origin'],mark_text_origin=mark['origin'],
                        attachment_visibility_status='unique_source_strokes_without_later_covering_fill')
                elif point is not None:record['status']='withheld_station_attachment_visibility'
                else:record['status']='withheld_missing_unique_leader_mark'
            else:record['status']='withheld_station_glyph_visibility'
        elif len(rows)==1 and not marks.get(station):record['status']='withheld_missing_station_mark'
        report['candidates'].append(record)
    return report


def survey_references(page, policies):
    """Release a bounded table only under a reviewed source policy, never by score."""
    eligible=[s for s in policies if s.get('kind')=='survey' and s.get('sha256')==page['document_sha256']]
    if len(eligible)!=1:return [],'awaiting_unique_verified_survey_policy'
    source=eligible[0];metadata=source.get('metadata',{})
    required={'physical_landmarks_verified':True,'station_coordinate_identity_verified':True,
              'station_coordinate_table_contract':'explicit_cp_en_station_table_v1','reuse_allowed':True}
    if (source.get('registration_status')!='accepted' or any(metadata.get(k)!=v for k,v in required.items())
            or source.get('license')=='copyright-consultation-only' or metadata.get('reuse_status')=='consultation_only'
            or not isinstance(metadata.get('station_verification_reference'),str) or not metadata['station_verification_reference'].strip()):
        return [],'awaiting_verified_station_identity_and_reuse_policy'
    scope=metadata.get('station_pages');accuracy=metadata.get('reference_accuracy_m');role=metadata.get('station_reference_role')
    if (not isinstance(scope,list) or not 1<=len(scope)<=1000 or any(type(p) is not int or p<1 for p in scope)
            or len(set(scope))!=len(scope) or page['page'] not in scope
            or type(accuracy) not in (int,float) or not math.isfinite(accuracy) or not 0<=accuracy<=1
            or role not in ('control','checkpoint')):
        return [],'awaiting_source_bound_station_scope_accuracy_and_role'
    crs=CRS.from_user_input(source['crs'])
    if (not crs.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in crs.axis_info[:2])
            or page['visible_epsg_candidates']!=[crs.to_epsg()]):return [],'awaiting_visible_matching_projected_crs'
    if page['survey_context']['restriction_flags'] or page['reference_notes']['arbitrary_coordinate_warning']:
        return [],'withheld_local_or_restricted_survey_grid'
    if page['status']!='station_candidates_only':return [],'withheld_unsupported_station_page'
    refs=[]
    for candidate in page['candidates']:
        if candidate['status']!='source_bound_station_coordinate_candidate':continue
        refs.append({'id':candidate['station_id'],'target':candidate['target'],'source_id':source['id'],
            'role':role,'accuracy_m':accuracy,'document_sha256':source['sha256'],'page':page['page'],
            'candidate_sha256':identity(candidate),'verification_reference':metadata['station_verification_reference']})
    return refs,'verified_policy_station_references' if refs else 'awaiting_supported_attached_station_coordinates'


def input_contract(config,resolve):
    settings=config.get('survey_landmark_discovery',{})
    automatic=config.get('automatic_reconstruction',{})
    enabled=settings.get('enabled',config.get('registration_qualification',{}).get('enabled',automatic.get('enabled',False)))
    if not enabled:return None
    manifest=settings.get('manifest',config.get('registration_qualification',{}).get('manifest',automatic.get('manifest')))
    return {'version':VERSION,'glyph_version':GLYPH_VERSION,'context_version':CONTEXT_VERSION,
            'manifest_sha256':file_hash(resolve(manifest)) if manifest else None}


def run(corpus,geometry,store,output,*,manifest=None,max_pages=1000):
    if type(max_pages) is not int or not 1<=max_pages<=10000:raise ValueError('Bounded survey discovery page budget required')
    extraction=json.loads((Path(geometry)/'geometry-report.json').read_text())
    pages=corpus.db.execute('SELECT sha,page FROM geometry_pages WHERE version=? AND contract=? ORDER BY sha,page',
        (extraction['version'],extraction['contract'])).fetchall()
    if len(pages)!=extraction['pages'] or len(pages)>max_pages:raise ValueError('Survey discovery page inventory/budget changed')
    policies=json.loads(Path(manifest).read_text())['sources'] if manifest else []
    if len(policies)>10000 or len({s['id'] for s in policies})!=len(policies):raise ValueError('Distinct bounded station source policies required')
    pin=file_hash(manifest) if manifest else None
    contract={'version':VERSION,'glyph_version':GLYPH_VERSION,'context_version':CONTEXT_VERSION,
              'source_pages':pages,'manifest_sha256':pin,'max_pages':max_pages}
    output=Path(output)/identity(contract);records=[];refs=[];facts=[];computed=reused=0
    with EvidenceMemory(store) as memory,SourcePages() as opened:
        for sha,number in pages:
            path=corpus.root/'files'/f'{sha}.pdf'
            if not re.fullmatch('[0-9a-f]{64}',sha) or file_hash(path)!=sha:raise ValueError('Survey source PDF checksum mismatch')
            policy=[s for s in policies if s.get('sha256')==sha]
            parents=[memory.put('source_policy',s,s) for s in policy]
            inputs={'version':VERSION,'glyph_version':GLYPH_VERSION,'context_version':CONTEXT_VERSION,
                    'document_sha256':sha,'page':number,'source_policy_sha256':identity(policy)}
            cached=memory.get('survey_station_page',inputs,parents)
            if cached is not None:record=cached['payload'];reused+=1
            else:
                native,rendered=opened.get(path,number)
                record=inspect_page(native,rendered,sha,number)
                references,status=survey_references(record,policy)
                record.update(reference_status=status,survey_references=references);computed+=1
            identifier=memory.put('survey_station_page',inputs,record,parents)
            records.append(record);refs.extend(record['survey_references']);facts.append({'id':identifier,'inputs':inputs,'parents':parents})
        # Repeated identities cannot be resolved by proximity or by picking a revision.
        counts=Counter(r['id'] for r in refs);ambiguous=sorted(k for k,v in counts.items() if v>1)
        refs=sorted((r for r in refs if counts[r['id']]==1),key=lambda r:r['id'])
        if len(refs)>1000:raise ValueError('Survey reference registry budget exceeded')
        payload=''.join(json.dumps(r,sort_keys=True)+'\n' for r in records)
        if len(payload.encode())>128000000:raise ValueError('Station discovery output byte budget exceeded')
        from hashlib import sha256
        hashes={'station-pages.jsonl':sha256(payload.encode()).hexdigest(),'survey-references.json':identity({'landmarks':refs})}
        report={'contract':contract,'run_id':output.name,'pages':len(records),
            'page_statuses':dict(Counter(r['status'] for r in records)),
            'reference_statuses':dict(Counter(r['reference_status'] for r in records)),
            'station_candidates':sum(len(r['candidates']) for r in records),
            'reference_count':len(refs),'ambiguous_station_ids':ambiguous,'page_facts':facts,
            'output_sha256':hashes,'references_file':str((output/'survey-references.json').resolve()),
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}
        if output.exists():
            old=json.loads((output/'station-report.json').read_text())
            if (old!=json.loads(json.dumps(report)) or file_hash(output/'station-pages.jsonl')!=hashes['station-pages.jsonl']
                    or identity(json.loads((output/'survey-references.json').read_text()))!=hashes['survey-references.json']):
                raise ValueError('Station discovery output changed')
        else:
            output.mkdir(parents=True);(output/'station-pages.jsonl').write_text(payload)
            atomic_json(output/'survey-references.json',{'landmarks':refs})
        for sha in {s for s,_ in pages}:
            if file_hash(corpus.root/'files'/f'{sha}.pdf')!=sha:raise ValueError('Survey source PDF changed')
        if manifest and file_hash(manifest)!=pin:raise ValueError('Survey source policy changed')
        for fact in facts:
            if memory.get('survey_station_page',fact['inputs'],fact['parents']) is None:raise ValueError('Survey evidence changed')
        atomic_json(output/'station-report.json',report)
        return {**report,'run_pages':computed,'reused_pages':reused}


def main():
    from .planning_bulk import Corpus
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('corpus','geometry','store','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--manifest');args=parser.parse_args();corpus=Corpus(args.corpus)
    try:
        report=run(corpus,args.geometry,args.store,args.output,manifest=args.manifest)
        print(json.dumps({k:report[k] for k in ('pages','station_candidates','reference_count','page_statuses','run_pages','reused_pages')}))
    finally:corpus.close()


if __name__=='__main__':main()
