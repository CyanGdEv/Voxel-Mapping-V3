"""Search the retained planning archive for coordinate references, not controls."""
import argparse, hashlib, json, re, sys, zipfile
from pathlib import Path
import fitz
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper.survey_reference import inspect_reference_notes
from voxel_mapper.raster_location import inspect_grid_location

APPLICATIONS = {'SMD/2016/0315', 'SMD/2017/0111'}
SURVEY = '82cac12a14cd3d9d4232f409e681bd977f6c7f4f03be7b9049a6f845375543a9'
SIGNALS = re.compile(r'\b(?:topographical|OSGB36|national grid|eastings?|northings?|survey station|survey control)\b|\b(?:407\d{3}|343\d{3})\b', re.I)


def audit(archive):
    archive = Path(archive)
    with zipfile.ZipFile(archive) as z:
        raw = z.read('metadata/alton-planning-catalogue.json')
        entries = json.loads(raw)['entries']
        grouped = {}
        for entry in entries:
            if entry['file'].endswith('.pdf'):
                grouped.setdefault(entry['sha256'], []).append(entry)
        if len(grouped) > 1000:
            raise ValueError('Document budget exceeded')
        selected = []
        page_count = 0
        for sha, sources in grouped.items():
            names = {s['file'] for s in sources}
            if len(names) != 1:
                raise ValueError('Inconsistent duplicate source paths')
            name = names.pop()
            if z.getinfo(name).file_size > 100_000_000:
                raise ValueError('PDF byte budget exceeded')
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError('Catalogue/PDF checksum mismatch')
            document = fitz.open(stream=data, filetype='pdf')
            pages = []
            for index, page in enumerate(document):
                page_count += 1
                if page_count > 10000:
                    raise ValueError('Page budget exceeded')
                text = page.get_text()
                notes = inspect_reference_notes(text)
                labels = [{'axis': m[2], 'value': int(m[1]), 'text': m[0]}
                          for m in re.finditer(r'\b(\d{6})([EN])\b', text)]
                relevant = any(s['applicationReference'] in APPLICATIONS for s in sources)
                if not (relevant or SIGNALS.search(text)):
                    continue
                pages.append({'page': index + 1, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                              'extracted_text_characters': len(text),
                              'coordinate_reference_signal_count': len(SIGNALS.findall(text)),
                              'printed_grid_labels': labels, 'reference_notes': notes,
                              'numeric_location_mentions': sorted(set(re.findall(r'\b(?:407\d{3}|343\d{3})\b', text))),
                              'control_identity_verified': False})
            if pages:
                selected.append({'sha256': sha, 'archive_member': name,
                                 'sources': [{k: s[k] for k in ['applicationReference', 'title', 'url']} for s in sources],
                                 'pages': pages})
        topo = next(d for d in selected if d['sha256'] == SURVEY)
        page = topo['pages'][0]
        location = inspect_grid_location(page['printed_grid_labels'], page['reference_notes'], [-1.891, 52.988, -1.887, 52.991])
        if location['status'] != 'local_grid_requires_transform':
            raise ValueError('Known arbitrary-grid survey warning was lost')
        wicker = [d for d in selected if any(s['applicationReference'] in APPLICATIONS for s in d['sources'])]
        axis_values = {a: [v['value'] for v in page['printed_grid_labels'] if v['axis'] == a] for a in ['E', 'N']}
        extent = [min(axis_values['E']), min(axis_values['N']), max(axis_values['E']), max(axis_values['N'])]
        statement = next(d for d in wicker if d['sha256'] == '4aceb78f4d571324bed4378ee0e7ad733cc3f9d783277d85fb8bcc3170ee4eee')
        if not {'407628', '343522'} <= set(statement['pages'][0]['numeric_location_mentions']):
            raise ValueError('Wicker location mention did not reproduce')
        return {'status': 'coordinate_reference_search_only',
                'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'catalogue_sha256': hashlib.sha256(raw).hexdigest(),
                'unique_pdf_count_checked': len(grouped), 'pages_text_checked': page_count,
                'wicker_unique_pdf_count': len(wicker), 'selected_documents': selected,
                'wildwood_survey': {'sha256': SURVEY, 'printed_grid_label_extent': extent,
                                    'location_review': location,
                                    'scope': 'Wildwood, Farley Lane; not the Wicker Man shop',
                                    'scope_basis': 'Survey title block and printed grid labels',
                                    'station_table_is_registration_authority': False},
                'wicker_location_reference': {'application': 'SMD/2017/0111',
                    'source_sha256': '4aceb78f4d571324bed4378ee0e7ad733cc3f9d783277d85fb8bcc3170ee4eee',
                    'printed_numeric_reference': [407628,343522],
                    'role': 'Application location mention; physical landmark and uncertainty not established',
                    'accepted_control': False},
                'limitations': ['This text search does not inspect coordinate labels embedded solely in raster images.',
                                'No-hit pages are not proof that no survey controls exist.',
                                'Application location references are not physical correspondence points.',
                                'The retained archive is an incomplete planning subset, not all public attachments.'],
                'accepted_controls': 0, 'accepted_checkpoints': 0, 'world_geometry_additions': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', required=True); p.add_argument('--output', required=True)
    a = p.parse_args(); result = audit(a.archive)
    Path(a.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['unique_pdf_count_checked', 'pages_text_checked', 'wicker_unique_pdf_count']}))

if __name__ == '__main__':
    main()
