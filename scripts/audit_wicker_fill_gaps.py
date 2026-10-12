"""Re-extract pinned plan fills and locate source gap review geometry."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

import pymupdf
from voxel_mapper.clipped_plan_fills import recover, audit_discontinuities, GAP_VERSION


def run(pdf_directory, retained):
    envelope = json.loads(Path(retained).read_text())
    entry = envelope['files']['shop-clipped-fill-review.json']
    raw = gzip.decompress(base64.b64decode(entry['gzip_base64']))
    if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Retained fill replay checksum mismatch')
    replay = json.loads(raw); pages = []
    for record in replay['network_pages']:
        sha = record['document_sha256']; number = record['page']
        pdf = Path(pdf_directory) / (sha + '.pdf')
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != sha:
            raise ValueError('Plan PDF checksum mismatch')
        with pymupdf.open(pdf) as document:
            recovered = recover(document[number - 1], sha, number)
        old = record['clipped_fill_recovery']['candidates']
        # Ignore derived nominal measurements; extraction itself must reproduce.
        keys = recovered['candidates'][0].keys() if recovered['candidates'] else []
        if json.loads(json.dumps(recovered['candidates'])) != [{k: c[k] for k in keys} for c in old]:
            raise ValueError('Pinned fill extraction did not reproduce')
        unit = record['plan_scale']['nominal_metres_per_pdf_point_candidate']
        gaps = audit_discontinuities(recovered['candidates'], unit)
        pages.append({'document_sha256': sha, 'page': number, 'fills_reproduced': len(old),
                      'nominal_metres_per_pdf_point_candidate': unit,
                      'gaps': gaps, 'gaps_with_fill_overlap': sum(bool(g['intersecting_fill_candidates']) for g in gaps)})
    return {'version': GAP_VERSION, 'retained_replay_sha256': entry['sha256'], 'pages': pages,
            'accepted_physical_openings': 0, 'accepted_registration_points': 0, 'world_geometry_additions': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-directory', required=True)
    parser.add_argument('--retained', default='evidence/wicker-shop-clipped-fill-replay.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = run(args.pdf_directory, args.retained)
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
