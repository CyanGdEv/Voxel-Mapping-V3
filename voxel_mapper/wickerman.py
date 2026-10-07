"""A bounded SW8 test which cannot pass on terrain/buildings alone.

PDF annotations and vectors remain drawing-space evidence until registered and
converted into independently verified physical components by a drawing adapter.
"""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

APPLICATIONS = ('SMD/2016/0315', 'SMD/2017/0111')
# Covers all four mapped Wicker Man track ways, station/shop and nearby plazas.
BBOX = [-1.8900, 52.9883, -1.8865, 52.9901]
REQUIREMENTS = {
    'ride_layout': r'\btrack\b|\bHP\d+\b|\bLP\d+\b',
    'ride_elevations': r'\b[HL]P\d+\s*-\s*\d',
    'sound_tunnels': r'\bsound\s+tunnel\b',
    'sound_screens': r'\bsound\s+screens?\b',
    'widths': r'\bwidth\b|\b\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*m\b',
    'materials': r'\btarmac\b|\basphalt\b|\bconcrete\b|\btimber\b|\bbrick\b|\bstone\b|\bgravel\b|pavement\s+blocks',
    'paths_plazas': r'\bplaza\b|\bpaving\b|\bboardwalk\b|\bpath\b|\bqueue\b|\bqueueline\b',
    'walls': r'\bwall\b|\brtw\b',
    'fences': r'\bfenc(?:e|es|ing)\b|\brailings\b',
    'buildings': r'\bstation\b|\bmaintenance\b|\bshop\b|\bFFL\b',
    'theming': r'\btheming\b|\benvelope\b',
}


def annotation_evidence(lines):
    """Keep locations and units; never turn nearby text into verified heights."""
    categories = {key: [] for key in REQUIREMENTS}
    levels = []
    for line in lines:
        text = line['text']
        for key, pattern in REQUIREMENTS.items():
            if re.search(pattern, text, re.I):
                categories[key].append(line)
        match = re.fullmatch(r'\s*([HL]P\d+)\s*-\s*(\d+(?:\.\d+)?)\s*', text)
        if match:
            levels.append({**line, 'point_label': match[1], 'printed_level': float(match[2]),
                           'vertical_datum': None, 'status': 'unregistered_annotation'})
    return categories, levels


def _json_geometry(value):
    if isinstance(value, dict):
        return {key: _json_geometry(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_geometry(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _json_geometry(list(value))  # Point/Rect/Quad: drawing-space values only.


def report_page_indices(pdf, max_pages=2, scan_pages=64, max_matches=12):
    """Bounded native-text search beyond cover sheets; no unbounded OCR."""
    chosen = set(range(min(len(pdf), max_pages)))
    examined = min(len(pdf), scan_pages)
    matches, ride_matches = [], []
    for index in range(examined):
        text = pdf[index].get_text('text')
        if len(text) > 500_000:
            continue
        if re.search(r'\bAOD\b|sound\s+tunnels?|ride\s+structure|ride\s+track|dark\s+stained', text, re.I):
            ride_matches.append(index)
        if re.search(r'\bAOD\b|sound\s+tunnels?|ride\s+structure|ride\s+track|dark\s+stained|\bpath\b|\bpaving\b|pavement\s+blocks|\bmaterials?\b|\bfenc\w*|\bwall\b|list\s+of\s+drawings', text, re.I):
            matches.append(index)
    # Preserve ride/height specifications before broader landscaping matches.
    priority = list(dict.fromkeys(ride_matches+matches))
    chosen.update(priority[:max_matches])
    return sorted(chosen), {'native_text_pages_scanned': examined,
                            'native_text_pages_unscanned': len(pdf)-examined,
                            'relevant_pages_omitted_by_budget': max(0, len(matches)-max_matches)}


def ride_specifications(text):
    normalized = ' '.join(text.split())
    result = []
    if re.search(r'ride structure, sound tunnels and screens would be dark stained timber', normalized, re.I):
        result.append({'components': ['ride_structure', 'sound_tunnels', 'sound_screens'],
                       'material': 'dark_stained_timber', 'status': 'proposed_document_specification',
                       'as_built_verified': False})
    match = re.search(r'proposed ride track has a spot height of (\d+(?:\.\d+)?)\s*m\s*AOD', normalized, re.I)
    if match:
        result.append({'component': 'ride_track_maximum', 'printed_level_m': float(match[1]),
                       'datum_label': 'AOD', 'datum_realization': None,
                       'status': 'proposed_document_specification', 'as_built_verified': False})
    return result


def path_specifications(text):
    """Preserve scoped proposal requirements, never assign them to every path."""
    normalized = ' '.join(text.split())
    result = []
    proposal = re.search(
        r'The path is proposed to be made of pavement blocks to the north of the '
        r'DPW \(a minimum of (\d+(?:\.\d+)?)m away from the DPW\)', normalized, re.I)
    if proposal:
        result.append({'component': 'woodland_path_north_of_deer_park_wall',
                       'material': 'pavement_blocks', 'block_type': None,
                       'minimum_wall_setback_m': float(proposal[1]),
                       'status': 'proposed_document_specification',
                       'as_built_verified': False, 'geometry_verified': False})
    grading = re.search(r'ground surrounding the DPW is proposed to be graded down to 1:(\d+(?:\.\d+)?)', normalized, re.I)
    if grading:
        result.append({'component': 'ground_surrounding_deer_park_wall',
                       'slope_vertical': 1, 'slope_horizontal': float(grading[1]),
                       'status': 'proposed_document_specification',
                       'as_built_verified': False, 'geometry_verified': False})
    return result


def inspect_drawings(documents, output, max_pages=2, max_paths=150_000, max_drawing_pages=16):
    import fitz
    output = Path(output)
    evidence = {'applications': list(APPLICATIONS), 'documents': [], 'failures': [],
                'coordinate_space': 'unrotated PDF points, x right, y down',
                'registration_verified': False, 'world_geometry_additions': 0}
    for document in documents:
        if document.get('applicationReference') not in APPLICATIONS:
            continue
        row = {key: document[key] for key in ('applicationReference', 'title', 'url', 'sha256', 'role') if key in document}
        row['pages'] = []
        try:
            path = Path(document['local_pdf'])
            if path.stat().st_size > 10_000_000 or hashlib.sha256(path.read_bytes()).hexdigest() != document['sha256']:
                raise ValueError('Drawing size/hash check failed')
            with fitz.open(path) as pdf:
                indices = list(range(min(len(pdf), max_drawing_pages)))
                if document['role'] == 'context-report':
                    indices, row['report_page_search'] = report_page_indices(pdf, max_pages)
                row['omitted_pages'] = len(pdf)-len(indices)
                row['inspection_complete'] = len(indices) == len(pdf)
                for index in indices:
                    page = pdf[index]
                    lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])}
                             for block in page.get_text('dict')['blocks'] if 'lines' in block
                             for line in block['lines']]
                    categories, levels = annotation_evidence(lines)
                    detail = {'page': index+1, 'rotation': page.rotation, 'annotations': lines,
                              'categories': categories, 'ride_level_candidates': levels,
                              'ride_specifications': ride_specifications(page.get_text('text')),
                              'path_specifications': path_specifications(page.get_text('text'))}
                    # Preserve curves, clipping/group records and style, rather
                    # than replacing this detailed plan with a bounding box.
                    if document['role'] in ('site-plan', 'landscape-plan', 'floor-plan', 'elevations'):
                        vectors = page.get_drawings(extended=True)
                        detail['vector_path_count'] = len(vectors)
                        if len(vectors) > max_paths:
                            detail['vector_status'] = 'withheld_path_budget'
                        else:
                            name = f"{document['sha256']}-page-{index+1}-vectors.json.gz"
                            with gzip.open(output/name, 'wt', encoding='utf-8') as stream:
                                json.dump(_json_geometry(vectors), stream)
                            detail.update(vector_file=name, vector_status='drawing_space_only')
                    row['pages'].append(detail)
            row['status'] = 'inspected'
        except (KeyError, OSError, ValueError, RuntimeError) as error:
            row.update(status='unavailable', reason=str(error))
            evidence['failures'].append({'url': document['url'], 'reason': str(error)})
        evidence['documents'].append(row)
    (output/'wicker-man-planning-evidence.json').write_text(json.dumps(evidence, indent=2))
    return evidence


def acceptance_report(evidence, quality, voxel_path):
    # Acceptance is based on emitted blocks, not annotation counts, approval,
    # generic OSM features or a successful .mcworld export.
    accepted = {'planning/'+d['id'] for d in quality.get('planning_geometry_decisions', [])
                if d.get('status') == 'accepted_verified_adapter_record'}
    rendered = {key: 0 for key in REQUIREMENTS}
    emitted = set()
    with Path(voxel_path).open() as stream:
        for line in stream:
            voxel = json.loads(line)
            if voxel.get('feature') in accepted:
                emitted.add(voxel['feature'])
    # A future adapter must supply component-level geometry checks; this avoids
    # counting an opaque solid building as a tunnel, fence or elevated track.
    for check in quality.get('planning_component_checks', []):
        category = check.get('category')
        if category in rendered and check.get('feature_id') in emitted and check.get('geometry_check') == 'passed':
            rendered[category] += 1
    checks = []
    for category in REQUIREMENTS:
        candidate_count = sum(len(p['categories'][category]) for d in evidence['documents'] for p in d['pages'])
        checks.append({'category': category, 'drawing_annotation_candidates': candidate_count,
                       'rendered_verified_components': rendered[category],
                       'status': 'passed' if rendered[category] else 'missing_world_geometry'})
    return {'target': 'Alton Towers — Wicker Man (SW8)', 'bbox': BBOX,
            'applications': list(APPLICATIONS), 'checks': checks,
            'status': 'passed' if all(c['status'] == 'passed' for c in checks) else 'failed_missing_planning_geometry',
            'accepted_planning_records': len(accepted), 'planning_features_with_emitted_blocks': len(emitted),
            'baseline_world_exported': bool(quality.get('world')),
            'attachment_coverage': evidence.get('attachment_coverage', {}),
            'limitations': ['Drawing annotations may describe existing, proposed or legend details',
                            'Printed ride levels need a verified vertical datum and spatial association',
                            'Planning approval alone does not confirm the built ride']}


def main():
    from .pipeline import run_auto
    from .cli import build
    from .bedrock import export_world
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--planning-cache')
    parser.add_argument('--source-output', help='Reuse an existing Alton acquisition directory for a local test')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if args.source_output:
        if output.exists() and any(output.iterdir()):
            parser.error('Output must be a fresh directory')
        output.mkdir(parents=True, exist_ok=True)
        source = Path(args.source_output).resolve()
        config = json.loads((source/'resolved-config.json').read_text())
        config.update(bbox=BBOX, location='Alton Towers — Wicker Man baseline test', clip_to_boundary=False)
        collection = json.loads((source/'input.geojson').read_text())
        collection['planning_geometry_records'] = []
        (output/'resolved-config.json').write_text(json.dumps(config, indent=2))
        quality = build(config, collection, output)
        quality['world'] = export_world(output/'voxels.jsonl', output, quality, name='Wicker Man — BASELINE ONLY')
        (output/'quality-report.json').write_text(json.dumps(quality, indent=2))
        if args.planning_cache:
            from .alton import acquire_alton
            inspection = acquire_alton(output, bounds=BBOX, cache=args.planning_cache,
                                       application_references=APPLICATIONS)
            quality['council_drawings'] = inspection
        else:
            inspection = json.loads((source/'alton-planning-inspection.json').read_text())
    else:
        quality = run_auto(output, location='Alton Towers — Wicker Man BASELINE ONLY', bounds=BBOX,
                           planning_cache=args.planning_cache, planning_applications=APPLICATIONS)
        inspection = quality['council_drawings']
    from .alton_discovery import document_role
    for document in inspection['documents']:
        document['role'] = document_role(document['title'])[0]
    evidence = inspect_drawings(inspection['documents'], output)
    discovery_path = output/'alton-planning-discovery.json'
    if not discovery_path.exists() and args.source_output:
        discovery_path = Path(args.source_output)/'alton-planning-discovery.json'
    if discovery_path.exists():
        discovery = json.loads(discovery_path.read_text())
        wanted = [d for d in discovery['documents'] if d['applicationReference'] in APPLICATIONS]
        inspected = {d['url'] for d in evidence['documents'] if d['status'] == 'inspected'}
        evidence['attachment_coverage'] = {
            'discovered_attachments': len(wanted), 'inspected_documents': len(inspected),
            'uninspected_attachments': [{'title': d['title'], 'url': d['url'], 'role': d['role']}
                                       for d in wanted if d['url'] not in inspected],
            'discovery_complete': discovery['status'] == 'checked'}
        (output/'wicker-man-planning-evidence.json').write_text(json.dumps(evidence, indent=2))
    result = acceptance_report(evidence, quality, output/'voxels.jsonl')
    from .wicker_registration import inspect_alignment
    raw_path = (Path(args.source_output) if args.source_output else output)/'osm-raw.json'
    if raw_path.exists():
        raw_osm = json.loads(raw_path.read_text())
        result['registration'] = inspect_alignment(evidence, raw_osm, output, BBOX)
        from .wicker_track import inspect_track
        result['track_association'] = inspect_track(evidence, raw_osm, result['registration'], output)
    (output/'wicker-man-acceptance.json').write_text(json.dumps(result, indent=2))
    (output/'quality-report.json').write_text(json.dumps(quality, indent=2))
    print(json.dumps(result, indent=2))
    if result['status'] != 'passed':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
