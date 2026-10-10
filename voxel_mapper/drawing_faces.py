"""Source-linked bounded face candidates and raster dependencies for material anchors."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import pymupdf
from shapely.geometry import Point,shape
from .drawing_annotations import file_hash
from .drawing_callouts import page_callouts
from .drawing_geometry import extract_page
from .drawing_page_tools import native_inverse
from .linework_boundaries import recover_page
from .glyph_visibility import screen_span,VERSION as GLYPH_VERSION

from .raster_faces import review as raster_review, VERSION as RASTER_VERSION, BACKENDS as RASTER_BACKENDS

from .raster_boundaries import VERSION as BOUNDARY_VERSION

from .contrast_boundaries import VERSION as CONTRAST_VERSION

from .drawing_views import page_labels, page_references, attach_metrics, cross_links, VERSION as VIEW_VERSION

VERSION='material-anchor-faces-v4'


def face_matches(candidates,point):
    """Retain every containing source face; never select a smaller enclosure or repair gaps."""
    matches=[]
    for candidate in candidates:
        if candidate.get('extraction_kind')!='linework_boundaries' or candidate['geometry']['type']!='Polygon':continue
        geometry=shape(candidate['geometry'])
        if geometry.is_valid and geometry.contains(Point(point)):matches.append(candidate)
    return matches


def raster_references(page,point):
    references=[]
    for image in page.get_image_info(xrefs=True):
        if not pymupdf.Rect(image['bbox']).contains(pymupdf.Point(point)):continue
        transform=pymupdf.Matrix(image['transform'])
        if abs(transform.a*transform.d-transform.b*transform.c)<1e-12:continue
        uv=pymupdf.Point(point)*(~transform)
        if not 0<=uv.x<=1 or not 0<=uv.y<=1:continue
        xref=image.get('xref');digest=None
        if xref:
            buffer=page.parent.extract_image(xref)['image']
            if len(buffer)>20000000:continue
            digest=hashlib.sha256(buffer).hexdigest()
        references.append({'image_number':image['number'],'xref':xref,'image_bytes_sha256':digest,
                'image_bbox_page_points':list(image['bbox']),'image_transform':list(image['transform']),
                'image_size_pixels':[image['width'],image['height']],
                'anchor_image_pixel_candidate':[uv.x*image['width'],uv.y*image['height']],
                'has_mask':image.get('has-mask',False),'component_boundary_verified':False,'component_visibility_verified':False,'view_identity_verified':False,
                'limitations':['Image tile bounds are not physical face or drawing-view boundaries.',
                               'Image placement or clipping may require further verification before pixel segmentation.']})
    return references


def page_faces(page,sha,page_number):
    callouts,callout_report=page_callouts(page,sha,page_number)
    raw=page.get_texttrace();screens={};records=[];counts=Counter()
    parents,extraction=extract_page(page,sha,page_number)
    recovered,recovery=recover_page(parents) if parents else ([],{'status':'no_supported_parents','recovered_faces':0})
    faces=[c for c in recovered if c.get('extraction_kind')=='linework_boundaries']
    inverse=native_inverse(page)
    for callout in callouts:
        record={**callout,'original_callout_status':callout['status'],'status':'withheld_callout_connection',
                'outline_identity_verified':False,'component_association_verified':False,'view_identity_verified':False,'accepted_feature':False,'world_geometry_additions':0}
        if callout['status'] not in ('explicit_material_anchor_candidate','withheld_label_or_legend_visibility'):
            records.append(record);counts[record['status']]+=1;continue
        indices=sorted(set(callout['label_trace_indices']+callout['legend_candidates'][0]['trace_indices']))
        for index in indices:
            if index not in screens:screens[index]=screen_span(page,raw[index])
        record['glyph_screen_trace_indices']=indices
        record['glyph_screen_status']='raster_consistent_candidate' if all(screens[i]['status']=='raster_consistent_candidate' for i in indices) else 'withheld'
        if record['glyph_screen_status']=='withheld':
            record['status']='withheld_glyph_visibility';records.append(record);counts[record['status']]+=1;continue
        record['visibility_screen_resolution']='native glyph raster comparison; original bbox hazard retained'
        native=pymupdf.Point(callout['target_page_point'])*inverse
        point=[native.x,native.y];matches=face_matches(faces,point)
        record['anchor_pdf_native_points_y_up']=point
        record['matching_enclosed_face_ids']=[f['id'] for f in matches]
        record['raster_dependencies']=raster_references(page,callout['target_page_point'])
        if len(matches)==1:
            record['status']='unique_enclosed_face_candidate';record['face_candidate_id']=matches[0]['id']
            record['opening_count_candidate']=len(shape(matches[0]['geometry']).interiors)
            record['opening_identity_verified']=False
        elif matches:record['status']='withheld_ambiguous_enclosed_faces'
        elif record['raster_dependencies']:record['status']='withheld_raster_face_identity'
        else:record['status']='withheld_no_supported_face'
        records.append(record);counts[record['status']]+=1
    raster_receipt=raster_review(page,records)
    return records,faces,{'raster_review':raster_receipt,'document_sha256':sha,'page':page_number,'callout_extraction':callout_report,
               'geometry_extraction':extraction,'linework_recovery':recovery,'face_statuses':dict(counts),
               'glyph_screen_version':GLYPH_VERSION,'glyph_screens':screens,'glyph_checks':len(screens),
               'glyph_screen_passes':sum(s['status']=='raster_consistent_candidate' for s in screens.values()),
               'coordinate_basis':'Faces use PDF native points with y up; raster references use unrotated MuPDF page points.',
               'world_geometry_additions':0}


def run(documents_file,output,*,max_pages=10000):
    if type(max_pages) is not int or not 1<=max_pages<=10000:raise ValueError('Bounded face page budget required')
    path=Path(documents_file);documents=json.loads(path.read_text());resolved=[];seen=set()
    if not isinstance(documents,list) or not 1<=len(documents)<=1000:raise ValueError('Bounded pinned document list required')
    for item in documents:
        pdf=(path.parent/item['file']).resolve()
        if pdf.stat().st_size>20000000 or file_hash(pdf)!=item['sha256'] or item['sha256'] in seen:raise ValueError('Distinct bounded pinned PDFs required')
        seen.add(item['sha256']);resolved.append((pdf,item))
    contract={'version':VERSION,'glyph_screen_version':GLYPH_VERSION,'raster_version':RASTER_VERSION,'boundary_version':BOUNDARY_VERSION,'contrast_version':CONTRAST_VERSION,'view_version':VIEW_VERSION,'raster_backends':RASTER_BACKENDS,'pymupdf_version':pymupdf.VersionBind,'documents_sha256':file_hash(path),'pdf_sha256':[i['sha256'] for _,i in resolved],'max_pages':max_pages}
    output=Path(output)
    if output.exists():
        report=json.loads((output/'face-report.json').read_text())
        if report['contract']!=contract:raise ValueError('Face inputs changed')
        for name,digest in report['output_sha256'].items():
            if file_hash(output/name)!=digest:raise ValueError('Face output checksum mismatch')
        return report
    partial=output.with_name(output.name+'.partial')
    if partial.exists():raise ValueError('Incomplete face run; use a fresh directory')
    partial.mkdir(parents=True);pages=[];view_pages=[];counts=Counter();boundary_counts=Counter();contrast_counts=Counter();total=0;face_count=0;glyph_checks=0;glyph_passes=0;resolved_visibility_hazards=0
    with (partial/'drawing-view-pages.jsonl').open('w') as view_reviews,(partial/'face-associations.jsonl').open('w') as associations,(partial/'face-candidates.jsonl').open('w') as geometry,(partial/'page-reviews.jsonl').open('w') as reviews:
        for pdf,item in resolved:
            with pymupdf.open(pdf) as document:
                if len(document)>1000 or len(pages)+len(document)>max_pages:raise ValueError('Face page budget exceeded')
                for n,page in enumerate(document,1):
                    try:records,faces,review=page_faces(page,item['sha256'],n)
                    except ValueError as error:records=[];faces=[];review={'document_sha256':item['sha256'],'page':n,'status':'withheld','reason':str(error)}
                    try:
                        labels=page_labels(page,review.get('raster_review',{}).get('atlas',{}).get('artwork_review_windows',[]),sheet_metadata=item)
                        references=page_references(page,sheet_metadata=item)
                        attach_metrics(page,records,labels)
                    except ValueError as error:
                        labels={'status':'withheld','reason':str(error)};references={}
                    view_pages.append((item['sha256'],n,labels,references))
                    view_reviews.write(json.dumps({'document_sha256':item['sha256'],'page':n,'view_labels':labels,'plan_references':references},sort_keys=True)+'\n')
                    for r in records:
                        associations.write(json.dumps(r,sort_keys=True)+'\n');counts[r['status']]+=1
                        boundary_counts[r.get('raster_boundary_review',{}).get('status','not_reviewed')]+=1
                        contrast_counts[r.get('raster_contrast_boundary_review',{}).get('status','not_reviewed')]+=1
                        resolved_visibility_hazards+=int(r.get('original_callout_status')=='withheld_label_or_legend_visibility' and r.get('glyph_screen_status')=='raster_consistent_candidate')
                    for f in faces:geometry.write(json.dumps(f,sort_keys=True)+'\n')
                    total+=len(records);face_count+=len(faces);glyph_checks+=review.get('glyph_checks',0);glyph_passes+=review.get('glyph_screen_passes',0)
                    reviews.write(json.dumps(review,sort_keys=True)+'\n');pages.append({k:v for k,v in review.items() if k!='glyph_screens'})
    links=cross_links(view_pages)
    with (partial/'view-links.jsonl').open('w') as stream:
        for link in links:stream.write(json.dumps(link,sort_keys=True)+'\n')
    report={'view_link_statuses':dict(Counter(link['status'] for link in links)),'status':'unplaced_face_association_evidence','contract':contract,'pages':pages,'anchor_records':total,
            'raster_contrast_statuses':dict(contrast_counts),'raster_boundary_statuses':dict(boundary_counts),'unclassified_enclosed_face_candidates':face_count,'face_statuses':dict(counts),'glyph_checks':glyph_checks,'glyph_screen_passes':glyph_passes,'resolved_callout_visibility_hazards':resolved_visibility_hazards,
            'output_sha256':{name:file_hash(partial/name) for name in ('face-associations.jsonl','face-candidates.jsonl','page-reviews.jsonl','drawing-view-pages.jsonl','view-links.jsonl')},
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0,
            'limitations':['A unique enclosed face is a candidate, not proof of physical component or opening identity.',
                           'Raster glyph checks resolve a screening hazard, not material/as-built or national-grid verification.',
                           'Raster regions require physical boundary, clipping and view verification; tile rectangles are never component boundaries.',
                           'View identity, dimensions/depth, revision state, vertical datum and independent registration remain required.']}
    (partial/'face-report.json').write_text(json.dumps(report,indent=2)+'\n');partial.replace(output);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--documents',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(run(a.documents,a.output),indent=2))


if __name__=='__main__':main()
