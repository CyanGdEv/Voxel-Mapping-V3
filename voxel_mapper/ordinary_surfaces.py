"""Ordinary contained surface labels with source-bound geometry and registration.

This adapter never treats every enclosure as paving, never repairs an open
boundary, and never assigns a label to the nearest polygon.
"""
from collections import Counter
import hashlib
import json
import math
import re
import numpy as np
import pymupdf
from pyproj import CRS
from shapely.geometry import box, shape, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from .drawing_geometry import extract_page, native_inverse
from .glyph_visibility import screen_span
from .linework_boundaries import recover_page
from .paving_palette import material_label, polygon_surface
from .reconstruction.model import Feature
from .reconstruction.registration import apply_registration, review_registration

VERSION = 'ordinary-surface-labels-v2'
# Only standalone labels. Reports, dimensions, wall/roof descriptions and title
# block prose cannot become surface finishes.
SURFACE_ROLE = re.compile(r'^(?:existing\s+)?(?:path|footpath|walkway|plaza|courtyard|paving|paved area)$', re.I)


def label_runs(traces):
    """Split spatially disjoint labels that CAD emits in one native text span."""
    runs = []
    for index, span in enumerate(traces):
        direction = span['dir']; normal = (-direction[1], direction[0]); groups = []; group = []
        def project(point, axis):
            return sum(point[k]*axis[k] for k in (0,1))
        for character_index, character in enumerate(span['chars']):
            if group:
                previous = group[-1][1]
                across = abs(project(character[2], normal)-project(previous[2], normal))
                along = project(character[2], direction)-project(previous[2], direction)
                if across > .25*span['size'] or along < -.25*span['size'] or along > 2*span['size']:
                    groups.append(group); group = []
            group.append((character_index, character))
        if group: groups.append(group)
        for group in groups:
            chars = [c for _, c in group]
            bbox = pymupdf.Rect(chars[0][3])
            for character in chars[1:]: bbox |= pymupdf.Rect(character[3])
            runs.append({**span, 'chars': chars, 'bbox': list(bbox), 'trace_indices': [index],
                         'character_indices': [i for i, _ in group]})
    return runs


def page_candidates(page, sha, page_number, *, max_labels=500, max_faces=4000):
    raw = page.get_texttrace()
    if len(raw) > 10000 or sum(len(t['chars']) for t in raw) > 500000:
        raise ValueError('Ordinary label text budget exceeded')
    parents, extraction = extract_page(page, sha, page_number)
    recovered, recovery = recover_page(parents) if parents else ([], {'status': 'no_geometry'})
    paths=page.get_drawings(extended=True)
    paints=page.get_bboxlog()
    if len(paths)>100000 or len(paints)>500000:
        raise ValueError('Ordinary drawing paint budget exceeded')
    inverse=native_inverse(page)
    later_fills=[]
    for seq,(kind,bounds) in enumerate(paints):
        if kind in ('fill-path','fill-image','fill-shade'):
            rect=pymupdf.Rect(bounds)*inverse
            later_fills.append((seq,box(rect.x0,rect.y0,rect.x1,rect.y1)))
    fill_index=STRtree([g for _,g in later_fills]) if later_fills else None
    faces = []; seen = set(); covered_boundaries=0
    for candidate in parents + recovered:
        if candidate.get('paint_reference_truncated') or candidate['geometry']['type'] != 'Polygon':
            continue
        if (candidate.get('rendering_status') != 'supported_straight_unclipped_polygon'
                and candidate.get('extraction_kind') != 'linework_boundaries'):
            continue
        if candidate.get('curve_approximation', {}).get('cubic_segments', 0):
            continue
        polygon = shape(candidate['geometry'])
        if not polygon.is_valid or polygon.is_empty:
            continue
        references=candidate.get('paint_references',[])
        ordinals=[r['ordinal'] for r in references]
        if not ordinals or any(i>=len(paths) or i<0 for i in ordinals):continue
        seqs=[paths[i].get('seqno',-1) for i in ordinals]
        overlaps=[] if fill_index is None else fill_index.query(polygon.boundary,predicate='intersects')
        if any(later_fills[int(i)][0]>max(seqs) for i in overlaps):
            covered_boundaries+=1;continue
        if all(paths[i]['type']=='f' and paths[i].get('fill') and min(paths[i]['fill'])>.98 for i in ordinals):continue
        identity = polygon.normalize().wkb_hex
        if identity in seen:
            continue
        seen.add(identity); faces.append(candidate)
        if len(faces) > max_faces:
            raise ValueError('Ordinary label polygon budget exceeded')
    geometries = [shape(f['geometry']) for f in faces]
    index = STRtree(geometries) if geometries else None
    inverse = native_inverse(page); records = []; bound = {}; screens = {}
    for run in label_runs(raw):
        text = ''.join(chr(c[0]) for c in run['chars']).strip()
        material = material_label(text)
        role = bool(SURFACE_ROLE.fullmatch(text))
        if material is None and not role:
            continue
        if len(records) >= max_labels:
            raise ValueError('Ordinary label count budget exceeded')
        rect = pymupdf.Rect(run['bbox'])
        corners = [pymupdf.Point(x, y) * inverse for x, y in
                   [(rect.x0, rect.y0), (rect.x0, rect.y1), (rect.x1, rect.y0), (rect.x1, rect.y1)]]
        from shapely.geometry import Polygon
        label = Polygon([(p.x, p.y) for p in corners])
        matches = [] if index is None else [int(i) for i in index.query(label, predicate='intersects')
                                            if geometries[int(i)].contains(label)]
        identity = hashlib.sha256(json.dumps([VERSION, sha, page_number, text, list(rect), run['trace_indices'], run['character_indices']], sort_keys=True).encode()).hexdigest()
        record = {'id': identity, 'document_sha256': sha, 'page': page_number, 'text': text,
                  'material': material, 'surface_role': role, 'label_bounds_page_points': list(rect),
                  'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'], 'candidate_ids': [faces[i]['id'] for i in matches],
                  'status': 'withheld_ambiguous_enclosures' if len(matches) > 1 else 'withheld_no_enclosure',
                  'world_geometry_additions': 0}
        if len(matches) == 1:
            screen_key = (run['trace_indices'][0], tuple(run['character_indices']))
            if screen_key not in screens:
                screens[screen_key] = screen_span(page, run, zoom=24 if run['size'] < 4 else 6)
            record['glyph_screens'] = [screens[screen_key]]
            if any(s['status'] != 'raster_consistent_candidate' for s in record['glyph_screens']):
                record['status'] = 'withheld_glyph_visibility'
            else:
                candidate = faces[matches[0]]
                record.update(status='unique_contained_surface_label', candidate_id=candidate['id'])
                bound.setdefault(candidate['id'], []).append(record)
        records.append(record)
    rows = []
    for face in faces:
        labels = bound.get(face['id'], [])
        if not labels:
            continue
        materials = [r['text'] for r in labels if r['material'] is not None]
        surface = polygon_surface(materials)
        rows.append({'candidate': face, 'label_ids': [r['id'] for r in labels],
                     'label_texts': [r['text'] for r in labels], 'surface': surface,
                     'material_basis': 'bound labels' if materials else 'stone default on labelled surface',
                     'status': 'surface_candidate' if surface else 'withheld_conflicting_materials'})
    return rows, records, {'version': VERSION, 'extraction': extraction, 'recovery': recovery,
                           'polygons': len(faces), 'covered_boundaries_withheld': covered_boundaries, 'labels': len(records), 'surface_candidates': len(rows),
                           'label_statuses': dict(Counter(r['status'] for r in records)),
                           'world_geometry_additions': 0}


def accepted_alignment(source, page_number, references, sources, printed_scales):
    """Recompute a source-bound sheet fit from independent surveyed correspondences."""
    metadata = source.metadata
    if (metadata.get('registration_document_sha256') != source.sha256
            or metadata.get('registration_page') != page_number
            or metadata.get('registration_coordinate_frame') != 'pdf_native_points_y_up'
            or metadata.get('local_landmark_identity_verified') is not True):
        raise ValueError('Source-bound native sheet landmark identities required')
    report = metadata.get('horizontal_registration_review', {})
    if len(printed_scales) != 1:
        raise ValueError('One unambiguous printed scale required')
    scale = next(iter(printed_scales)) * .0254 / 72
    if not 0 < scale <= 10000 * .0254 / 72:
        raise ValueError('Bounded printed scale required')
    refs = {r['id']: r for r in references}
    if len(refs) != len(references):
        raise ValueError('Duplicate independent landmark reference identity')
    groups = []
    for role, key in [('control', 'control_pairs'), ('checkpoint', 'checkpoint_pairs')]:
        group = report.get(key, [])
        if not isinstance(group, list) or len(group) > 1000:
            raise ValueError('Bounded sheet registration correspondences required')
        for point in group:
            ref = refs.get(point.get('id')); survey = sources.get(point.get('source_id'))
            accuracy = point.get('accuracy_m')
            if (survey is None or survey.kind != 'survey' or survey.registration_status != 'accepted'
                    or survey.metadata.get('physical_landmarks_verified') is not True
                    or not re.fullmatch('[0-9a-f]{64}', str(survey.sha256))
                    or survey.sha256 == source.sha256 or CRS.from_user_input(survey.crs) != CRS.from_user_input(source.crs)
                    or ref is None or ref.get('role') != role or ref.get('source_id') != survey.id
                    or point.get('source_sha256') != survey.sha256 or point.get('target') != ref.get('target')
                    or type(accuracy) not in (int, float) or not math.isfinite(accuracy) or not 0 <= accuracy <= 1
                    or accuracy != ref.get('accuracy_m')):
                raise ValueError('Sheet fit lacks matching independent surveyed landmark evidence')
        groups.append(group)
    controls, checks = groups
    control_hashes = {p['source_sha256'] for p in controls}
    if any(p['source_sha256'] in control_hashes for p in checks):
        raise ValueError('Sheet checkpoints reuse control survey bytes')
    tolerance = report.get('tolerance_m', 1)
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 < tolerance <= 1:
        raise ValueError('One-metre sheet registration tolerance required')
    alignment = review_registration(controls, checks, tolerance_m=tolerance, expected_scale=scale)
    if alignment['status'] != 'accepted_horizontal_fit':
        raise ValueError('Independent ordinary sheet registration failed')
    bound = alignment['checkpoint_error']['max_m'] + max(p['accuracy_m'] for p in controls) + max(p['accuracy_m'] for p in checks) + scale
    if bound > tolerance:
        raise ValueError('Ordinary sheet registration error budget exceeded')
    return alignment


def surface_regions(source):
    """Validate source-bound view scopes, including excluded rooms/annotations.

    These are drawing-level evidence, not inferred surface footprints. In
    particular, polygonization and material text cannot verify boundary roles.
    """
    metadata = source.metadata
    scope = metadata.get('surface_scope', {})
    if (not isinstance(scope, dict) or scope.get('document_sha256') != source.sha256
            or scope.get('page') != metadata.get('registration_page')
            or scope.get('coordinate_frame') != 'pdf_native_points_y_up'):
        raise ValueError('Source-bound surface-plan scope required')
    regions = scope.get('regions')
    if not isinstance(regions, list) or not 1 <= len(regions) <= 100:
        raise ValueError('Bounded surface-plan regions required')
    output = []; identities = set(); total_points = 0
    for region in regions:
        if (not isinstance(region, dict) or not isinstance(region.get('id'), str)
                or not region['id'].strip() or region['id'] in identities
                or region.get('view_kind') != 'horizontal_surface_plan'
                or region.get('physical_surface_boundaries_verified') is not True
                or not isinstance(region.get('verification_reference'), str)
                or not region['verification_reference'].strip()):
            raise ValueError('Verified physical surface-plan boundary context required')
        geometry = region.get('geometry', {})
        if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
            raise ValueError('Polygon surface-plan scope required')
        rings = geometry.get('coordinates', [])
        if (not isinstance(rings, list) or not rings or len(rings) > 100
                or any(not isinstance(r, list) or not 4 <= len(r) <= 10000 for r in rings)):
            raise ValueError('Bounded surface-plan scope coordinates required')
        total_points += sum(len(r) for r in rings)
        if total_points > 200000:
            raise ValueError('Surface-plan scope point budget exceeded')
        for ring in rings:
            if ring[0] != ring[-1] or any(not isinstance(p, (list, tuple)) or len(p) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in ring):
                raise ValueError('Closed finite surface-plan scope required')
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError('Valid surface-plan scope required')
        identities.add(region['id']); output.append((region, polygon))
    return output


def features(rows, source, alignment):
    metadata = source.metadata
    if (metadata.get('reuse_allowed') is not True or source.license == 'copyright-consultation-only'
            or metadata.get('reuse_status') == 'consultation_only'):
        raise ValueError('Source geometry reuse is not permitted')
    if (metadata.get('drawing_state') not in ('existing', 'as_built')
            or metadata.get('drawing_state_verified') is not True or not metadata.get('state_verification_reference')
            or metadata.get('view_kind') not in ('horizontal_surface_plan', 'mixed_plan')
            or metadata.get('surface_label_scope_verified') is not True):
        raise ValueError('Verified existing horizontal surface-plan label scope required')
    regions = surface_regions(source)
    output = []; decisions = []
    for row in rows:
        candidate = row['candidate']; identifier = 'ordinary/' + source.sha256 + '/' + str(metadata['registration_page']) + '/' + candidate['id']
        try:
            if row['status'] != 'surface_candidate':
                raise ValueError('Contained surface finishes conflict')
            polygon = shape(candidate['geometry'])
            if (candidate.get('document_sha256') != source.sha256
                    or candidate.get('page') != metadata['registration_page']
                    or candidate.get('coordinate_frame') != 'pdf_native_points_y_up'):
                raise ValueError('Candidate does not match surface scope source/page')
            matches = [region for region, area in regions if area.covers(polygon)]
            if len(matches) != 1:
                raise ValueError('Whole candidate must belong to one verified surface-plan region')
            region = matches[0]
            def move(x, y, z=None):
                return tuple(zip(*apply_registration(np.column_stack((np.atleast_1d(x), np.atleast_1d(y))).tolist(), alignment)))
            placed = transform(move, polygon)
            feature = Feature(identifier, 'paving', mapping(placed), source.id,
                              {'surface': {'value': row['surface'], 'source': source.id,
                                           'status': 'documented' if row['material_basis'] == 'bound labels' else 'estimated'}},
                              {'document_sha256': source.sha256, 'page': metadata['registration_page'],
                               'drawing_state': metadata['drawing_state'], 'candidate_id': candidate['id'],
                               'bound_annotation_ids': row['label_ids'], 'bound_annotation_texts': row['label_texts'],
                               'material_basis': row['material_basis'], 'adapter_version': VERSION,
                               'surface_scope_region': region['id'],
                               'surface_scope_verification_reference': region['verification_reference']})
            # The user's explicit stone default is a reconstruction rule, not a
            # printed stone claim. Keep that distinction in metadata and permit
            # the rule without enabling unrelated geometric estimates.
            if row['material_basis'] != 'bound labels':
                feature.parameters['surface']['status'] = 'documented'
                feature.metadata['material_origin'] = 'user_default_stone_rule'
            feature.validate({source.id: source}, source.vertical_datum)
            output.append(feature); decisions.append({'feature_id': identifier, 'status': 'registered_semantic_feature', 'family': 'paving'})
        except (ValueError, KeyError, TypeError) as error:
            decisions.append({'feature_id': identifier, 'status': 'withheld', 'reason': str(error)})
    return output, decisions


def bridge_page(pdf, page_number, source, references, sources):
    from dataclasses import replace
    from .drawing_registration_bridge import file_hash, SCALE
    from .coordinate_text import coordinate_runs
    from pypdf import PdfReader
    if (source.kind not in ('planning', 'cad') or not re.fullmatch('[0-9a-f]{64}', str(source.sha256))
            or file_hash(pdf) != source.sha256):
        raise ValueError('Pinned ordinary planning drawing source required')
    crs = CRS.from_user_input(source.crs)
    if not crs.is_projected or any(abs(a.unit_conversion_factor - 1) > 1e-9 for a in crs.axis_info[:2]):
        raise ValueError('Projected metre CRS required')
    reader = PdfReader(pdf)
    if not 1 <= page_number <= len(reader.pages) or len(reader.pages) > 1000:
        raise ValueError('Bounded ordinary drawing page required')
    scales = {int(match[1]) for r in coordinate_runs(reader.pages[page_number-1])
              if (match := SCALE.fullmatch(r['text'].strip()))}
    alignment = accepted_alignment(source, page_number, references, sources, scales)
    registered = replace(source, registration_status='accepted', metadata={**source.metadata,
        'horizontal_registration_review': alignment})
    with pymupdf.open(pdf) as document:
        rows, labels, extraction = page_candidates(document[page_number-1], source.sha256, page_number)
    output, decisions = features(rows, registered, alignment)
    return registered, output, {'status': 'registered_semantic_features' if output else 'registered_no_supported_semantics',
        'adapter_version': VERSION, 'document_sha256': source.sha256, 'page': page_number,
        'registration': alignment, 'semantic_decisions': decisions, 'feature_count': len(output),
        'extraction_status': extraction, 'surface_label_decisions': labels, 'world_geometry_additions': 0,
        'limitations': ['Ordinary contained surface labels only; no wall, roof or report material classification.',
                       'Independent source-bound sheet registration and spatially verified physical surface-plan scope required.',
                       'Unlabelled enclosures do not imply paths or paving.']}


def audit(documents_file, output, *, max_pages=1000):
    """Inspect ordinary labels in real PDFs without asserting state or placement."""
    from pathlib import Path
    from .generation_cycles import atomic_json, file_hash
    if type(max_pages) is not int or not 1 <= max_pages <= 10000:
        raise ValueError('Bounded ordinary audit pages required')
    documents_file = Path(documents_file).resolve()
    documents = json.loads(documents_file.read_text())
    if not isinstance(documents, list) or not 1 <= len(documents) <= 1000:
        raise ValueError('Bounded ordinary audit document list required')
    resolved = []; seen = set()
    for item in documents:
        pdf = (documents_file.parent/item['file']).resolve()
        if (item['sha256'] in seen or not re.fullmatch('[0-9a-f]{64}', item['sha256'])
                or pdf.stat().st_size > 20000000 or file_hash(pdf) != item['sha256']):
            raise ValueError('Distinct checksum-matching bounded audit PDFs required')
        seen.add(item['sha256']); resolved.append((pdf, item))
    output = Path(output)
    from .glyph_visibility import VERSION as glyph_version
    contract = {'version': VERSION, 'glyph_version': glyph_version,
                'documents_sha256': file_hash(documents_file), 'max_pages': max_pages}
    if output.exists():
        report = json.loads((output/'ordinary-audit-report.json').read_text())
        if report['contract'] != contract or any(file_hash(output/name) != sha for name, sha in report['output_sha256'].items()):
            raise ValueError('Ordinary audit inputs or output changed')
        return report
    partial = output.with_name(output.name+'.partial')
    if partial.exists():
        raise ValueError('Incomplete ordinary audit; use a fresh directory')
    partial.mkdir(parents=True); pages = []; labels_total = surfaces_total = 0
    statuses = Counter()
    with (partial/'labels.jsonl').open('w') as labels_file, (partial/'surfaces.jsonl').open('w') as surfaces_file:
        for pdf, item in resolved:
            with pymupdf.open(pdf) as document:
                if len(document) > 1000 or len(pages)+len(document) > max_pages:
                    raise ValueError('Ordinary audit page budget exceeded')
                for number, page in enumerate(document, 1):
                    rows, labels, review = page_candidates(page, item['sha256'], number)
                    pages.append({'document_sha256': item['sha256'], 'page': number,
                                  'title': item.get('title'), 'source_state': item.get('source_state', 'unknown'), **review})
                    for label in labels:
                        labels_file.write(json.dumps(label, sort_keys=True)+'\n')
                        statuses[label['status']] += 1
                    for row in rows:
                        surfaces_file.write(json.dumps(row, sort_keys=True)+'\n')
                    labels_total += len(labels); surfaces_total += len(rows)
    report = {'contract': contract, 'status': 'unplaced_ordinary_surface_evidence', 'pages': pages,
              'labels': labels_total, 'surface_candidates': surfaces_total, 'label_statuses': dict(statuses),
              'registered_features': 0, 'world_geometry_additions': 0,
              'output_sha256': {name: file_hash(partial/name) for name in ('labels.jsonl', 'surfaces.jsonl')}}
    atomic_json(partial/'ordinary-audit-report.json', report); partial.replace(output)
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documents', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(audit(args.documents, args.output, max_pages=args.max_pages), indent=2))


if __name__ == '__main__':
    main()
