"""Import checksum-pinned retained planning archives into a resumable corpus."""
import argparse
import hashlib
import json

from .source_archive import (MAX_HTML_BYTES, MAX_METADATA_BYTES, MAX_PDF_BYTES,
                             application_records, checked_archive, load_json,
                             pdf_records, read_member, retain, safe_member)


def import_archive(corpus, archive, expected_sha256, hosts, *,
                   catalogue_member='metadata/alton-planning-catalogue.json',
                   applications_member='metadata/alton-applications.json', allow_partial=False):
    if type(allow_partial) is not bool:
        raise ValueError('allow_partial must be a boolean')
    hosts = set(hosts)
    if not hosts:
        raise ValueError('Explicit official portal hosts required')
    with checked_archive(archive, expected_sha256) as (source, index):
        if 'bundle.json' in index:
            from .planning_bundle import import_bundle
            return import_bundle(corpus, archive, expected_sha256, hosts, allow_partial=allow_partial)
        safe_member(catalogue_member)
        if catalogue_member not in index:
            raise ValueError('Archive catalogue is absent')
        metadata = {catalogue_member: read_member(source, index[catalogue_member], MAX_METADATA_BYTES)}
        entries = pdf_records(load_json(metadata[catalogue_member]), hosts)
        applications = []
        safe_member(applications_member)
        if applications_member in index:
            metadata[applications_member] = read_member(source, index[applications_member], MAX_METADATA_BYTES)
            applications = application_records(load_json(metadata[applications_member]), hosts)
        selected = {r['file']: ('pdf', r['sha256']) for r in entries}
        selected.update({r['cached_page']: ('application_html', r['cached_page_sha256']) for r in applications})
        missing = [{'member': name, 'kind': kind, 'sha256': sha, 'status': 'missing'}
                   for name, (kind, sha) in selected.items() if name not in index]
        # Validate every selected blob before changing catalogue/availability.
        # Partial mode permits absence only; it never permits corrupt evidence.
        for name, (kind, sha) in selected.items():
            if name in index:
                data = read_member(source, index[name], MAX_PDF_BYTES if kind == 'pdf' else MAX_HTML_BYTES, sha)
                if kind == 'pdf' and not data.startswith(b'%PDF-'):
                    raise ValueError('Retained PDF header/checksum mismatch')
        if missing and not allow_partial:
            raise ValueError('Catalogue source file is absent from retained archive')
        corpus.validate_applications(applications, hosts)
        records = [{**r, 'retained_archive_sha256': expected_sha256, 'retained_archive_member': r['file'],
                    'acquisition_provenance': ('retained_archive_catalogue_only; PDF_not_retained' if r['file'] not in index
                                               else 'checksum_verified_retained_archive; no live download')} for r in entries]
        corpus.ingest(records, hosts)
        corpus.ingest_applications(applications, hosts)
        copied = resumed = html_copied = html_resumed = 0
        for name, (kind, sha) in selected.items():
            if name not in index:
                continue
            data = read_member(source, index[name], MAX_PDF_BYTES if kind == 'pdf' else MAX_HTML_BYTES, sha)
            changed = retain(corpus.root, name, data, sha)
            if kind == 'pdf':
                copied += int(changed)
                resumed += int(not changed)
                with corpus.db:
                    corpus.db.execute("UPDATE downloads SET status='downloaded',sha=?,size=?,error=NULL WHERE expected_sha=?",
                                      (sha, len(data), sha))
            else:
                html_copied += int(changed)
                html_resumed += int(not changed)
                with corpus.db:
                    corpus.db.execute("UPDATE applications SET status='retained',sha=?,error=NULL WHERE expected_sha=?", (sha, sha))
        for name, data in metadata.items():
            retain(corpus.root, f'bundles/{expected_sha256}/{name}', data, hashlib.sha256(data).hexdigest())
    deferred = sum(r['file'] not in index for r in entries)
    report = {'status': 'retained_archive_imported', 'archive_sha256': expected_sha256,
              'catalogue_records': len(entries), 'retained_catalogue_records': len(entries) - deferred,
              'deferred_catalogue_records': deferred, 'allow_partial': allow_partial,
              'unique_pdf_blobs': copied + resumed, 'copied_blobs': copied, 'resumed_blobs': resumed,
              'expanded_pdf_bytes': sum(index[n].file_size for n, (k, _) in selected.items() if n in index and k == 'pdf'),
              'application_catalogue_available': applications_member in metadata,
              'application_records': len(applications), 'retained_application_pages': html_copied + html_resumed,
              'copied_application_pages': html_copied, 'resumed_application_pages': html_resumed,
              'missing_sources': missing, 'source_completeness': 'partial' if missing else 'selected_members_complete',
              'discovery_completeness': 'Not implied by archive completion',
              'live_downloads': 0, 'world_geometry_additions': 0}
    (corpus.root / f'archive-{expected_sha256}.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    from .planning_bulk import Corpus
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus', required=True)
    p.add_argument('--archive', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--official-host', action='append', required=True)
    p.add_argument('--catalogue-member', default='metadata/alton-planning-catalogue.json')
    p.add_argument('--applications-member', default='metadata/alton-applications.json')
    p.add_argument('--allow-partial', action='store_true')
    a = p.parse_args()
    corpus = Corpus(a.corpus)
    try:
        print(json.dumps(import_archive(corpus, a.archive, a.sha256, a.official_host,
                                        catalogue_member=a.catalogue_member, applications_member=a.applications_member,
                                        allow_partial=a.allow_partial), indent=2))
    finally:
        corpus.close()


if __name__ == '__main__':
    main()
