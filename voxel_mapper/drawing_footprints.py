"""Native-sheet polygon candidates and explicitly reviewed reconstruction records."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from shapely.geometry import Polygon,LineString,Point,box,shape,mapping
from shapely.ops import polygonize,unary_union
from shapely.strtree import STRtree
from .drawing_page_tools import native_inverse,native_lines
from .reconstruction.registration import apply_registration,review_registration
from .reconstruction.model import Feature,Source

VERSION='footprint-candidates-v2'
FAMILIES={'path':r'\b(path|footpath|walkway|paving)\b','plaza':r'\bplaza\b','building_shell':r'\b(building|station|shop|house|toilets)\b','lake':r'\b(lake|pond|water)\b'}


def rings_from_path(path,matrix,max_points=10000):
    import pymupdf
    rings=[];current=[];count=0
    def point(value):
        nonlocal count
        count+=1
        if count>max_points:raise ValueError('Paint-group point budget exceeded')
        p=pymupdf.Point(value)*matrix
        if not math.isfinite(p.x) or not math.isfinite(p.y):raise ValueError('Nonfinite path point')
        return (p.x,p.y)
    def flush():
        nonlocal current
        if current:rings.append(current);current=[]
    for item in path['items']:
        if item[0]=='l':
            start,end=point(item[1]),point(item[2])
            if current and math.dist(current[-1],start)>1e-5:flush()
            if not current:current=[start]
            current.append(end)
        elif item[0]=='re':
            flush();rect=pymupdf.Rect(item[1]);corners=[rect.tl,rect.tr,rect.br,rect.bl]
            if item[2]<0:corners.reverse()
            ring=[point(p) for p in corners];rings.append(ring+[ring[0]])
        else:raise ValueError('Curved or unsupported paint-group geometry')
    flush()
    if not rings:raise ValueError('No polygon rings')
    for i,ring in enumerate(rings):
        if ring[0]!=ring[-1]:
            if 'f' in path['type'] or (path.get('closePath') and i==len(rings)-1):ring.append(ring[0])
            else:raise ValueError('Open stroked path; not a footprint')
        if len(ring)<4 or not Polygon(ring).is_valid or Polygon(ring).area<=0:raise ValueError('Invalid ring topology')
    return rings


def fill_geometry(rings,even_odd,filled):
    polygons=[Polygon(r) for r in rings]
    if not filled:
        if len(polygons)!=1:raise ValueError('Compound stroked outlines need topology review')
        return polygons[0]
    if even_odd:
        result=polygons[0]
        for polygon in polygons[1:]:result=result.symmetric_difference(polygon)
        return result
    # Native nonzero winding: classify bounded arrangement faces by signed
    # ring membership. Nesting is not blindly treated as a hole.
    orientations=[1 if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:]))>0 else -1 for r in rings]
    faces=list(polygonize(unary_union([p.boundary for p in polygons])))
    return unary_union([face for face in faces if sum(sign for p,sign in zip(polygons,orientations) if p.contains(face.representative_point()))!=0])


def extract_page(page,sha,page_number,*,max_paths=100000,max_candidates=2000,max_points=10000):
    import pymupdf
    matrix=native_inverse(page);crop=pymupdf.Rect(page.rect)
    # Page.rect follows display rotation; the unrotated visible frame is the
    # cropbox-sized sheet. Obtain its native frame through restored rotation.
    angle=page.rotation
    try:
        page.set_rotation(0);crop=page.rect;native_crop=crop*~page.transformation_matrix
    finally:page.set_rotation(angle)
    frame=box(*native_crop);paths=page.get_cdrawings(extended=True);reasons=Counter();candidates=[];seen={};clips=[];groups=[]
    text_masks=[]
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                rect=pymupdf.Rect(span['bbox'])*matrix;text_masks.append(box(*rect).buffer(.5))
    masks=STRtree(text_masks) if text_masks else None
    if len(paths)>max_paths:return [],{'status':'path_budget_withheld','raw_paths':len(paths),'reason':'Native drawing path budget exceeded'}
    for ordinal,path in enumerate(paths):
        level=path.get('level',0)
        clips=[c for c in clips if c['level']<level];groups=[g for g in groups if g<level]
        if path['type']=='clip':
            try:
                geometry=fill_geometry(rings_from_path({**path,'type':'f'},matrix,max_points),path.get('even_odd',False),True)
                if not geometry.equals(box(*geometry.bounds)):raise ValueError('Nonrectangular clip')
            except (ValueError,TypeError,KeyError):geometry=None
            clips.append({'level':level,'geometry':geometry});continue
        if path['type']=='group':groups.append(level);continue
        if any(c['geometry'] is None for c in clips) or groups:reasons['unsupported_clipping_or_compositing_scope']+=1;continue
        if path.get('layer'):reasons['optional_layer_state_unknown']+=1;continue
        if path.get('fill_opacity',1)!=1 or path.get('stroke_opacity',1)!=1:reasons['nonopaque_paint']+=1;continue
        try:
            rings=rings_from_path(path,matrix,max_points)
            if len(rings)>100:raise ValueError('Compound-ring budget exceeded')
            geometry=fill_geometry(rings,path.get('even_odd',False),'f' in path['type'])
            if geometry.is_empty or geometry.geom_type not in ('Polygon','MultiPolygon') or not geometry.is_valid:raise ValueError('Invalid polygon result')
            if any(not c['geometry'].covers(geometry) for c in clips):raise ValueError('Paint group crosses clipping boundary')
            if geometry.area<16:raise ValueError('Small symbol/annotation candidate')
            if not frame.covers(geometry):raise ValueError('Geometry outside native crop')
            if geometry.area>frame.area*.7 or geometry.boundary.distance(frame.boundary)<.25:raise ValueError('Sheet frame/border candidate')
            if masks is not None and any(text_masks[int(i)].covers(geometry) for i in masks.query(geometry)):raise ValueError('Text glyph/annotation mask')
            canonical=geometry.normalize().wkb_hex;digest=hashlib.sha256((sha+'/'+str(page_number)+'/'+canonical).encode()).hexdigest()
            if digest in seen:seen[digest]['paint_ordinals'].append(ordinal);continue
            if len(candidates)>=max_candidates:reasons['candidate_budget_deferred']+=1;break
            candidate={'id':digest,'document_sha256':sha,'page':page_number,'geometry':mapping(geometry),'coordinate_frame':'pdf_native_points_y_up','paint_ordinals':[ordinal],
                       'area_pdf_points_squared':geometry.area,'rendering_status':'supported_straight_unclipped_polygon','semantic_status':'unclassified','physical_identity_verified':False,'world_geometry_additions':0}
            candidates.append(candidate);seen[digest]=candidate
        except (ValueError,TypeError,KeyError,OverflowError) as exc:reasons[str(exc)]+=1
    labels=native_lines(page);index=STRtree([shape(c['geometry']) for c in candidates]) if candidates else None
    for label in labels:
        families=[family for family,pattern in FAMILIES.items() if re.search(pattern,label['text'],re.I)]
        if not families:continue
        point=Point(label['local']);matches=[int(i) for i in index.query(point) if shape(candidates[int(i)]['geometry']).contains(point)] if index is not None else []
        if len(matches)!=1:reasons['ambiguous_label' if matches else 'unmatched_label']+=1;continue
        candidates[matches[0]].setdefault('label_hypotheses',[]).append({'text':label['text'],'local':label['local'],'family_candidates':families,'status':'unique_interior_text_center_only'})
    return candidates,{'status':'partial_candidate_budget' if reasons['candidate_budget_deferred'] else 'unplaced_polygon_candidates','raw_paths':len(paths),'candidates':len(candidates),'rejections':dict(reasons),'world_geometry_additions':0}


def retained_page_candidates(corpus,candidate):
    sha,page=candidate['document_sha256'],candidate['page']
    if candidate.get('extraction_kind')=='drawing_geometry':
        from .drawing_geometry import VERSION as version
        if candidate.get('extraction_version')!=version or not re.fullmatch('[0-9a-f]{64}',str(candidate.get('extraction_contract',''))):raise ValueError('Current geometry extraction version/contract required')
        if not corpus.db.execute("SELECT 1 FROM sqlite_master WHERE name='geometry_pages'").fetchone():raise ValueError('Current geometry extraction required')
        row=corpus.db.execute('SELECT result FROM geometry_pages WHERE sha=? AND page=? AND version=? AND contract=?',(sha,page,version,candidate['extraction_contract'])).fetchone()
    else:row=corpus.db.execute('SELECT result FROM footprint_pages WHERE sha=? AND page=? AND version=?',(sha,page,VERSION)).fetchone()
    if not row:raise ValueError('Current retained page extraction required')
    return json.loads(row[0])['candidates']


def reviewed_feature(candidate,review,source,alignment,target_crs):
    from pyproj import CRS
    if review.get('candidate_id')!=candidate['id']:raise ValueError('Review must bind exact candidate identity')
    geometry=shape(candidate['geometry'])
    line=geometry.geom_type=='LineString';expanded=candidate.get('extraction_kind')=='drawing_geometry'
    if geometry.geom_type not in ('Polygon','MultiPolygon','LineString') or geometry.is_empty or not geometry.is_valid or geometry.has_z or (line and not geometry.is_simple):raise ValueError('Valid native 2D candidate geometry required')
    if line and (not expanded or review.get('line_role') not in ('centerline','boundary') or not isinstance(review.get('line_role_verification_reference'),str) or not review['line_role_verification_reference'].strip()):raise ValueError('Explicit physical line-role review required')
    if expanded:
        from .drawing_geometry import VERSION as version
        if candidate.get('extraction_version')!=version or candidate.get('paint_reference_truncated'):raise ValueError('Complete current geometry extraction required')
    digest=hashlib.sha256((candidate['document_sha256']+'/'+str(candidate['page'])+'/'+geometry.normalize().wkb_hex).encode()).hexdigest()
    statuses={'supported_straight_unclipped_polygon'}
    if expanded:statuses|={'supported_curved_unclipped_polygon','supported_straight_unclipped_polyline','supported_curved_unclipped_polyline'}
    if digest!=candidate['id'] or candidate.get('coordinate_frame')!='pdf_native_points_y_up' or candidate.get('rendering_status') not in statuses or line!=candidate['rendering_status'].endswith('polyline'):raise ValueError('Candidate content/frame/rendering changed')
    if review.get('physical_identity_verified') is not True or not isinstance(review.get('verification_reference'),str) or not review['verification_reference'].strip():raise ValueError('Physical identity review required')
    if not isinstance(review.get('feature_id'),str) or not review['feature_id'].strip():raise ValueError('Feature identity required')
    if review.get('reuse_allowed') is not True:raise ValueError('Explicit geometry reuse required')
    if review.get('drawing_state') not in ('existing','as_built') or not review.get('state_verification_reference'):raise ValueError('Verified existing/as-built state required')
    if source.kind not in ('planning','cad') or source.sha256!=candidate['document_sha256']:raise ValueError('Source must pin the candidate PDF')
    if source.metadata.get('registration_document_sha256')!=candidate['document_sha256'] or source.metadata.get('registration_page')!=candidate['page']:raise ValueError('Registration must bind the same PDF page')
    if source.license=='copyright-consultation-only' or source.metadata.get('reuse_status')=='consultation_only':raise ValueError('Source restricts geometry reuse')
    if CRS.from_user_input(source.crs)!=CRS.from_user_input(target_crs) or CRS.from_user_input(alignment['target_crs'])!=CRS.from_user_input(target_crs):raise ValueError('Declared target frame mismatch')
    if source.metadata.get('horizontal_registration_review')!=alignment:raise ValueError('Source must retain this exact accepted alignment review')
    controls=alignment['control_pairs'];checks=alignment['checkpoint_pairs']
    for pair in controls+checks:
        if not isinstance(pair.get('source_id'),str) or not pair['source_id'] or not re.fullmatch('[0-9a-f]{64}',str(pair.get('source_sha256',''))):raise ValueError('Registration pair source provenance required')
    control_sources={(r['source_id'],r['source_sha256']) for r in controls}
    if any(r.get('independent') is not True or (r['source_id'],r['source_sha256']) in control_sources for r in checks):raise ValueError('Independently sourced checkpoint evidence required')
    import numpy as np
    checked=review_registration(alignment['control_pairs'],alignment['checkpoint_pairs'],tolerance_m=alignment['tolerance_m'],expected_scale=alignment['scale'])
    if checked['status']!='accepted_horizontal_fit' or not np.allclose(checked['matrix'],alignment['matrix'],rtol=0,atol=1e-9) or not np.allclose(checked['translation_m'],alignment['translation_m'],rtol=0,atol=1e-7):raise ValueError('Alignment does not match its independent control evidence')
    def polygon(poly):
        return Polygon(apply_registration(list(poly.exterior.coords),alignment),[apply_registration(list(r.coords),alignment) for r in poly.interiors])
    if line:placed=LineString(apply_registration(list(geometry.coords),alignment))
    elif geometry.geom_type=='Polygon':placed=polygon(geometry)
    else:
        from shapely.geometry import MultiPolygon
        placed=MultiPolygon([polygon(p) for p in geometry.geoms])
    if line:
        if review.get('family') not in ('path','wall','fence','metal_fence','wood_fence'):raise ValueError('Supported planar line family required; rides need measured 3D routes')
        if review['family']=='path' and review['line_role']!='centerline':raise ValueError('Path lines require reviewed centerline and separate width evidence')
    elif review.get('family') not in FAMILIES:raise ValueError('Supported polygon family required')
    curve_error_m=0
    if expanded and candidate['curve_approximation']['cubic_segments']:
        if review.get('curve_approximation_reviewed') is not True or not isinstance(review.get('approximation_verification_reference'),str) or not review['approximation_verification_reference'].strip():raise ValueError('Explicit curve approximation review required')
        approximation=candidate['curve_approximation'];bound=approximation['chord_error_bound_pdf_points']
        if not math.isfinite(bound) or not 0<=bound<=approximation['requested_tolerance_pdf_points'] or approximation['method']!='adaptive_de_casteljau_control_hull_to_chord':raise ValueError('Invalid curve error certificate')
        curve_error_m=bound*alignment['scale']
        if curve_error_m+checked['checkpoint_error']['max_m']>alignment['tolerance_m']:raise ValueError('Curve approximation exceeds registration error budget')
        from .reconstruction.registration import registration_domain
        if not registration_domain(alignment).buffer(1e-7).covers(placed.buffer(curve_error_m)):raise ValueError('Curve error envelope extrapolates beyond validated domain')
    association=None
    if review.get('checked_landmark'):
        if line:raise ValueError('Polygon landmark overlap cannot verify a line role')
        landmark=review['checked_landmark']
        if landmark.get('independently_checked') is not True or not landmark.get('id') or not re.fullmatch('[0-9a-f]{64}',str(landmark.get('source_sha256',''))):raise ValueError('Checked landmark identity/provenance required')
        if landmark['source_sha256']==candidate['document_sha256']:raise ValueError('Landmark must use independent source evidence')
        if CRS.from_user_input(landmark['crs'])!=CRS.from_user_input(target_crs):raise ValueError('Checked landmark target frame mismatch')
        reference=shape(landmark['geometry'])
        if reference.geom_type not in ('Polygon','MultiPolygon') or not reference.is_valid or reference.is_empty:raise ValueError('Checked polygon landmark required')
        iou=placed.intersection(reference).area/placed.union(reference).area
        if iou<.75:raise ValueError('Footprint does not agree with checked landmark')
        association={'landmark_id':landmark['id'],'source_sha256':landmark['source_sha256'],'intersection_over_union':iou,'status':'checked_reference_overlap; physical identity remains explicitly reviewed'}
    feature=Feature(review['feature_id'],review['family'],mapping(placed),source.id,review.get('parameters',{}),
                    {'drawing_state':review['drawing_state'],'geometry_crs':target_crs,'candidate_id':candidate['id'],'document_sha256':candidate['document_sha256'],'page':candidate['page'],'physical_verification_reference':review['verification_reference'],'state_verification_reference':review['state_verification_reference']})
    if expanded:feature.metadata.update(extraction_version=candidate['extraction_version'],extraction_contract=candidate['extraction_contract'],curve_approximation_error_bound_m=curve_error_m)
    if line:feature.metadata.update(line_role=review['line_role'],line_role_verification_reference=review['line_role_verification_reference'])
    if review.get('name'):
        if not isinstance(review['name'],str):raise ValueError('Reviewed name must be text')
        feature.metadata['name']=review['name']
    if any(key in review for key in ('sheet_key','issue_date','revision')):
        from datetime import date
        if not isinstance(review.get('sheet_key'),str) or not review['sheet_key'].strip() or not isinstance(review.get('sheet_revision_reference'),str) or not review['sheet_revision_reference'].strip():raise ValueError('Sheet identity and revision evidence reference required')
        issued=date.fromisoformat(review['issue_date'])
        if issued.isoformat()!=review['issue_date']:raise ValueError('Canonical ISO issue date required')
        feature.metadata.update({key:review[key] for key in ('sheet_key','issue_date','sheet_revision_reference')})
        if 'revision' in review:
            if not isinstance(review['revision'],str):raise ValueError('Revision label must be text')
            feature.metadata['revision']=review['revision']
    feature.validate({source.id:source},source.vertical_datum)
    if association:feature.metadata['checked_landmark_association']=association
    return feature


def run(corpus,output,*,max_pages=1000):
    import pymupdf
    if not isinstance(max_pages,int) or isinstance(max_pages,bool) or not 1<=max_pages<=100000:raise ValueError('Positive bounded page budget required')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    corpus.db.execute('CREATE TABLE IF NOT EXISTS footprint_pages(sha TEXT,page INTEGER,version TEXT,result TEXT,PRIMARY KEY(sha,page,version))')
    processed=resumed=0;errors=[];valid=set()
    for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded' ORDER BY sha").fetchall():
        path=corpus.root/'files'/f'{sha}.pdf'
        try:
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('PDF checksum mismatch')
            with pymupdf.open(path) as pdf:
                valid.add(sha)
                for index in range(len(pdf)):
                    if corpus.db.execute('SELECT 1 FROM footprint_pages WHERE sha=? AND page=? AND version=?',(sha,index+1,VERSION)).fetchone():resumed+=1;continue
                    if processed>=max_pages:break
                    try:candidates,report=extract_page(pdf[index],sha,index+1)
                    except Exception as exc:candidates=[];report={'status':'withheld','reason':str(exc)}
                    with corpus.db:corpus.db.execute('INSERT INTO footprint_pages VALUES(?,?,?,?)',(sha,index+1,VERSION,json.dumps({'candidates':candidates,'report':report})))
                    processed+=1
        except Exception as exc:errors.append({'document_sha256':sha,'error':str(exc)})
    counts=Counter();rejections=Counter();total=pages=associated=0;digest=hashlib.sha256();temporary=output/'footprint-candidates.jsonl.partial'
    with temporary.open('wb') as stream:
        for sha,page,raw in corpus.db.execute('SELECT sha,page,result FROM footprint_pages WHERE version=? ORDER BY sha,page',(VERSION,)):
            if sha not in valid:continue
            data=json.loads(raw);pages+=1;counts[data['report']['status']]+=1;rejections.update(data['report'].get('rejections',{}))
            for candidate in data['candidates']:
                encoded=(json.dumps(candidate,sort_keys=True)+'\n').encode();stream.write(encoded);digest.update(encoded);total+=1;associated+=int(bool(candidate.get('label_hypotheses')))
    temporary.replace(output/'footprint-candidates.jsonl')
    report={'status':'unplaced_candidates_only','version':VERSION,'pages':pages,'run_pages':processed,'resumed_pages':resumed,'polygon_candidates':total,'candidates_with_label_hypotheses':associated,'page_statuses':dict(counts),'rejections':dict(rejections),'errors':errors,'candidate_file_sha256':digest.hexdigest(),'world_geometry_additions':0}
    (output/'footprint-report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def promote(candidate_file,review_file,manifest_file,output,corpus):
    manifest=json.loads(Path(manifest_file).read_text());sources={s['id']:Source(**s) for s in manifest['sources']}
    reviews=json.loads(Path(review_file).read_text())
    if not isinstance(reviews,list) or len(reviews)>10000:raise ValueError('Bounded feature review list required')
    index={}
    for review in reviews:
        if review['candidate_id'] in index:raise ValueError('Duplicate candidate review')
        index[review['candidate_id']]=review
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh reviewed feature output')
    output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix('.partial');decisions=[];seen=set();feature_ids=set()
    retained={};verified_blobs=set()
    with Path(candidate_file).open() as stream,temporary.open('w') as target:
        for line in stream:
            if len(line)>8000000:raise ValueError('Candidate line budget exceeded')
            candidate=json.loads(line);review=index.get(candidate['id'])
            if review is None:continue
            if candidate['id'] in seen:raise ValueError('Duplicate candidate identity')
            seen.add(candidate['id'])
            try:
                sha,page=candidate['document_sha256'],candidate['page']
                if sha not in verified_blobs:
                    path=corpus.root/'files'/f'{sha}.pdf'
                    if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('PDF identity malformed')
                    with path.open('rb') as original:
                        if hashlib.file_digest(original,'sha256').hexdigest()!=sha:raise ValueError('Source PDF checksum mismatch')
                    verified_blobs.add(sha)
                key=(sha,page,candidate.get('extraction_kind'),candidate.get('extraction_contract'))
                if key not in retained:
                    retained.clear();retained[key]={r['id']:r for r in retained_page_candidates(corpus,candidate)}
                if retained[key].get(candidate['id'])!=candidate:raise ValueError('Candidate differs from retained current extraction')
                source=sources[review['source_id']];alignment=source.metadata['horizontal_registration_review']
                feature=reviewed_feature(candidate,review,source,alignment,manifest['crs'])
                if feature.id in feature_ids:raise ValueError('Duplicate promoted feature identity')
                feature_ids.add(feature.id);target.write(json.dumps(feature.__dict__,sort_keys=True)+'\n')
                decisions.append({'candidate_id':candidate['id'],'feature_id':feature.id,'status':'reviewed_feature_record; generator dimensions/materials still gated'})
            except (ValueError,KeyError,TypeError,OSError) as exc:decisions.append({'candidate_id':candidate['id'],'status':'withheld','reason':str(exc)})
    temporary.replace(output)
    for identifier in set(index)-seen:decisions.append({'candidate_id':identifier,'status':'withheld','reason':'Reviewed candidate missing from current candidate file'})
    report={'reviewed_records':len(feature_ids),'decisions':decisions,'world_geometry_additions':0}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    from .planning_bulk import Corpus
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus');p.add_argument('--output',required=True);p.add_argument('--max-pages',type=int,default=1000)
    p.add_argument('--candidates');p.add_argument('--feature-reviews');p.add_argument('--manifest');a=p.parse_args()
    if a.feature_reviews:
        if not a.candidates or not a.manifest or not a.corpus:p.error('Promotion requires --corpus, --candidates and --manifest')
        corpus=Corpus(a.corpus)
        try:print(json.dumps(promote(a.candidates,a.feature_reviews,a.manifest,a.output,corpus),indent=2))
        finally:corpus.close()
        return
    if not a.corpus:p.error('Extraction requires --corpus')
    corpus=Corpus(a.corpus)
    try:print(json.dumps(run(corpus,a.output,max_pages=a.max_pages),indent=2))
    finally:corpus.close()

if __name__=='__main__':main()
