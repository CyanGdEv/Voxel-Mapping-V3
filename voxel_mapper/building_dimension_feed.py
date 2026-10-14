"""Recompute and compare plan enclosures with source-linked elevation regions."""
import copy
import hashlib
import math
from pathlib import Path
import re

from shapely.geometry import shape

from .building_spec import digest
from .generation_cycles import atomic_json
from .source_archive import load_json

VERSION = 'building-dimension-feed-v1'
DEFAULTS = {'max_comparisons': 100000, 'tolerance_m': .25}


def compare(hypotheses, regions, *, options=None):
    """Retain all diagnostic extent pairs; never choose or stretch a footprint."""
    opts = {**DEFAULTS, **(options or {})}
    if (set(opts) != set(DEFAULTS) or type(opts['max_comparisons']) is not int
            or not 1 <= opts['max_comparisons'] <= DEFAULTS['max_comparisons']
            or type(opts['tolerance_m']) not in (int, float)
            or not .001 <= opts['tolerance_m'] <= .25):
        raise ValueError('Bounded dimension comparison options required')
    candidates = hypotheses['candidates']
    if len(candidates) > 128 or len(regions) > 1024:
        raise ValueError('Bounded enclosure and region lists required')
    if len({c['id'] for c in candidates}) != len(candidates) or len({r['id'] for r in regions}) != len(regions):
        raise ValueError('Distinct source candidate identities required')
    base = {'version': VERSION, 'options': opts, 'hypotheses_sha256': digest(hypotheses),
            'regions_sha256': digest(regions), 'candidate_count': len(candidates), 'region_count': len(regions),
            'comparisons': [], 'selected_physical_footprint_id': None,
            'complete_building_specs_generated': 0, 'training_labels_generated': 0,
            'park_world_blocks_added': 0, 'source_geometry_changed': False,
            'physical_correspondence_verified': False}
    if hypotheses.get('status') != 'mixed_source_enclosure_hypotheses_only':
        return {**base, 'status': 'withheld_incomplete_footprint_hypotheses', 'checks': 0}
    measurements = []
    for region in sorted(regions, key=lambda r: r['id']):
        if region['coordinate_frame'] != 'pdf_native_points_y_up':
            raise ValueError('Native source region coordinates required')
        polygon = shape(region['display_geometry'])
        if (polygon.geom_type != 'Polygon' or not polygon.is_valid or polygon.is_empty
                or sum(len(r.coords) for r in [polygon.exterior, *polygon.interiors]) > 4096):
            raise ValueError('Bounded valid source region required')
        unit = region['nominal_metres_per_pdf_point_candidate']
        if type(unit) not in (int, float) or not .0001 <= unit <= 4:
            raise ValueError('Bounded nominal source scale required')
        width = (polygon.bounds[2] - polygon.bounds[0]) * unit
        measurements.append((region, width, digest(region)))
    comparisons = []; checks = 0
    for candidate in sorted(candidates, key=lambda c: c['id']):
        candidate_sha = digest(candidate)
        review = candidate.get('dimension_review', {})
        for channel, key in [('raw_nominal', 'raw_nominal_extent_dimensions_m'),
                             ('inverse_layout_hypothesis', 'inverse_layout_extent_candidates_m')]:
            lengths = review.get(key)
            if lengths is None:
                continue
            if (not isinstance(lengths, list) or len(lengths) != 2
                    or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in lengths)):
                raise ValueError('Finite positive diagnostic enclosure extents required')
            for axis, length in zip(('long_extent', 'short_extent'), lengths):
                for region, width, region_sha in measurements:
                    checks += 1
                    if checks > opts['max_comparisons']:
                        return {**base, 'status': 'withheld_comparison_budget', 'checks': checks}
                    difference = length - width
                    comparisons.append({'candidate_id': candidate['id'], 'candidate_sha256': candidate_sha,
                        'candidate_boundary_gap_ids': candidate['boundary_gap_ids'],
                        'plan_document_sha256': hypotheses['document_sha256'], 'plan_page': hypotheses['page'],
                        'extent_axis': axis, 'measurement_channel': channel, 'plan_extent_m': length,
                        'region_id': region['id'], 'region_sha256': region_sha,
                        'region_source_record_sha256': region['source_record_sha256'],
                        'elevation_document_sha256': region['document_sha256'], 'elevation_page': region['page'],
                        'view_key_candidate': region['view_key_candidate'],
                        'component_class_candidate': region.get('component_class_candidate'),
                        'region_width_m': width, 'signed_difference_m': difference,
                        'status': ('within_diagnostic_window' if abs(difference) <= opts['tolerance_m']
                                   else 'outside_diagnostic_window'),
                        'comparison_scope': 'enclosure_extent_vs_independent_region_not_complete_facade',
                        'scale_application_verified': False, 'physical_correspondence_verified': False})
    return {**base, 'status': 'source_dimension_hypotheses_only', 'checks': checks, 'comparisons': comparisons}


def _read(path):
    with Path(path).open('rb') as stream:
        data = stream.read(64000001)
    if len(data) > 64000000:
        raise ValueError('Dimension evidence metadata budget exceeded')
    return load_json(data)


def prepare(config, resolve, output):
    if (not isinstance(config, dict) or config.get('version') != VERSION
            or set(config) - {'version', 'footprint', 'facade_feed', 'options'}):
        raise ValueError('Versioned automatic dimension feed required')
    footprint, feed = copy.deepcopy(config['footprint']), config['facade_feed']
    building_id = footprint['plan_audit']['building_id']
    if len(feed['buildings']) != 1 or feed['buildings'][0]['building_id'] != building_id:
        raise ValueError('One common declared building scope required')
    sources = [footprint['plan_audit']['plan'], footprint['plan_audit']['reference_sheet'],
               *feed['buildings'][0]['sources']]
    def verify():
        for source in sources:
            sha = source['sha256']; path = Path(resolve(source['path']))
            if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
                raise ValueError('Pinned original source required')
            if path.stat().st_size > 20000000 or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('Original dimension source checksum or byte budget failed')
    verify()
    destination = Path(output); staged = destination.with_name(destination.name + '.partial')
    if destination.exists() or staged.exists():
        raise ValueError('Fresh dimension feed directory required')
    # Manual targets cannot influence this source-derived comparison channel.
    footprint['plan_audit'].pop('elevation_width_candidates_m', None)
    staged.mkdir(parents=True)
    from .footprint_hypotheses import prepare as propose
    from .building_facade_feed import prepare as facades
    propose(footprint, resolve, staged / 'footprint')
    facade_report = facades(feed, resolve, staged / 'facades')
    hypotheses = _read(staged / 'footprint/hypotheses.json')
    if facade_report['buildings'][0]['status'] == 'invalid_facade_source_input':
        report = {'version': VERSION, 'status': 'withheld_incomplete_facade_evidence',
                  'comparisons': [], 'selected_physical_footprint_id': None,
                  'complete_building_specs_generated': 0, 'training_labels_generated': 0,
                  'park_world_blocks_added': 0}
    else:
        regions = _read(staged / 'facades/building-0000/regions.json')['regions']
        report = compare(hypotheses, regions, options=config.get('options'))
    report.update(building_id=building_id, config_sha256=digest(config),
                  declared_scope_verified=False, manual_width_targets_used=False,
                  original_source_sha256=sorted({s['sha256'] for s in sources}))
    atomic_json(staged / 'comparisons.json', report)
    atomic_json(staged / 'review-queue.json', {'version': VERSION, 'report_sha256': digest(report),
        'original_source_sha256': report['original_source_sha256'], 'outcome': None,
        'requirements': ['exterior_boundary_and_void_identity', 'complete_facade_extent',
                         'view_state_scale_revision', 'independent_registration'],
        'training_labels_generated': 0})
    if sum(p.stat().st_size for p in staged.rglob('*') if p.is_file()) > 512000000:
        raise ValueError('Dimension feed output byte budget exceeded')
    verify()
    staged.replace(destination)
    return report
