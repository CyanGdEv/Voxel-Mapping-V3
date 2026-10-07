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
from PIL import Image

from .drawing_evidence import evidence_candidates
from .raster_grid import edge_labels, inspect_label_layout


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
    evidence = evidence_candidates(text, material_context=True)
    for candidate in evidence['levels'] + evidence['materials']:
        candidate['text_origin'] = 'ocr_unverified'
        candidate['ocr_line_min_confidence'] = accepted[candidate['line_number']-1]['confidence']
    return {'status': 'ocr_candidates_only', 'semantic_evidence': evidence,
            'word_count': words, 'low_confidence_word_count': rejected,
            'accepted_line_count': len(accepted),
            'printed_scale_candidates': sorted({int(v) for v in re.findall(r'\b1\s*:\s*(\d{2,6})\b', text)}),
            'explicit_epsg_candidates': sorted({int(v) for v in re.findall(r'\bEPSG\s*[:=]?\s*(\d{4,6})\b', text, re.I)}),
            'world_geometry_additions': 0,
            'limitations': ['OCR confidence is not measurement accuracy or registration',
                           'No raw text, raster, PDF, coordinate controls or polygons exported',
                           'Labels remain unplaced; no material or elevation assigned to world features']}


def inspect_border_grid(image, root, environment):
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
    report = inspect_label_layout(labels)
    report['edge_failures'] = failures
    if failures:
        report['status'] = 'incomplete_edge_inspection'
    return report


def inspect_scanned_page(payload, page_number):
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
            return {**labels_from_tsv(output.read_text()), 'rendered_size_pixels': [width, height],
                    'border_grid_inspection':inspect_border_grid(image,root,environment)}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        return {**result, 'reason': str(error)}
