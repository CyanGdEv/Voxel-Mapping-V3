"""Original native plan/elevation faces -> bounded, unaccepted local surface studies."""
import hashlib
import json
import math
from pathlib import Path

from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon, LineString, box, shape
from shapely.geometry.polygon import orient

from .building_spec import build, digest, FRAME
from .building_learning import FEATURES
from .generation_cycles import atomic_json
from . import building_pdf_discovery as discovery
from .glyph_visibility import VERSION as GLYPH_VERSION, INK_VERSION
from .mapped_alignment_checks import printed_scale_review, VERSION as SCALE_VERSION

VERSION = 'cross-view-building-v1'
SIDES = ('y_min', 'y_max', 'x_min', 'x_max')
DEFAULTS = {'dimension_tolerance_m': .25, 'max_checks': 100000, 'max_faces_per_view': 256}


def _options(values):
    if not isinstance(values, dict): raise ValueError('Cross-view options must be an object')
    result = {**DEFAULTS, **values}
    if set(result) != set(DEFAULTS): raise ValueError('Unknown cross-view option')
    t = result['dimension_tolerance_m']
    if type(t) not in (int, float) or not math.isfinite(t) or not .001 <= t <= .25:
        raise ValueError('Bounded cross-view dimension tolerance required')
    for key, limit in [('max_checks', 100000), ('max_faces_per_view', 256)]:
        if type(result[key]) is not int or not 1 <= result[key] <= limit:
            raise ValueError('Bounded cross-view work required')
    return result


def _views(building):
    views = building.get('views', [])
    if not isinstance(views, list) or len(views) > 5: raise ValueError('At most five source views required')
    identities = set(); slots = set(); captions = set()
    if any(not isinstance(s, dict) or not isinstance(s.get('sha256'), str) for s in building['sources']):
        raise ValueError('Pinned original source entries required')
    sources = {s['sha256'] for s in building['sources']}
    for view in views:
        if not isinstance(view, dict): raise ValueError('Source view must be an object')
        if set(view)-{'id', 'kind', 'document_sha256', 'page', 'bounds_pdf_native',
                     'caption_index', 'scope_review_reference', 'reverse_x', 'side'}:
            raise ValueError('Unknown source view binding field')
        identifier = view.get('id')
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128 or identifier in identities:
            raise ValueError('Unique bounded source view IDs required')
        identities.add(identifier)
        if view.get('document_sha256') not in sources: raise ValueError('View must bind a supplied original PDF')
        if type(view.get('page')) is not int or not 1 <= view['page'] <= 10000:
            raise ValueError('Bounded source view page required')
        if view.get('kind') not in ('floor_plan', 'elevation'): raise ValueError('Supported source view kind required')
        slot = 'floor_plan' if view['kind'] == 'floor_plan' else view.get('side')
        if slot not in ('floor_plan', *SIDES) or slot in slots: raise ValueError('Distinct local plan/facade slots required')
        slots.add(slot)
        bounds = view.get('bounds_pdf_native')
        if (not isinstance(bounds, list) or len(bounds) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
            raise ValueError('Finite ordered native view bounds required')
        if type(view.get('caption_index')) is not int or view['caption_index'] < 0:
            raise ValueError('Native view caption index required')
        caption = (view['document_sha256'], view['page'], view['caption_index'])
        if caption in captions: raise ValueError('A native caption cannot supply multiple source views')
        captions.add(caption)
        if type(view.get('reverse_x', False)) is not bool: raise ValueError('Boolean source view orientation required')
        reference = view.get('scope_review_reference')
        if reference is not None and (not isinstance(reference, str) or not reference.strip() or len(reference) > 1024):
            raise ValueError('Bounded source scope review reference required')
    return views


def _faces(row, scope, limit):
    if row.get('recovery', {}).get('status') not in ('enclosed_faces_only', 'no_eligible_linework'):
        raise ValueError('Complete native face recovery required')
    grouped = {}
    for candidate in row['source_geometry'] + row['closed_source_faces']:
        if (candidate['geometry']['type'] != 'Polygon' or candidate.get('paint_reference_truncated')
                or candidate.get('curve_approximation', {}).get('cubic_segments')): continue
        polygon = shape(candidate['geometry'])
        if (not polygon.is_valid or polygon.is_empty or not scope.covers(polygon)
                or sum(len(r.coords) for r in [polygon.exterior, *polygon.interiors]) > 256): continue
        key = polygon.normalize().wkb_hex
        grouped.setdefault(key, {'polygon': polygon, 'source_candidates': []})['source_candidates'].append(candidate)
        if len(grouped) > limit: raise ValueError('Native view face budget exceeded; refine reviewed scope')
    return [grouped[k] for k in sorted(grouped)]


def _view(view, row, pdf, limit):
    if row['status'] != 'native_drawing_candidates_discovered':
        raise ValueError('Complete original native discovery required')
    if not view.get('scope_review_reference'): raise ValueError('Source-bound view scope review required')
    captions = row['caption_layout']['view_captions']
    if view['caption_index'] >= len(captions): raise ValueError('Requested native view caption is absent')
    caption = captions[view['caption_index']]; claim = caption['printed_claim']
    if caption['glyph_screen']['status'] != 'raster_consistent_candidate':
        raise ValueError('Native caption visibility remains unresolved')
    if view['kind'] == 'floor_plan':
        if claim.get('view_kind') != 'plan' or 'floor' not in (claim.get('plan_level_or_form') or ''):
            raise ValueError('Floor-plan caption required; roof/key plans are not wall footprints')
    elif claim.get('view_kind') != 'elevation': raise ValueError('Elevation caption required')
    state = claim.get('printed_state')
    if state not in ('existing', 'proposed'): raise ValueError('Native view drawing state remains unresolved')
    scope = box(*view['bounds_pdf_native'])
    if not scope.covers(shape(caption['label_geometry'])): raise ValueError('Caption lies outside reviewed source scope')
    import pymupdf
    from .drawing_geometry import native_inverse
    with pymupdf.open(pdf) as document:
        page = document[view['page']-1]; rotation = page.rotation
        kind, value = document.xref_get_key(page.xref, 'UserUnit')
        if kind != 'null' and float(value) != 1: raise ValueError('Nonstandard PDF UserUnit remains unresolved')
        if page.cropbox != page.mediabox: raise ValueError('Cropped source view scale remains unresolved')
        try:
            page.set_rotation(0); frame = box(*(page.rect*native_inverse(page)))
        finally: page.set_rotation(rotation)
        if not frame.covers(scope): raise ValueError('Source view scope lies outside original page')
    denominator = claim.get('printed_scale_denominator')
    scale_receipt = {'basis': 'visible_native_view_caption', 'caption': caption}
    if denominator is None:
        scale_receipt = printed_scale_review(pdf, view['page'])
        if scale_receipt['status'] != 'one_visible_printed_scale': raise ValueError('Source view scale remains unresolved')
        factor = scale_receipt['expected_metres_per_pdf_point']
    else: factor = denominator*.0254/72
    return {'input': view, 'row': row, 'state': state, 'factor': factor,
            'scale_review': scale_receipt, 'faces': _faces(row, scope, limit)}


def _surface(polygon, transform, *, flip=False):
    vertices = []; indices = {}; triangles = []
    for triangle in constrained_delaunay_triangles(polygon).geoms:
        row = []
        for point in list(orient(triangle, sign=1).exterior.coords)[:-1]:
            xyz = tuple(transform(*point))
            if xyz not in indices: indices[xyz] = len(vertices); vertices.append(list(xyz))
            row.append(indices[xyz])
        triangles.append(list(reversed(row)) if flip else row)
    if not triangles: raise ValueError('Nonempty source surface required')
    return {'kind': 'mesh', 'mesh': {'vertices': vertices, 'triangles': triangles, 'watertight': False}}


def _upper(polygon, factor, reverse, length):
    xmin, ymin, xmax, ymax = polygon.bounds
    width = (xmax-xmin)*factor; shift = (length-width)/2
    result = []
    for x in sorted({p[0] for p in polygon.exterior.coords}):
        hit = polygon.intersection(LineString([(x, ymin-1), (x, ymax+1)]))
        if hit.is_empty: raise ValueError('Source silhouette has an unresolved upper boundary')
        coordinate = (xmax-x if reverse else x-xmin)*factor+shift
        result.append([coordinate, (hit.bounds[3]-ymin)*factor])
    return sorted(result)


def _height(profile, x):
    for a, b in zip(profile, profile[1:]):
        if a[0] <= x <= b[0]: return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])
    raise ValueError('Roof profile comparison outside retained source extent')


def _roof(profiles, width, depth, tolerance):
    """Interpolate original opposing upper edges; never certify roof identity."""
    for pair, others, length, transverse, axis in [
        (('y_min', 'y_max'), ('x_min', 'x_max'), width, depth, 0),
        (('x_min', 'x_max'), ('y_min', 'y_max'), depth, width, 1)]:
        a, b = [profiles[s] for s in pair]
        if any(abs(p[0][0]) > tolerance or abs(p[-1][0]-length) > tolerance for p in (a, b)): continue
        lo, hi = max(a[0][0], b[0][0]), min(a[-1][0], b[-1][0])
        xs = sorted({lo, hi, *[x for p in (a, b) for x, _ in p if lo < x < hi]})
        if lo >= hi or any(abs(_height(a, x)-_height(b, x)) > tolerance for x in xs): continue
        if any(max(z for _, z in profiles[s])-min(z for _, z in profiles[s]) > tolerance for s in others): continue
        if any(abs(z-_height(p, end)) > tolerance for s, end in zip(others, (lo, hi))
               for _, z in profiles[s] for p in (a, b)): continue
        vertices = []; triangles = []
        for x in xs:
            for t, p in [(0, a), (transverse, b)]:
                vertices.append([x, t, _height(p, x)] if axis == 0 else [t, x, _height(p, x)])
        for i in range(len(xs)-1):
            j = 2*i; triangles.extend([[j, j+2, j+3], [j, j+3, j+1]])
        if axis == 1: triangles = [list(reversed(t)) for t in triangles]
        return {'kind': 'mesh', 'mesh': {'vertices': vertices, 'triangles': triangles, 'watertight': False}}
    raise ValueError('Opposing roof profiles or side eaves disagree; no roof interpolation emitted')


def assemble(building_id, views, options):
    """Select one rectangular plan/four-facade tuple, with no best-score guessing."""
    if set(views) != {'floor_plan', *SIDES}: raise ValueError('One floor plan and four separately scoped elevations required')
    states = {v['state'] for v in views.values()}
    if len(states) != 1: raise ValueError('Existing/proposed views cannot be assembled together')
    tolerance = options['dimension_tolerance_m']; plan = views['floor_plan']; choices = []; reviews = []; checks = 0
    for face in plan['faces']:
        polygon = face['polygon']; xmin, ymin, xmax, ymax = polygon.bounds
        if polygon.interiors or not polygon.equals(box(xmin, ymin, xmax, ymax)): continue
        width, depth = (xmax-xmin)*plan['factor'], (ymax-ymin)*plan['factor']
        if not .5 <= min(width, depth) <= max(width, depth) <= 100: continue
        matched = {}; differences = {}; counts = {}
        for side in SIDES:
            expected = width if side.startswith('y') else depth; found = []
            for candidate in views[side]['faces']:
                checks += 1
                if checks > options['max_checks']: raise ValueError('Cross-view matching budget exceeded; partial matches discarded')
                bounds = candidate['polygon'].bounds; observed = (bounds[2]-bounds[0])*views[side]['factor']
                height = (bounds[3]-bounds[1])*views[side]['factor']
                if .5 <= height <= 50 and abs(observed-expected) <= tolerance: found.append((candidate, observed-expected))
            counts[side] = len(found)
            if len(found) == 1: matched[side], differences[side] = found[0]
        reviews.append({'plan_candidate_ids': [c['id'] for c in face['source_candidates']],
                        'plan_width_m': width, 'plan_depth_m': depth, 'facade_match_counts': counts})
        if len(matched) == 4:
            used = set(); repeated = False
            for slot, selected in [('floor_plan', face), *matched.items()]:
                view = views[slot]
                keys = {(view['input']['document_sha256'], view['input']['page'], c['id'])
                        for c in selected['source_candidates']}
                if used & keys: repeated = True
                used.update(keys)
            if repeated: reviews[-1]['reason'] = 'one_native_face_reused_across_source_views'
            else: choices.append((face, matched, width, depth, differences))
    if len(choices) != 1:
        return None, {'status': 'awaiting_unique_cross_view_correspondence', 'plan_reviews': reviews,
                      'matching_checks': checks, 'complete_candidate_tuples': len(choices)}
    face, matched, width, depth, differences = choices[0]
    sources = [{'id': v['input']['id'], 'sha256': v['input']['document_sha256'], 'state': v['state']}
               for _, v in sorted(views.items())]
    components = []; evidence = {}; profiles = {}
    def component(identifier, role, geometry, refs, description):
        components.append({'id': identifier, 'role': role, 'geometry': geometry,
            'evidence': {'class': 'inferred', 'source_ids': refs, 'description': description}})
    xmin, ymin, _, _ = face['polygon'].bounds; factor = plan['factor']
    component('local_floor_reference', 'floor', _surface(face['polygon'], lambda x, y: [(x-xmin)*factor, (y-ymin)*factor, 0]),
              [plan['input']['id']], 'Original plan face at inferred local display zero; surveyed floor/datum unverified.')
    evidence['floor_plan'] = face['source_candidates']
    for side in SIDES:
        view = views[side]; polygon = matched[side]['polygon']; x0, z0, x1, _ = polygon.bounds; factor = view['factor']
        length = width if side.startswith('y') else depth; native_width = (x1-x0)*factor; reverse = view['input'].get('reverse_x', False)
        def transform(x, z, *, side=side, factor=factor, x0=x0, x1=x1, z0=z0, reverse=reverse,
                      length=length, native_width=native_width):
            along = (x1-x if reverse else x-x0)*factor+(length-native_width)/2; height = (z-z0)*factor
            return [along, 0 if side == 'y_min' else depth, height] if side.startswith('y') else [0 if side == 'x_min' else width, along, height]
        flip = (side in ('y_max', 'x_min')) != reverse
        component('facade_'+side, 'wall', _surface(polygon, transform, flip=flip), [view['input']['id']],
                  'Original native face/holes at printed scale; declared view orientation and bottom-zero alignment remain hypotheses.')
        profiles[side] = _upper(polygon, factor, reverse, length); evidence[side] = matched[side]['source_candidates']
    roof = _roof(profiles, width, depth, tolerance)
    component('interpolated_roof', 'roof', roof, [s['id'] for s in sources],
              'Inferred surface between agreeing opposing silhouette upper edges; roof material, overhang and physical identity unverified.')
    spec = {'version': 'building-spec-v1', 'coordinate_frame': FRAME, 'building_id': building_id,
            'sources': sources, 'components': components,
            'assumptions': ['Source scope review references and local facade orientations are declared inputs, not authenticated physical reviews.',
                'Selected closed faces remain physical-identity hypotheses; rectangular plan support does not prove an exterior wall footprint.',
                'Facade bottoms are aligned to local zero; vertical datum and terrain placement remain unresolved.',
                'Original widths are preserved without rescaling; tolerated discrepancies can leave joins unresolved.',
                'Roof interpolation and local floor reference are inferred display surfaces; openings are only retained source holes.',
                'Materials, interior inventory, hidden components, as-built identity and geographic placement remain unresolved.']}
    build(spec)
    return spec, {'status': 'local_cross_view_surface_candidate', 'matching_checks': checks,
        'plan_reviews': reviews, 'width_m': width, 'depth_m': depth, 'facade_width_differences_m': differences,
        'source_faces': evidence, 'view_bindings': {k: v['input'] for k, v in sorted(views.items())},
        'scale_reviews': {k: v['scale_review'] for k, v in sorted(views.items())},
        'original_geometry_rescaled': False, 'physical_identity_verified': False,
        'complete_physical_inventory_verified': False, 'world_placement_eligible': False}


def prepare(config, resolve, output):
    if not isinstance(config, dict) or config.get('version') != VERSION: raise ValueError('Versioned cross-view building feed required')
    options = _options(config.get('options', {})); buildings = config.get('buildings')
    if not isinstance(buildings, list) or not 1 <= len(buildings) <= 32: raise ValueError('Bounded cross-view building list required')
    ids = [b.get('building_id') if isinstance(b, dict) else None for b in buildings]
    if any(not isinstance(i, str) or not i or len(i) > 256 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Unique bounded cross-view building IDs required')
    for building in buildings:
        if not isinstance(building, dict) or not isinstance(building.get('sources'), list): raise ValueError('Original building source list required')
        _views(building)
    root = Path(output)
    if root.exists(): raise ValueError('Fresh cross-view output directory required')
    raw_config = {'version': discovery.VERSION, 'buildings': [{'building_id': b['building_id'], 'sources': b['sources']} for b in buildings],
                  'options': config.get('discovery_options', {})}
    # Discovery validates request/source structure and stages whole original documents.
    discovered = discovery.prepare(raw_config, resolve, root/'discovery')
    contract = {'version': VERSION, 'config_sha256': digest(config), 'options': options,
        'glyph_version': GLYPH_VERSION, 'glyph_ink_version': INK_VERSION, 'scale_version': SCALE_VERSION,
        'discovery_pages_sha256': discovered['pages_sha256'], 'discovery_contract_sha256': digest(discovered)}
    atomic_json(root/'contract.json', contract)
    data = (root/'discovery/discovery-pages.jsonl').read_bytes()
    if hashlib.sha256(data).hexdigest() != discovered['pages_sha256']: raise ValueError('Discovery feed changed')
    rows = [json.loads(line) for line in data.splitlines()]
    by_page = {(r['building_id'], r['document_sha256'], r['page']): r for r in rows}
    if len(by_page) != len(rows): raise ValueError('Distinct discovery source pages required')
    job = {'version': 'building-batch-v1', 'buildings': []}; reports = []; queue = []; reviews = []
    for index, building in enumerate(buildings):
        identifier = building['building_id']; directory = root/f'building-{index:04d}'; directory.mkdir()
        result = {'building_id': identifier, 'status': 'awaiting_cross_view_evidence', 'view_reviews': [],
                  'park_world_blocks_added': 0, 'training_labels_generated': 0}
        pages = [r for r in rows if r['building_id'] == identifier]
        result['discovered_view_claims'] = [{'document_sha256': r['document_sha256'], 'page': r['page'],
            'caption_index': i, 'text': c['text'], 'printed_claim': c['printed_claim'],
            'glyph_status': c['glyph_screen']['status'], 'view_scope_verified': False}
            for r in pages for i, c in enumerate(r.get('caption_layout', {}).get('view_captions', []))]
        try:
            source_status = next(b for b in discovered['buildings'] if b['building_id'] == identifier)
            if source_status['status'] != 'source_inventory_prepared': raise ValueError('Complete original PDF discovery required')
            sources = {s['sha256']: Path(resolve(s['path'])) for s in building['sources']}
            views = {}
            for view in _views(building):
                try:
                    row = by_page.get((identifier, view['document_sha256'], view['page']))
                    if row is None: raise ValueError('Requested view page was not discovered')
                    resolved = _view(view, row, sources[view['document_sha256']], options['max_faces_per_view'])
                    views['floor_plan' if view['kind'] == 'floor_plan' else view['side']] = resolved
                    result['view_reviews'].append({'id': view['id'], 'status': 'source_scope_candidate', 'faces': len(resolved['faces'])})
                except (ValueError, RuntimeError, KeyError, TypeError) as error:
                    result['view_reviews'].append({'id': view['id'], 'status': 'awaiting_source_view_evidence', 'reason': str(error)})
            spec, assembly = assemble(identifier, views, options)
            result.update(assembly)
            if spec is not None:
                # Recheck every original before publishing any dependent geometry.
                for sha, path in sources.items():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != sha: raise ValueError('Original PDF changed during cross-view interpretation')
                model = build(spec)
                candidate = {'id': 'cross-view-'+digest(spec)[:16], 'spec': spec,
                    'features': {**dict.fromkeys(FEATURES, 0.), 'source_coverage': 1.,
                        'dimension_agreement': max(0., 1-max(abs(v) for v in assembly['facade_width_differences_m'].values())/options['dimension_tolerance_m']),
                        'view_agreement': max(0., 1-max(abs(v) for v in assembly['facade_width_differences_m'].values())/options['dimension_tolerance_m'])},
                    'gates': {'source_verified': False, 'identity_verified': False,
                              'dimensions_verified': False, 'topology_verified': False},
                    'cross_view': {'version': VERSION, 'original_pdf_sha256': sorted(sources),
                                   'interpretation_sha256': digest(assembly), 'world_placement_eligible': False}}
                candidate['candidate_sha256'] = digest(candidate)
                atomic_json(directory/'building-spec.json', spec); atomic_json(directory/'model.json', model)
                from .study_mesh_export import write_glb
                write_glb(model, directory/'model.glb')
                job['buildings'].append({'building_id': identifier, 'candidates': [candidate]})
                reviews.append({'building_id': identifier, 'candidate_id': candidate['id'],
                    'candidate_sha256': candidate['candidate_sha256'], 'features': candidate['features'],
                    'source_sha256': sorted(sources), 'native_structural_review': None,
                    'outcome': None, 'review_basis': None,
                    'review_scope': 'Inferred local surface hypothesis; no physical acceptance or geographic placement.'})
                result['spec_sha256'] = digest(spec); result['candidate_sha256'] = candidate['candidate_sha256']
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            result.update(status='awaiting_cross_view_evidence', reason=str(error))
        atomic_json(directory/'interpretation.json', result); reports.append(result)
        queue.append({'building_id': identifier, 'status': result['status'], 'candidate_sha256': result.get('candidate_sha256'),
            'original_pdf_sha256': sorted(s['sha256'] for s in building['sources']), 'outcome': None,
            'requirements': ['authenticated_scope_and_physical_identity_review', 'source_reuse_and_as_built_state',
                             'independent_dimension_verification', 'materials_and_complete_opening_inventory',
                             'native_structural_checks', 'geographic_registration_and_vertical_datum']})
    report = {'version': VERSION, 'contract': contract, 'buildings': reports,
        'shared_specs_generated': len(job['buildings']), 'original_documents_discovered': sum(
            d['status'] == 'verified_original_pdf_discovered' for b in discovered['buildings'] for d in b['documents']),
        'training_labels_generated': 0, 'park_world_blocks_added': 0, 'world_placement_eligible': False}
    review_queue = {'version': 'building-review-queue-v1', 'records': reviews}
    review_queue['content_sha256'] = digest(review_queue)
    atomic_json(root/'building-batch.json', job); atomic_json(root/'review-queue.json', review_queue)
    atomic_json(root/'source-queue.json', {'version': VERSION, 'records': queue, 'training_labels_generated': 0})
    atomic_json(root/'report.json', report)
    return report
