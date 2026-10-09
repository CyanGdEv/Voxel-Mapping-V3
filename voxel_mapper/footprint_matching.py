"""Bounded footprint association and revision review queues; never generates geometry."""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from pyproj import CRS,Transformer
from shapely.geometry import Point,shape
from shapely.ops import transform
from shapely.strtree import STRtree

VERSION='footprint-matching-v1'


def name_key(value):
    return re.sub(r'^the ', '', re.sub(r'[^\w]+',' ',str(value).lower()).strip())


def descriptor(geometry):
    if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.has_z or geometry.is_empty or not geometry.is_valid:raise ValueError('Valid 2D polygon required')
    if not all(math.isfinite(v) for v in geometry.bounds):raise ValueError('Finite polygon required')
    rectangle=geometry.minimum_rotated_rectangle
    lengths=[math.dist(a,b) for a,b in zip(rectangle.exterior.coords,list(rectangle.exterior.coords)[1:])]
    return min(lengths)/max(lengths),geometry.area/rectangle.area


def references(path,source_crs,target_crs):
    target=CRS.from_user_input(target_crs)
    if not target.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in target.axis_info):raise ValueError('Projected metre target CRS required')
    data=Path(path).read_bytes();digest=hashlib.sha256(data).hexdigest();feed=json.loads(data)
    if feed.get('type')!='FeatureCollection' or len(feed['features'])>5000:raise ValueError('Reference FeatureCollection limited to 5000 objects')
    converter=Transformer.from_crs(source_crs,target,always_xy=True);rows=[];seen=set();rejected=0
    for feature in feed['features']:
        try:
            identifier=feature.get('id')
            if not isinstance(identifier,str) or not identifier or identifier in seen:raise ValueError('Unique reference identity required')
            seen.add(identifier)
            geometry=transform(converter.transform,shape(feature['geometry']));aspect,fill=descriptor(geometry)
            rows.append({'id':identifier,'name':feature.get('properties',{}).get('name',''),'geometry':geometry,'aspect':aspect,'fill':fill,'source_sha256':digest})
        except (ValueError,KeyError,TypeError,ZeroDivisionError):rejected+=1
    return rows,digest,rejected


class NativeNames:
    """One retained page at a time; only unique interior native labels qualify."""
    def __init__(self,corpus,rows):
        self.corpus=corpus;self.names={name_key(r['name']) for r in rows if r['name']};self.key=None;self.matches={};self.document=None;self.sha=None
    def get(self,candidate):
        from .drawing_footprints import retained_page_candidates
        from .drawing_page_tools import native_lines
        import pymupdf
        key=(candidate['document_sha256'],candidate['page'],candidate.get('extraction_kind'),candidate.get('extraction_contract'))
        if key!=self.key:
            sha,page=key[:2]
            if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('Invalid PDF identity')
            if sha!=self.sha:
                if self.document:self.document.close()
                path=self.corpus.root/'files'/f'{sha}.pdf'
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
                self.document=pymupdf.open(path);self.sha=sha
            retained=retained_page_candidates(self.corpus,candidate)
            candidates=[c for c in retained if c['geometry']['type'] in ('Polygon','MultiPolygon')];geometries=[shape(c['geometry']) for c in candidates];index=STRtree(geometries);self.matches={}
            labels=native_lines(self.document[page-1])
            if len(labels)>20000:raise ValueError('Native page label budget exceeded')
            for label in labels:
                key_name=name_key(label['text'])
                if key_name not in self.names:continue
                point=Point(label['local']);hits=[int(i) for i in index.query(point) if geometries[int(i)].contains(point)]
                if len(hits)==1:self.matches.setdefault(candidates[hits[0]]['id'],set()).add(key_name)
            self.retained={c['id']:c for c in retained};self.key=key
        if self.retained.get(candidate['id'])!=candidate:raise ValueError('Candidate differs from retained page extraction')
        return self.matches.get(candidate['id'],set())
    def close(self):
        if self.document:self.document.close()


def shortlist(geometry,rows,names=(),*,placed=False):
    aspect,fill=descriptor(geometry);matches=[]
    for row in rows:
        name_match=bool(row['name']) and name_key(row['name']) in names
        shape_error=abs(aspect-row['aspect'])+abs(fill-row['fill'])
        if not placed:
            if not name_match and shape_error>.08:continue
            metrics={'shape_descriptor_error':shape_error,'exact_interior_name':name_match,'area_ratio':None,'distance_m':None,'intersection_over_union':None}
            score=(0 if name_match else 1,shape_error,row['id'])
        else:
            reference=row['geometry'];distance=geometry.distance(reference)
            if distance>25:continue
            ratio=min(geometry.area,reference.area)/max(geometry.area,reference.area)
            iou=geometry.intersection(reference).area/geometry.union(reference).area
            metrics={'shape_descriptor_error':shape_error,'exact_interior_name':name_match,'area_ratio':ratio,'distance_m':distance,'intersection_over_union':iou}
            score=(-iou,-int(name_match),-ratio,shape_error,row['id'])
        matches.append((score,{'reference_id':row['id'],'name':row['name'],'source_sha256':row['source_sha256'],'metrics':metrics,'review_flags':['name_shape_disagreement'] if name_match and shape_error>.25 else []}))
    matches.sort(key=lambda item:item[0]);return [r for _,r in matches[:3]]


def reconcile(connection,feature,geometry):
    """Spatial disk index; conflicts are retained without selecting a winner."""
    left,bottom,right,top=geometry.bounds
    hits=0
    for raw, in connection.execute('SELECT records.payload FROM spatial JOIN records ON records.rowid=spatial.id WHERE minx<=? AND maxx>=? AND miny<=? AND maxy>=?',(right,left,top,bottom)):
        hits+=1
        if hits>10000:raise ValueError('Per-feature spatial comparison budget exceeded; partition the review job')
        previous=json.loads(raw)
        if previous['family']!=feature['family']:continue
        other=shape(previous['geometry']);intersection=geometry.intersection(other).area
        if intersection<=0:continue
        iou=intersection/geometry.union(other).area
        if iou<.1:continue
        a=previous.get('metadata',{});b=feature.get('metadata',{});chronology=None
        # Explicit same-sheet keys and ISO dates are evidence of ordering only.
        if a.get('sheet_key') and a.get('sheet_key')==b.get('sheet_key') and a.get('sheet_revision_reference') and b.get('sheet_revision_reference'):
            try:
                dates=[date.fromisoformat(m['issue_date']) for m in (a,b)]
                if dates[0]!=dates[1]:chronology={'later_feature_id':feature['id'] if dates[1]>dates[0] else previous['id'],'basis':'explicit same sheet key and issue date; current state still requires review'}
            except (KeyError,ValueError,TypeError):pass
        yield {'feature_ids':[previous['id'],feature['id']],'source_ids':[previous['source_id'],feature['source_id']], 'candidate_ids':[a.get('candidate_id'),b.get('candidate_id')], 'document_sha256':[a.get('document_sha256'),b.get('document_sha256')], 'intersection_over_union':iou,'classification':'duplicate_geometry' if geometry.equals(other) else 'overlapping_geometry_review','drawing_states':[a.get('drawing_state','unknown'),b.get('drawing_state','unknown')],'chronology':chronology,'selected_feature_id':None}
    cursor=connection.execute('INSERT INTO records(feature_id,payload) VALUES(?,?)',(feature['id'],json.dumps(feature)))
    connection.execute('INSERT INTO spatial VALUES(?,?,?,?,?)',(cursor.lastrowid,left,right,bottom,top))


def lines(path):
    with Path(path).open() as stream:
        for line in stream:
            if len(line)>8000000:raise ValueError('Input line budget exceeded')
            if line.strip():yield json.loads(line)


def run(candidates,reference_file,reference_crs,target_crs,output,*,corpus=None,registered_features=None,max_records=2500000):
    if type(max_records)!=int or not 1<=max_records<=2500000:raise ValueError('Record budget must be 1..2500000')
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh matching output directory')
    rows,refhash,rejected=references(reference_file,reference_crs,target_crs);output.mkdir(parents=True)
    connection=sqlite3.connect(output/'review-index.sqlite')
    connection.executescript('CREATE TABLE records(feature_id TEXT UNIQUE,payload TEXT); CREATE VIRTUAL TABLE spatial USING rtree(id,minx,maxx,miny,maxy); CREATE TABLE candidates(id TEXT PRIMARY KEY);')
    names=NativeNames(corpus,rows) if corpus else None;counts=Counter();count=0
    try:
        with (output/'associations.jsonl').open('w') as associations,(output/'revision-review.jsonl').open('w') as revisions:
            for candidate in lines(candidates):
                count+=1
                if count>max_records:raise ValueError('Record budget exceeded')
                connection.execute('INSERT INTO candidates VALUES(?)',(candidate['id'],))
                if count%1000==0:connection.commit()
                geometry=shape(candidate['geometry']);identity=hashlib.sha256((candidate['document_sha256']+'/'+str(candidate['page'])+'/'+geometry.normalize().wkb_hex).encode()).hexdigest()
                if candidate['id']!=identity or candidate.get('coordinate_frame')!='pdf_native_points_y_up':raise ValueError('Native candidate identity/frame mismatch')
                matched_names=names.get(candidate) if names else set()
                matches=shortlist(geometry,rows,matched_names)
                counts['native_candidates']+=1;counts['native_with_shortlist']+=int(bool(matches));counts['native_with_name_match']+=int(any(m['metrics']['exact_interior_name'] for m in matches))
                associations.write(json.dumps({'candidate_id':candidate['id'],'document_sha256':candidate['document_sha256'],'page':candidate['page'],'status':'unplaced_shape_name_hypotheses','matches':matches,'physical_identity_verified':False,'world_geometry_additions':0})+'\n')
            if registered_features:
                for feature in lines(registered_features):
                    count+=1
                    if count>max_records:raise ValueError('Record budget exceeded')
                    metadata=feature.get('metadata',{})
                    if CRS.from_user_input(metadata.get('geometry_crs',''))!=CRS.from_user_input(target_crs) or not metadata.get('physical_verification_reference') or not metadata.get('candidate_id'):raise ValueError('Reviewed target-frame feature records required')
                    geometry=shape(feature['geometry']);descriptor(geometry)
                    matches=shortlist(geometry,rows,{name_key(metadata.get('name',''))},placed=True)
                    associations.write(json.dumps({'feature_id':feature['id'],'candidate_id':metadata['candidate_id'],'status':'registered_overlap_hypotheses','matches':matches,'physical_identity_verified':False,'world_geometry_additions':0})+'\n');counts['registered_features']+=1
                    for decision in reconcile(connection,feature,geometry):
                        revisions.write(json.dumps(decision)+'\n');counts[decision['classification']]+=1
            connection.commit()
        report={'status':'review_queues_only','version':VERSION,'counts':dict(counts),'reference_polygons':len(rows),'rejected_nonpolygon_or_invalid_references':rejected,'reference_sha256':refhash,'target_crs':target_crs,'reference_crs':reference_crs,'native_names_enabled':corpus is not None,'max_records':max_records,'world_geometry_additions':0,'limitations':['Unplaced shape descriptors cannot establish location, absolute size or identity','Mapped references are comparison evidence, not independent survey verification','No automatic latest-revision, existing-state, reuse or material acceptance']}
        for key,path in [('candidate_sha256',candidates),('registered_features_sha256',registered_features)]:
            if path:
                with Path(path).open('rb') as stream:report[key]=hashlib.file_digest(stream,'sha256').hexdigest()
        for filename in ('associations.jsonl','revision-review.jsonl'):
            with (output/filename).open('rb') as stream:report[filename+'_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
        (output/'matching-report.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:
        if names:names.close()
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('candidates','references','reference-crs','target-crs','output'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--registered-features');parser.add_argument('--corpus');args=parser.parse_args()
    from .planning_bulk import Corpus
    corpus=Corpus(args.corpus) if args.corpus else None
    try:print(json.dumps(run(args.candidates,args.references,args.reference_crs,args.target_crs,args.output,corpus=corpus,registered_features=args.registered_features),indent=2))
    finally:
        if corpus:corpus.close()

if __name__=='__main__':main()
