"""Pinned retained-drawing studies -> building specs, diagnostics and review queue."""
import hashlib
import json
import math
import re
from pathlib import Path
from .building_spec import from_study, build, digest
from .building_learning import FEATURES
from .generation_cycles import atomic_json

VERSION = 'retained-building-feed-v1'


def _read(path, expected):
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('Explicit input checksum required')
    raw = Path(path).read_bytes()
    if len(raw) > 100000000 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Feed input checksum mismatch or byte budget exceeded')
    return json.loads(raw)


def _hashes(value):
    """Original PDF references, excluding annotation/model/render checksums."""
    out = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('source_sha256', 'document_sha256', 'floor_sha256', 'roof_plan_sha256') and isinstance(child, str): out.add(child)
            if key == 'source_pdf_sha256':
                out.update(child.values() if isinstance(child, dict) else [child])
            out.update(_hashes(child))
    elif isinstance(value, list):
        for child in value: out.update(_hashes(child))
    if any(not isinstance(s, str) or not re.fullmatch('[0-9a-f]{64}', s) for s in out):
        raise ValueError('Malformed original source hash')
    return out


def _finite(value, low=0, high=10000):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Finite bounded source diagnostic required')
    return value


def _agreement(difference, bound):
    difference = _finite(difference, -10000, 10000); bound = _finite(bound)
    if bound <= 0: raise ValueError('Positive comparison bound required')
    return max(0., 1-abs(difference)/bound), abs(difference) <= bound


def diagnostics(model, assets, source_coverage):
    """Missing diagnostics score zero with explicit missing-feature inventory."""
    values = dict.fromkeys(FEATURES, 0.)
    values['source_coverage'] = source_coverage
    values['topology_quality'] = 1.  # Set only after the shared mesh validator succeeds.
    missing = {'boundary_support','view_agreement','dimension_agreement','opening_support'}
    dimensions_consistent = False
    if 'width_check' in model:
        width = model['width_check']
        score, dimensions_consistent = _agreement(width['difference_m'], width['combined_sampling_bound_m'])
        values['dimension_agreement'] = score; values['view_agreement'] = score
        missing -= {'dimension_agreement','view_agreement'}
    # Retained plan normalization reviews provide source-derived differences,
    # not inferred physical dimensions. No filenames or building names are used.
    for asset in assets:
        if 'normalized_minus_elevation_metres' in asset:
            diffs = asset['normalized_minus_elevation_metres']
            if not isinstance(diffs,list) or len(diffs) != 2: raise ValueError('Two plan/elevation differences required')
            agreements = [_agreement(v,.25) for v in diffs]
            values['dimension_agreement'] = min(v[0] for v in agreements)
            values['view_agreement'] = values['dimension_agreement']
            dimensions_consistent = all(v[1] for v in agreements)
            missing -= {'dimension_agreement','view_agreement'}
        rows = asset.get('opening_rows')
        if rows is not None:
            if not isinstance(rows,list) or not 1 <= len(rows) <= 128: raise ValueError('Bounded opening diagnostics required')
            supported = perimeter = 0.
            for row in rows:
                length = _finite(row['reviewed_perimeter_pixels'], 0, 100000)
                supported += length * _finite(row['near_source_fraction'], 0, 1)
                perimeter += length
            if not perimeter: raise ValueError('Nonempty opening perimeter required')
            values['boundary_support'] = supported/perimeter
            # Near-source drawing support is distinct from a complete eligible outline.
            values['opening_support'] = sum(r.get('status') == 'unique_review_trace_refinement_candidate' for r in rows)/len(rows)
            missing -= {'boundary_support','opening_support'}
    return values, sorted(missing), dimensions_consistent


def prepare(config, resolve, output):
    if config.get('version') != VERSION:
        raise ValueError('Versioned retained-building feed required')
    entries = config.get('buildings')
    if not isinstance(entries,list) or not 1 <= len(entries) <= 1000:
        raise ValueError('Bounded source building feed required')
    identifiers = [e.get('building_id') for e in entries]
    if any(not isinstance(i,str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('Unique source-feed building IDs required')
    root = Path(output)
    if root.exists(): raise ValueError('Fresh source-feed directory required')
    root.mkdir(parents=True)
    job = {'version':'building-batch-v1','buildings':[]}
    reports, queue = [], []
    for entry in entries:
        report = {'building_id':entry['building_id'],'status':'invalid_source_input'}
        try:
            model = _read(resolve(entry['model']), entry['model_sha256'])
            assets = []; pins = {'model':entry['model_sha256']}
            model_asset_hashes = set()
            for key in ('input_sha256', 'vertical_input_sha256'):
                model_asset_hashes.update(model.get(key, {}).values())
            asset_entries = entry.get('diagnostics', [])
            if not isinstance(asset_entries,list) or len(asset_entries)>64: raise ValueError('Diagnostic input budget exceeded')
            for index, asset in enumerate(asset_entries):
                diagnostic = _read(resolve(asset['path']), asset['sha256'])
                if asset['sha256'] not in model_asset_hashes and diagnostic.get('corrected_model_sha256') != entry['model_sha256']:
                    raise ValueError('Diagnostic is not bound to this exact model')
                assets.append(diagnostic)
                pins[f'diagnostic-{index}'] = asset['sha256']
            required = _hashes(model) | set().union(*[_hashes(a) for a in assets])
            if not required: raise ValueError('Study has no original PDF source references')
            corpus = [resolve(p) for p in entry.get('source_directories', [])]
            if len(corpus)>16: raise ValueError('Source directory budget exceeded')
            verified, missing = [], []
            for source in sorted(required):
                paths = [Path(p)/(source+'.pdf') for p in corpus]
                existing = [p for p in paths if p.exists()]
                if not existing: missing.append(source); continue
                for p in existing:
                    if p.stat().st_size>32000000 or hashlib.sha256(p.read_bytes()).hexdigest()!=source:
                        raise ValueError('Original PDF source checksum changed')
                verified.append(source)
            spec = from_study(model, entry['building_id'], entry['model_sha256']); geometry = build(spec)
            features, missing_features, dimensions_consistent = diagnostics(model, assets, len(verified)/len(required))
            state = geometry['source_state']
            candidate = {'id':'retained-'+entry['model_sha256'][:16], 'spec':spec, 'features':features,
                         'gates':{'source_verified':not missing and state=='existing',
                                  'identity_verified':False, # Independent physical identity is not supplied by a preview.
                                  'dimensions_verified':dimensions_consistent,
                                  'topology_verified':True},
                         'source_feed':{'version':VERSION,'input_sha256':pins,'original_pdf_sha256':sorted(required),
                                        'verified_pdf_sha256':verified,'missing_pdf_sha256':missing,
                                        'missing_features':missing_features,'source_state':state,
                                        'automatic_trace_discovery':False}}
            candidate['candidate_sha256'] = digest(candidate)
            job['buildings'].append({'building_id':entry['building_id'],'candidates':[candidate]})
            queue.append({'building_id':entry['building_id'],'candidate_id':candidate['id'],
                          'candidate_sha256':candidate['candidate_sha256'], 'features':features,
                          'source_sha256':sorted(required), 'outcome':None,'review_basis':None,
                          'review_scope':'whole local candidate correctness; physical placement not established'})
            report.update(status='candidate_prepared',source_state=state,component_meshes=len(geometry['components']),
                          features=features,missing_features=missing_features,
                          verified_source_pdfs=len(verified),missing_source_pdfs=len(missing),
                          failed_gates=[k for k,v in candidate['gates'].items() if not v])
        except (ValueError,KeyError,TypeError,OSError) as error:
            report['reason'] = str(error)
        reports.append(report)
    report = {'version':VERSION,'config_sha256':digest(config),'buildings':reports,
              'candidate_buildings':len(job['buildings']),'training_labels_generated':0,'park_world_blocks_added':0}
    review_queue = {'version':'building-review-queue-v1','records':queue}
    review_queue['content_sha256'] = digest(review_queue)
    atomic_json(root/'buildings.json',job); atomic_json(root/'review-queue.json',review_queue)
    atomic_json(root/'report.json',report)
    return job, report


def feedback_from_reviews(queue, decisions):
    """Bind external reviews to exact candidates, computed features and source sets."""
    if queue.get('version')!='building-review-queue-v1' or decisions.get('version')!='building-review-decisions-v1':
        raise ValueError('Versioned review queue and decisions required')
    if queue.get('content_sha256') != digest({k:v for k,v in queue.items() if k!='content_sha256'}):
        raise ValueError('Review queue changed')
    rows = queue['records']; reviews = decisions['records']
    if not isinstance(rows,list) or not isinstance(reviews,list) or len(rows)>10000 or len(reviews)>10000:
        raise ValueError('Review record budget exceeded')
    index = {}
    for row in rows:
        key=(row['building_id'],row['candidate_sha256'])
        if key in index: raise ValueError('Duplicate review queue candidate')
        index[key]=row
    output=[]; seen=set()
    for review in reviews:
        key=(review['building_id'],review['candidate_sha256'])
        if key not in index or key in seen: raise ValueError('Unknown or duplicate reviewed candidate')
        seen.add(key)
        if review.get('outcome') not in ('accepted','rejected') or review.get('review_basis') not in ('independent_review','source_verified'):
            raise ValueError('Explicit reviewed outcome required')
        if not isinstance(review.get('review_reference'),str) or not review['review_reference'].strip():
            raise ValueError('External review reference required')
        original=index[key]
        output.append({'id':digest(review),'building_id':original['building_id'],
                       'candidate_sha256':original['candidate_sha256'],'features':original['features'],
                       'source_sha256':original['source_sha256'],'outcome':review['outcome'],
                       'review_basis':review['review_basis'],'review_reference':review['review_reference']})
    return {'version':'building-feedback-v1','records':output,'queue_sha256':digest(queue),'decisions_sha256':digest(decisions)}
