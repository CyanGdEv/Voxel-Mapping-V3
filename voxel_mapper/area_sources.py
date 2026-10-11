"""Audit explicit planning-to-area associations without accepting world geometry."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .generation_cycles import atomic_json


def bind_associations(config, catalogue, registry):
    """Only reviewed, context-pinned official application links enter selection."""
    result = copy.deepcopy(config)
    areas = {a['id']: a for a in result['areas']}
    accepted, rejected = [], []
    for association in registry['associations']:
        area_id = association['area_id']
        reference = association['application_reference']
        docs = [d for d in catalogue['entries']
                if d.get('applicationReference', d.get('application_reference')) == reference]
        contexts = {d.get('application_context', '') for d in docs}
        url = urlparse(association['application_url'])
        reason = None
        if area_id not in areas:
            reason = 'Unknown area'
        elif not docs:
            reason = 'Application absent from catalogue'
        elif (url.scheme != 'https' or url.hostname not in config['official_hosts']
              or url.port is not None or url.username is not None
              or url.path != '/portal/servlets/ApplicationSearchServlet'
              or not re.fullmatch(r'[0-9]+', parse_qs(url.query).get('PKID', [''])[0])):
            reason = 'Application URL is not an allowed official application page'
        elif not association['context_contains'].strip():
            reason = 'Nonempty location marker required'
        elif not any(association['context_contains'].lower() in context.lower()
                     and hashlib.sha256(context.encode()).hexdigest()
                     == association['application_context_sha256'] for context in contexts):
            reason = 'Application context changed or location marker absent'
        elif not any(d.get('discovery_source') == association['application_url'] for d in docs):
            reason = 'Catalogue does not bind this official application page'
        if reason:
            rejected.append({'area_id': area_id, 'application_reference': reference, 'reason': reason})
            continue
        area = areas[area_id]
        if reference not in area['application_references']:
            area['application_references'].append(reference)
        evidence = area.setdefault('application_associations', [])
        if association not in evidence:
            evidence.append(copy.deepcopy(association))
        area['source_selection_status'] = 'associated; sheet location and reconstruction remain unaccepted'
        accepted.append(copy.deepcopy(association))
    coverage = []
    for area in result['areas']:
        refs = set(area['application_references'])
        docs = [d for d in catalogue['entries']
                if d.get('applicationReference', d.get('application_reference')) in refs]
        coverage.append({'area_id': area['id'], 'applications': len(refs),
                         'candidate_document_records': len(docs),
                         'status': 'associated' if docs else 'awaiting_applications',
                         'search_queries': registry.get('pending_search_queries', {}).get(area['id'], [])})
    audit = {'accepted_associations': accepted, 'rejected_associations': rejected,
             'coverage': coverage, 'pending_related_applications': registry.get('pending_related_applications', {}),
             'world_geometry_additions': 0,
             'scope': 'Document selection only; shared applications require sheet and geographic review'}
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', required=True)
    parser.add_argument('--registry', default=str(Path(__file__).parent / 'data/alton-area-associations.json'))
    parser.add_argument('--output-job', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    job = Path(args.job).resolve()
    config = json.loads(job.read_text())
    catalogue = json.loads((job.parent / config['catalogue']).read_text())
    bound, report = bind_associations(config, catalogue, json.loads(Path(args.registry).read_text()))
    # Moving a job must not silently change the meaning of relative asset paths.
    for key in ('catalogue', 'work_directory', 'initial_base_world'):
        if bound.get(key):
            bound[key] = str((job.parent / bound[key]).resolve())
    for key in ('source_directories', 'supplemental_catalogues'):
        bound[key] = [str((job.parent / p).resolve()) for p in bound.get(key, [])]
    for area in bound['areas']:
        if area.get('reconstruction_job'):
            area['reconstruction_job'] = str((job.parent / area['reconstruction_job']).resolve())
    atomic_json(Path(args.output_job), bound)
    atomic_json(Path(args.report), report)
    print(json.dumps({'accepted': len(report['accepted_associations']),
                      'rejected': len(report['rejected_associations']), 'coverage': report['coverage']}))


if __name__ == '__main__':
    main()
