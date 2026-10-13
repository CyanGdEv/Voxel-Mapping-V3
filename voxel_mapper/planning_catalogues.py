"""Validate a paired portable source catalogue before automatic acquisition."""
import json
from pathlib import Path

from .source_archive import (MAX_METADATA_BYTES, application_records, load_json,
                             pdf_records)

HOST = 'publicaccess.staffsmoorlands.gov.uk'


def _read(path):
    with Path(path).open('rb') as stream:
        payload = stream.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError('Planning catalogue metadata budget exceeded')
    return load_json(payload)


def load_planning_catalogues(catalogue=None, applications=None, cache=None):
    """Explicit replay scope replaces historical seeds; it does not approve geometry.

    Unpinned missing links may still use official HTTPS recovery. Pinned records
    always keep their original content-addressed cache identity.
    """
    if catalogue is None and applications is None:
        root = Path(__file__).parent / 'data'
        return (json.loads((root / 'alton-planning-catalogue.json').read_text()),
                json.loads((root / 'alton-applications.json').read_text()))
    if catalogue is None or applications is None or cache is None:
        raise ValueError('Replayed planning catalogues require both catalogues and planning-cache')
    documents, seeds = _read(catalogue), _read(applications)
    rows = pdf_records(documents, {HOST}, allow_unpinned=True)
    app_rows = application_records(seeds, {HOST}, allow_unpinned=True)
    known = {}
    for row in app_rows:
        if not isinstance(row.get('application_context'), str):
            raise ValueError('Retained application context required')
        identity = (row['url'], row.get('cached_page_sha256'), row['application_context'])
        if row['reference'] in known and known[row['reference']] != identity:
            raise ValueError('Conflicting retained application snapshots')
        known[row['reference']] = identity
    pins = {}
    for row in rows:
        if (not isinstance(row.get('title'), str) or not row['title']
                or not isinstance(row.get('application_context'), str)):
            raise ValueError('Retained document title and application context required')
        reference = row.get('applicationReference')
        if not isinstance(reference, str) or not reference:
            raise ValueError('Retained document application reference required')
        if reference in known and row['application_context'] != known[reference][2]:
            raise ValueError('Conflicting retained application context')
        pin = row.get('sha256')
        if row['url'] in pins and pins[row['url']] != pin:
            raise ValueError('Conflicting retained PDF pins')
        pins[row['url']] = pin
    return documents, seeds
