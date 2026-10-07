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
    'materials': r'\btarmac\b|\basphalt\b|\bconcrete\b|\btimber\b|\bbrick\b|\bstone\b|\bgravel\b',
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


def inspect_drawings(documents, output, max_pages=2, max_paths=150_000):
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
                row['omitted_pages'] = max(0, len(pdf)-max_pages)
                for index in range(min(len(pdf), max_pages)):
                    page = pdf[index]
                    lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])}
                             for block in page.get_text('dict')['blocks'] if 'lines' in block
                             for line in block['lines']]
                    categories, levels = annotation_evidence(lines)
                    detail = {'page': index+1, 'rotation': page.rotation, 'annotations': lines,
                              'categories': categories, 'ride_level_candidates': levels}
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
        # Read only already inspected/hash-linked records from the acquisition.
        inspection = json.loads((source/'alton-planning-inspection.json').read_text())
        if args.planning_cache:
            cache = Path(args.planning_cache).resolve()
            for document in inspection['documents']:
                if document.get('file'):
                    path = (cache/document['file']).resolve()
                    if path.is_relative_to(cache):
                        document['local_pdf'] = str(path)
    else:
        quality = run_auto(output, location='Alton Towers — Wicker Man BASELINE ONLY', bounds=BBOX,
                           planning_cache=args.planning_cache, planning_applications=APPLICATIONS)
        inspection = quality['council_drawings']
    from .alton_discovery import document_role
    for document in inspection['documents']:
        document['role'] = document_role(document['title'])[0]
    evidence = inspect_drawings(inspection['documents'], output)
    discovery_path = (Path(args.source_output) if args.source_output else output)/'alton-planning-discovery.json'
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
    (output/'wicker-man-acceptance.json').write_text(json.dumps(result, indent=2))
    (output/'quality-report.json').write_text(json.dumps(quality, indent=2))
    print(json.dumps(result, indent=2))
    if result['status'] != 'passed':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
