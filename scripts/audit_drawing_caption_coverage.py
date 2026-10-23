"""Replay coverage and independently check exact native caption/key witnesses."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tempfile

import pymupdf

from voxel_mapper import drawing_caption_inventory
from voxel_mapper.generation_cycles import atomic_json, file_hash
from voxel_mapper.reconstruction_evidence_queue import digest


def audit(evidence, references, source_catalogue, source_directory, output):
    evidence, references, source_catalogue, source_directory, output = map(Path,
        (evidence, references, source_catalogue, source_directory, output))
    path = evidence / 'drawing-caption-coverage.json'; report = json.loads(path.read_text())
    with tempfile.TemporaryDirectory() as temp:
        fresh = drawing_caption_inventory.build(references, source_catalogue, source_directory, temp,
                                                max_checks=report['contract']['max_checks'])
        fresh.pop('directory'); assert fresh == report
    assert report['status'] == 'source_caption_coverage_only'
    checked = Counter(); candidates = {}
    for record in report['pages']:
        original = source_directory / (record['document_sha256'] + '.pdf')
        assert file_hash(original) == record['document_sha256']
        with pymupdf.open(original) as doc:
            page = doc[record['page'] - 1]; traces = page.get_texttrace()
            assert page.rotation == record['native_rotation_degrees']
            for caption in record['captions']:
                span = traces[caption['title_trace_index']]
                raw = ''.join(chr(c[0]) for c in span['chars']).strip()
                assert raw == caption['caption']
                assert list(span['bbox']) == caption['title_bbox_pdf_unrotated']
                assert not caption['artwork_assignment_verified'] and not caption['geometry_export_authorized']
                if 'source_caption_key_candidate' in caption:
                    project, sheet, number = caption['source_caption_key_candidate']
                    assert re.match(r'^Elevation\s+' + str(number) + r'\s+to\b', raw)
                    header = caption['sheet_identity_candidate']
                    header_text = ''.join(chr(c[0]) for c in traces[header['trace_index']]['chars']).strip()
                    unit = re.sub(r'\s+', '', project + '-' + str(sheet))
                    assert re.sub(r'\s+', '', header_text) == unit * header['overprint_count']
                    assert all(record['glyph_screens'][str(i)]['status'] == 'raster_consistent_candidate'
                               for i in (caption['title_trace_index'], header['trace_index']))
                    candidates[caption['id']] = [project, sheet, number]
                    checked['original_caption_and_header_witnesses'] += 1
                checked['original_caption_traces'] += 1
    refs = {r['id']: r for r in report['source_references']}
    for row in report['reference_links']:
        ref = refs[row['source_reference_id']]; key = ref.get('target_view_key_candidate')
        expected = [identity for identity, target_key in candidates.items() if key and target_key == key]
        assert expected == row['caption_candidates']
        assert row['source_reference_sha256'] == digest(ref)
        assert row['target_view_key_candidate'] == key
        assert (row['status'] == 'unique_source_caption_candidate') == (len(expected) == 1)
        assert not row['geometry_export_authorized'] and not row['artwork_assignment_verified']
        checked['independent_exact_caption_joins'] += 1
    assert not report['previous_source_holds_overridden'] and report['world_geometry_additions'] == 0
    receipt = {'status': 'passed', 'fresh_replay_identical': True, 'review_sha256': file_hash(path),
               'source_reference_review_sha256': file_hash(references), 'checked': dict(checked)}
    atomic_json(output, receipt); return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('evidence', 'references', 'source-catalogue', 'source-directory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    print(json.dumps(audit(**vars(parser.parse_args()))))
