"""Read-only page rotation, bounded OCR and named landmark hypotheses."""
import copy
import csv
import hashlib
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .drawing_ocr import labels_from_tsv
from .reconstruction.registration import review_registration


def native_inspection_page(page):
    from pypdf.generic import NameObject,NumberObject
    rotation=int(page.get('/Rotate',0))%360
    if rotation not in (0,90,180,270):raise ValueError('Unsupported non-right-angle page rotation')
    if float(page.get('/UserUnit',1))!=1:raise ValueError('Non-default PDF UserUnit remains unsupported')
    # /Rotate affects display, not the native content coordinates. Do not
    # transform content, viewport metadata or user-supplied native controls.
    result=copy.copy(page);result[NameObject('/Rotate')]=NumberObject(0)
    return result,{'original_rotation_degrees':rotation,'inspection_rotation_degrees':0,'local_frame':'pdf_native_points_y_up','source_pdf_modified':False}


def native_inverse(page):
    # PyMuPDF's transformation_matrix drops crop offsets on rotated pages.
    # Read the unrotated matrix, then restore the in-memory display metadata;
    # no PDF file is saved or rewritten.
    rotation=page.rotation
    try:
        if rotation:page.set_rotation(0)
        return ~page.transformation_matrix
    finally:
        if rotation:page.set_rotation(rotation)


def pixel_to_native(page,width,height):
    import pymupdf
    matrix=pymupdf.Matrix(page.rect.width/width,page.rect.height/height)
    derotation=page.derotation_matrix
    matrix=matrix*derotation*native_inverse(page)
    return list(matrix)


def native_lines(page,max_lines=20000):
    import pymupdf
    rows=[];matrix=native_inverse(page)
    for block in page.get_text('dict',flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            text=' '.join(s['text'] for s in line['spans']).strip()
            if not text:continue
            box=pymupdf.Rect(line['bbox']);p=pymupdf.Point((box.x0+box.x1)/2,(box.y0+box.y1)/2)*matrix
            rows.append({'text':text,'local':[p.x,p.y],'origin':'native_text_box_center_unverified'})
            if len(rows)>max_lines:raise ValueError('Native label budget exceeded')
    return rows


def ocr_lines(tsv,page,width,height,min_confidence=70):
    import pymupdf
    summary=labels_from_tsv(tsv,min_confidence=min_confidence)
    groups={};matrix=pymupdf.Matrix(pixel_to_native(page,width,height))
    for row in csv.DictReader(io.StringIO(tsv),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5' or not row.get('text','').strip():continue
        key=tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
        group=groups.setdefault(key,{'words':[],'boxes':[],'confidence':100})
        confidence=float(row['conf']);group['confidence']=min(group['confidence'],confidence)
        x,y,w,h=[float(row[k]) for k in ('left','top','width','height')]
        if not all(math.isfinite(v) for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0 or x+w>width or y+h>height:raise ValueError('OCR word outside rendered frame')
        group['words'].append(row['text']);group['boxes'].append([x,y,x+w,y+h])
    lines=[]
    for group in groups.values():
        if group['confidence']<min_confidence:continue
        boxes=group['boxes'];x=(min(b[0] for b in boxes)+max(b[2] for b in boxes))/2;y=(min(b[1] for b in boxes)+max(b[3] for b in boxes))/2
        p=pymupdf.Point(x,y)*matrix
        lines.append({'text':' '.join(group['words']),'local':[p.x,p.y],'origin':'ocr_text_box_center_unverified','confidence':group['confidence']})
    return summary,lines


def inspect_ocr_page(page,*,timeout=20,max_side=3072,min_confidence=70):
    import pymupdf
    if not shutil.which('tesseract'):return {'status':'unavailable','reason':'Tesseract required'},[]
    try:
        if not .01<timeout<=60 or not 256<=max_side<=4096:raise ValueError('Invalid OCR time/pixel budget')
        scale=min(300/72,max_side/max(page.rect.width,page.rect.height))
        pixmap=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csGRAY,alpha=False)
        if max(pixmap.width,pixmap.height)>max_side+1 or pixmap.width*pixmap.height>17000000:raise ValueError('OCR rendered pixel budget exceeded')
        with tempfile.TemporaryDirectory(prefix='park-page-ocr-') as directory:
            root=Path(directory);pixmap.save(root/'page.png')
            result=subprocess.run(['tesseract',str(root/'page.png'),str(root/'labels'),'-l','eng','--psm','3','tsv'],timeout=timeout,env={**os.environ,'OMP_THREAD_LIMIT':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if result.returncode:raise ValueError('Tesseract failed')
            output=root/'labels.tsv'
            if output.stat().st_size>8000000:raise ValueError('OCR TSV byte budget exceeded')
            text=output.read_text();summary,lines=ocr_lines(text,page,pixmap.width,pixmap.height,min_confidence)
        return {**summary,'tsv_sha256':hashlib.sha256(text.encode()).hexdigest(),'rendered_size_pixels':[pixmap.width,pixmap.height],'pixel_to_pdf_native_matrix':pixel_to_native(page,pixmap.width,pixmap.height),'render_rotation_degrees':page.rotation},lines
    except (OSError,ValueError,subprocess.SubprocessError) as exc:return {'status':'unavailable','reason':str(exc)},[]


def reference_landmarks(collection,source_crs,target_crs,source_sha256):
    from pyproj import CRS,Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    source,target=CRS.from_user_input(source_crs),CRS.from_user_input(target_crs)
    if not target.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in target.axis_info[:2]):raise ValueError('Landmark target must use projected metres')
    projector=Transformer.from_crs(source,target,always_xy=True);rows=[]
    for i,feature in enumerate(collection.get('features',[])):
        props=feature.get('properties',{});name=props.get('name')
        if not isinstance(name,str) or not name.strip():continue
        geometry=transform(projector.transform,shape(feature['geometry']))
        if geometry.is_empty or not geometry.is_valid or not all(math.isfinite(v) for v in geometry.bounds):continue
        point=geometry.centroid
        rows.append({'id':str(feature.get('id',i)),'name':name,'target':[point.x,point.y],'target_crs':target.to_string(),'source_sha256':source_sha256,'source_id':props.get('source_id','reference-feed'),'anchor_kind':'reference_geometry_centroid_unverified'})
        if len(rows)>5000:raise ValueError('Named reference budget exceeded')
    return rows


def name_key(text):return re.sub(r'[^a-z0-9]+',' ',re.sub(r'^the\s+','',text.strip(),flags=re.I).casefold()).strip()


def match_landmarks(lines,references,scales):
    if len(lines)>20000 or len(references)>5000:raise ValueError('Landmark matching budget exceeded')
    if len({r['target_crs'] for r in references})>1:raise ValueError('Landmark targets must share a declared CRS')
    groups={}
    for reference in references:groups.setdefault(name_key(reference['name']),[]).append(reference)
    matches=[];controls=[];ambiguous=[]
    labels={}
    for line in lines:labels.setdefault(name_key(line['text']),[]).append(line)
    for name,refs in groups.items():
        found=labels.get(name,[])
        if not found:continue
        if len(refs)!=1 or len(found)!=1:ambiguous.append({'name':name,'reference_count':len(refs),'label_count':len(found)});continue
        reference,line=refs[0],found[0]
        match={'reference':reference,'label':line,'status':'name_match_only; text centre is not a surveyed corner'}
        matches.append(match);controls.append({'id':'landmark/'+name,'local':line['local'],'target':reference['target']})
    result={'status':'named_candidates_only','matches':matches,'ambiguous_names':ambiguous,'registration_verified':False,'world_geometry_additions':0,'fit':{'status':'not_attempted','reason':'Three unique names and one scale candidate required'}}
    if len(controls)>=3 and len(scales)==1:
        try:
            fit=review_registration(controls,[],expected_scale=scales[0]*.0254/72,scale_tolerance=.1,tolerance_m=5)
            result['fit']={**fit,'status':'candidate_name_fit' if fit['reasons']==['independent_checkpoints_missing'] else 'failed_consistency','independent_accuracy':'not_verified','anchor_limitations':'Label centres and reference centroids are hypotheses, never approved controls'}
        except ValueError as exc:result['fit']={'status':'withheld','reason':str(exc)}
    return result
