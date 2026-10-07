"""Bounded scanned-page label inspection. OCR never places world geometry."""
import csv
import io
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
from PIL import Image
from pypdf import PdfReader

from .drawing_evidence import evidence_candidates
from .raster_grid import edge_labels, inspect_label_layout, provisional_word_boxes, LABEL
from .raster_marks import inspect_grid_marks
from .survey_reference import inspect_reference_notes
from .raster_location import inspect_grid_location


def labels_from_tsv(tsv, *, min_confidence=70, max_words=20_000):
    if len(tsv.encode('utf-8')) > 8_000_000:
        raise ValueError('OCR text byte budget exceeded')
    lines = {}
    words = rejected = 0
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        words += 1
        if words > max_words:
            raise ValueError('OCR word budget exceeded')
        confidence = float(row['conf'])
        if not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError('Invalid OCR confidence')
        key = tuple(row[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        line = lines.setdefault(key, {'words': [], 'confidence': 100, 'rejected': False})
        if confidence < min_confidence:
            # Do not join across an omitted word and invent a specification.
            line['rejected'] = True
            rejected += 1
        line['confidence'] = min(line['confidence'], confidence)
        line['words'].append(row['text'].strip())
    accepted = [line for line in lines.values() if not line['rejected']]
    text = '\n'.join(' '.join(line['words']) for line in accepted)
    reference_text = '\n'.join('' if line['rejected'] else ' '.join(line['words'])
                               for line in lines.values())
    evidence = evidence_candidates(text, material_context=True)
    for candidate in evidence['levels'] + evidence['materials']:
        candidate['text_origin'] = 'ocr_unverified'
        candidate['ocr_line_min_confidence'] = accepted[candidate['line_number']-1]['confidence']
    return {'status': 'ocr_candidates_only', 'semantic_evidence': evidence,
            'survey_reference_notes': inspect_reference_notes(reference_text),
            'word_count': words, 'low_confidence_word_count': rejected,
            'accepted_line_count': len(accepted),
            'printed_scale_candidates': sorted({int(v) for v in re.findall(r'\b1\s*:\s*(\d{2,6})\b', text)}),
            'explicit_epsg_candidates': sorted({int(v) for v in re.findall(r'\bEPSG\s*[:=]?\s*(\d{4,6})\b', text, re.I)}),
            'world_geometry_additions': 0,
            'limitations': ['OCR confidence is not measurement accuracy or registration',
                           'No raw text, raster, PDF, coordinate controls or polygons exported',
                           'Labels remain unplaced; no material or elevation assigned to world features']}


def original_region_label(source, page_number, page_size_points, image_size, word_box,
                          rotation, edge, root, environment, deadline=None):
    """Rerender one original-PDF region; no character substitutions."""
    pw,ph = page_size_points
    iw,ih = image_size
    if rotation not in (0,90) or edge not in ('top','bottom','left','right') or not 1<=page_number<=12:
        raise ValueError('Unsupported original region orientation/page')
    def remaining(limit):
        if deadline is None:return limit
        available=deadline-time.monotonic()
        if available<=0:raise ValueError('Original region retry time budget exhausted')
        return min(limit,available)
    if not all(math.isfinite(v) and v>0 for v in (pw,ph,iw,ih)):
        raise ValueError('Finite page/render dimensions required')
    sx,sy = pw*300/72/iw,ph*300/72/ih
    x0,y0,x1,y1 = word_box
    if not all(math.isfinite(v) for v in word_box) or min(x0,y0)<0 or x1>iw or y1>ih or x1<=x0 or y1<=y0:
        raise ValueError('Retry word outside page')
    x,y = max(0,math.floor((x0-4)*sx)),max(0,math.floor((y0-4)*sy))
    width = min(math.ceil(pw*300/72),math.ceil((x1+4)*sx))-x
    height = min(math.ceil(ph*300/72),math.ceil((y1+4)*sy))-y
    if min(width,height)<1 or max(width,height)>1024 or width*height>1_000_000:
        raise ValueError('Original region pixel budget exceeded')
    target = root/'region'
    subprocess.run(['pdftoppm','-f',str(page_number),'-l',str(page_number),'-singlefile',
                    '-r','300','-x',str(x),'-y',str(y),'-W',str(width),'-H',str(height),
                    '-png',str(source),str(target)],check=True,timeout=remaining(15),
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if target.with_suffix('.png').stat().st_size>4_000_000:
        raise ValueError('Original region byte budget exceeded')
    with Image.open(target.with_suffix('.png')) as region:
        if region.width>width or region.height>height or min(region.size)<1:
            raise ValueError('Rendered region exceeds requested extent')
        region.rotate(rotation,expand=True).save(root/'region-ocr.png')
    subprocess.run(['tesseract',str(root/'region-ocr.png'),str(root/'region-label'),'-l','eng','--psm','7','tsv'],
                   check=True,timeout=remaining(5),env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    output=root/'region-label.tsv'
    if output.stat().st_size>100_000:
        raise ValueError('Region OCR byte budget exceeded')
    candidates=[]
    for row in csv.DictReader(io.StringIO(output.read_text()),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5':continue
        match=LABEL.fullmatch(row.get('text','').strip())
        if not match:continue
        confidence=float(row['conf'])
        if not math.isfinite(confidence) or not 0<=confidence<=100:
            raise ValueError('Invalid region OCR confidence')
        if confidence<70 or (match[2].upper()=='E')!=(edge in ('top','bottom')):continue
        candidates.append({'axis':match[2].upper(),'value':int(match[1]),'confidence':confidence,
                           'pixel_position':(x0+x1)/2 if match[2].upper()=='E' else (y0+y1)/2,
                           'edge':edge,'ocr_method':'original_pdf_region_300dpi'})
    return candidates[0] if len(candidates)==1 else None


def inspect_border_grid(image, root, environment, source=None, page_number=1, page_size_points=None,
                        reference_notes=None, bounds=None):
    labels, failures = [], []
    with Image.open(image) as page:
        width, height = page.size
        horizontal_band = min(180, min(width,height)//8)
        vertical_band = min(100, min(width,height)//8)
        crops = [('top',(0,0,width,horizontal_band),90), ('bottom',(0,height-horizontal_band,width,height),90),
                 ('left',(0,0,vertical_band,height),0), ('right',(width-vertical_band,0,width,height),0)]
        for edge, box, rotation in crops:
            try:
                crop = page.crop(box)
                if crop.width*crop.height*9 > 8_000_000:
                    raise ValueError('Edge crop pixel budget exceeded')
                crop = crop.resize((crop.width*3,crop.height*3)).rotate(rotation,expand=True)
                target = root/(edge+'.png'); crop.save(target)
                subprocess.run(['tesseract',str(target),str(root/edge),'-l','eng','--psm','11','tsv'],
                               check=True,timeout=10,env=environment,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                output = root/(edge+'.tsv')
                if output.stat().st_size > 8_000_000:
                    raise ValueError('Edge TSV byte budget exceeded')
                labels.extend(edge_labels(output.read_text(),edge,box,rotation))
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                failures.append({'edge':edge,'reason':str(error)})
        retries=0
        recovered=0
        if source is not None and page_size_points is not None:
            deadline=time.monotonic()+75
            for edge,box,rotation in crops:
                axis='E' if edge in ('top','bottom') else 'N'
                if len({label['value'] for label in labels if label['axis']==axis})>=3:
                    continue
                if retries>=4 or time.monotonic()>=deadline:
                    break
                try:
                    target=root/('base-'+edge)
                    page.crop(box).rotate(rotation,expand=True).save(target.with_suffix('.png'))
                    subprocess.run(['tesseract',str(target.with_suffix('.png')),str(target),'-l','eng','--psm','11','tsv'],
                                   check=True,timeout=min(10,max(.01,deadline-time.monotonic())),env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    if target.with_suffix('.tsv').stat().st_size>8_000_000:
                        raise ValueError('Baseline edge TSV byte budget exceeded')
                    proposals=provisional_word_boxes(target.with_suffix('.tsv').read_text(),edge,box,rotation)
                    for proposal in proposals:
                        if retries>=4 or time.monotonic()>=deadline:break
                        # Avoid duplicate retries for coordinates already read
                        # clearly; this never accepts the provisional digits.
                        if any(str(label['value'])==proposal['first_pass_text'][:6] for label in labels if label['axis']==axis):continue
                        retries+=1
                        label=original_region_label(source,page_number,page_size_points,(width,height),
                                                    proposal['page_pixel_box'],rotation,edge,root,environment,deadline)
                        if label is not None:
                            labels.append(label);recovered+=1
                except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
                    failures.append({'edge':edge,'stage':'original_region_retry','reason':str(error)})
    report = inspect_label_layout(labels)
    report['original_region_retries']=retries
    report['recovered_coordinate_labels']=recovered
    report['grid_mark_registration']=inspect_grid_marks(image,labels)
    report['grid_location_check']=inspect_grid_location(labels,reference_notes or {},bounds)
    report['edge_failures'] = failures
    if failures:
        report['status'] = 'incomplete_edge_inspection'
    return report


def inspect_scanned_page(payload, page_number, bounds=None):
    result = {'status': 'unavailable', 'world_geometry_additions': 0}
    if not shutil.which('pdftoppm') or not shutil.which('tesseract'):
        return {**result, 'reason': 'Poppler and Tesseract executables required'}
    if len(payload) > 10_000_000 or not payload.startswith(b'%PDF-') or not 1 <= page_number <= 12:
        return {**result, 'reason': 'OCR PDF/page budget exceeded'}
    try:
        with tempfile.TemporaryDirectory(prefix='voxel-ocr-') as directory:
            root = Path(directory)
            source, image = root/'input.pdf', root/'page.png'
            source.write_bytes(payload)
            subprocess.run(['pdftoppm', '-f', str(page_number), '-l', str(page_number),
                            '-singlefile', '-scale-to', '4096', '-png', str(source), str(root/'page')],
                           check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if image.stat().st_size > 40_000_000:
                raise ValueError('OCR image byte budget exceeded')
            with image.open('rb') as stream:
                header = stream.read(24)
            if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
                raise ValueError('Expected rendered PNG header')
            width, height = struct.unpack('>II', header[16:24])
            if min(width, height) < 1 or max(width, height) > 4096:
                raise ValueError('OCR pixel budget exceeded')
            environment = dict(os.environ, OMP_THREAD_LIMIT='1')
            subprocess.run(['tesseract', str(image), str(root/'labels'), '-l', 'eng', '--psm', '3', 'tsv'],
                           check=True, timeout=45, env=environment,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            output = root/'labels.tsv'
            if output.stat().st_size > 8_000_000:
                raise ValueError('OCR text byte budget exceeded')
            page=PdfReader(io.BytesIO(payload)).pages[page_number-1]
            size = (float(page.mediabox.width),float(page.mediabox.height)) if not int(page.get('/Rotate',0))%360 and float(page.get('/UserUnit',1))==1 else None
            candidates=labels_from_tsv(output.read_text())
            return {**candidates, 'rendered_size_pixels': [width, height],
                    'border_grid_inspection':inspect_border_grid(image,root,environment,source,page_number,size,
                                                                candidates['survey_reference_notes'],bounds)}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return {**result, 'reason': str(error)}
