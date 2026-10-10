"""Review source-linked SW8 section claims without accepting map placement."""
import argparse, hashlib, json, re, sys
from pathlib import Path
import fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.survey_reference import inspect_reference_notes

PATTERNS = {
    'combined_station_shop_top': r'Station & Shop Building to (\d+(?:\.\d+)?)',
    'shop_building_top': r'(?<!& )Shop Building to (\d+(?:\.\d+)?)',
    'station_building_level': r'Station Building (\d+(?:\.\d+)?)',
    'maintenance_building_level': r'Maintenance Building (?:to )?(\d+(?:\.\d+)?)',
    'ride_low_point': r'Ride track low point at (\d+(?:\.\d+)?)',
    'ride_high_point': r'Track HP\d+ at (\d+(?:\.\d+)?)',
    'sound_tunnel_top': r'Sound tunnel shown dashed to (\d+(?:\.\d+)?)',
    'section_level_mark': r'\b(175|180)m\b',
}


def inspect_page(page, label):
    text = page.get_text()
    words = page.get_text('words')
    pieces, offsets, cursor = [], [], 0
    for word in words:
        token = word[4]; pieces.append(token)
        offsets.append((cursor, cursor + len(token), list(word[:4])))
        cursor += len(token) + 1
    joined = ' '.join(pieces)
    claims = []
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, joined, re.I):
            boxes = [bbox for start, end, bbox in offsets if start < match.end() and end > match.start()]
            claims.append({'kind': kind, 'value_metres': float(match[1]),
                           'native_word_bboxes': boxes, 'visible_text_verified': False,
                           'vertical_datum_verified': False, 'physical_identity_verified': False})
    # PDF text may survive beneath white overpainting. Opposite state markers
    # in the same title position are not two visible title blocks.
    existing = [fitz.Rect(w[:4]) for w in words if w[4].lower() == 'existing']
    proposed = [fitz.Rect(w[:4]) for w in words if w[4].lower() == 'proposed']
    conflicts = []
    for a in existing:
        for b in proposed:
            intersection = a & b
            if not intersection.is_empty and intersection.get_area() / min(a.get_area(), b.get_area()) > .5:
                pair = {'existing_bbox': list(a), 'proposed_bbox': list(b)}
                if pair not in conflicts:
                    conflicts.append(pair)
    materials = {}
    normal = re.sub(r'\s+', ' ', text).lower()
    for field, phrase in [('ride_structure_sound_tunnels_screens','dark stained timber'),
                          ('roof_thatch','artificial thatch'),
                          ('roof_metal','distressed profiled metal sheeting'),
                          ('walls','distressed dark timber boarding'),
                          ('thematic_structure','dark stained forest thinnings')]:
        if phrase in normal:
            materials[field] = phrase
    section = bool(re.search(r'\bsections?\b', label, re.I))
    return {'native_rotation_degrees': page.rotation, 'native_media_box_points': list(page.mediabox),
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'declared_sheet_role': 'vertical_section' if section else 'horizontal_site_plan',
            'source_state_from_attachment_label': 'existing' if 'existing' in label.lower() else 'proposed',
            'horizontal_geometry_eligible': not section,
            'role_basis': 'Observed attachment label; extracted text alone can contain overpainted prior titles',
            'overlapping_incompatible_title_markers': conflicts,
            'text_visibility_review_required': bool(conflicts),
            'reference_notes': inspect_reference_notes(text), 'level_claims': claims,
            'material_text_candidates': materials, 'materials_as_built_verified': False,
            'untyped_xy_annotation_present': bool(re.search(r'\bX=\d+\s+Y=\d+', text)),
            'drawing_family_373_95_printed': '373/95' in text,
            'revision_A_note_printed': bool(re.search(r'Rev A\s+28\.7\.16', text)),
            'registration_verified': False}


def review(receipt_path, directory):
    receipt_path, directory = Path(receipt_path), Path(directory)
    receipt = json.loads(receipt_path.read_text())
    if receipt['application_reference'] != 'SMD/2016/0315' or len(receipt['documents']) > 30:
        raise ValueError('Bounded SW8 source batch required')
    documents = []
    for row in receipt['documents']:
        if row['status'] != 'downloaded':
            documents.append({'attachment_id':row['attachment_id'],'status':'source_unavailable'});continue
        path = directory / (row['sha256'] + '.pdf')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Acquired PDF checksum mismatch')
        with fitz.open(stream=data, filetype='pdf') as document:
            if len(document) != row['pages'] or len(document) > 100:
                raise ValueError('Source page identity mismatch')
            pages = [{'page': i + 1, **inspect_page(p, row['attachment_label'])} for i, p in enumerate(document)]
        documents.append({'attachment_id':row['attachment_id'], 'source_sha256':row['sha256'],
                          'attachment_label':row['attachment_label'], 'url':row['url'], 'pages':pages})
    return {'status':'source_section_constraints_only',
            'source_receipt_sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            'documents':documents,
            'limitations':['Section level marks and planning parameters are not a verified ODN height datum.',
                           'A section projection does not provide a 3D ride centreline or support positions.',
                           'Material text describes proposals, not independently verified as-built materials.',
                           'Native PDF text can remain beneath overpainting; claims require visible-source review.',
                           'An untyped X/Y annotation is not a national-grid control point.'],
            'accepted_controls':0,'accepted_checkpoints':0,'world_geometry_additions':0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ['receipt','directory','output']:p.add_argument('--'+key, required=True)
    a=p.parse_args();r=review(a.receipt,a.directory);Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({'documents':len(r['documents']), 'section_pages':sum(p['declared_sheet_role']=='vertical_section' for d in r['documents'] for p in d.get('pages',[])),
                      'pages_with_title_conflicts':sum(bool(p['overlapping_incompatible_title_markers']) for d in r['documents'] for p in d.get('pages',[]))}))

if __name__ == '__main__':main()
