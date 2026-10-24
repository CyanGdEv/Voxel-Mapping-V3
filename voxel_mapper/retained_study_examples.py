"""Bounded source-local supervision from retained architectural study annotations.

This catalogue does not accept whole buildings, authenticate physical identity,
create ranker feedback or promote conditional 3D/display geometry to truth.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

VERSION = 'retained-study-examples-v1'
MAX_INPUT_BYTES = 8_000_000
MAX_RECORDS = 512
MAX_POINTS = 100_000
SHA = re.compile(r'[0-9a-f]{64}')


def _pointer(*parts):
    return '/'+'/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def _geometry(kind, points):
    points = copy.deepcopy(points)
    if kind == 'Polygon':
        if points and points[0] != points[-1]:
            points.append(copy.deepcopy(points[0]))
        geometry = {'type': kind, 'coordinates': [points]}
    else:
        geometry = {'type': kind, 'coordinates': points}
    return geometry


def catalogue(repo_root):
    root = Path(repo_root).resolve()
    inputs, records, excluded, documents = {}, [], [], {}
    retained = {}
    point_count = 0

    def read(relative):
        if relative in retained:
            return retained[relative]
        path = (root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError('Bounded retained study input required: '+relative)
        data = path.read_bytes()
        if len(data) > MAX_INPUT_BYTES:
            raise ValueError('Retained study input changed beyond byte budget')
        inputs[relative] = hashlib.sha256(data).hexdigest()
        if path.suffix.lower() in ('.json', '.geojson'):
            def invalid(value):
                raise ValueError('Nonfinite retained study JSON: '+value)
            value = json.loads(data.decode('utf-8'), parse_constant=invalid)
        else:
            value = None
        retained[relative] = value
        return value

    def ref(relative, pointer=''):
        read(relative)
        return {'path': relative, 'sha256': inputs[relative], 'pointer': pointer}

    catalog_path = 'voxel_mapper/data/alton-planning-catalogue.json'
    entries = read(catalog_path)['entries']
    source_urls, source_states = {}, {}
    for entry in entries:
        sha = entry.get('sha256')
        if SHA.fullmatch(str(sha)):
            if isinstance(entry.get('url'), str) and entry['url'].startswith(('http://', 'https://')):
                source_urls.setdefault(sha, set()).add(entry['url'])
            if entry.get('state') in ('existing', 'proposed'):
                source_states.setdefault(sha, set()).add(entry['state'])

    for relative in ('evidence/wicker-shop-drawing-sources.json', 'evidence/wicker-architectural-extra-sources.json'):
        metadata = read(relative)
        def collect_urls(value):
            if isinstance(value, dict):
                sha = value.get('sha256')
                if SHA.fullmatch(str(sha)):
                    for name in ('canonical_url', 'url'):
                        url = value.get(name)
                        if isinstance(url, str) and url.startswith(('https://', 'http://')):
                            source_urls.setdefault(sha, set()).add(url)
                for child in value.values():
                    collect_urls(child)
            elif isinstance(value, list):
                for child in value:
                    collect_urls(child)
        collect_urls(metadata)

    def document(sha, url=None):
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError('Pinned source document required')
        if url:
            source_urls.setdefault(sha, set()).add(url)
        urls = source_urls.get(sha, set())
        documents[sha] = {'document_sha256': sha}
        if urls:
            documents[sha]['url'] = sorted(urls, key=lambda value: (not value.startswith('https://'), value))[0]
        return sha

    def source(sha, page=1, frame='page_points', **extras):
        document(sha)
        if type(page) is not int or page < 1 or frame not in ('render_pixels', 'page_points', 'native_y_up'):
            raise ValueError('Known source coordinate frame and positive page required')
        return {'document_sha256': sha, 'page': page, 'coordinate_frame': frame, **copy.deepcopy(extras)}

    def raster(annotation, page=1):
        sha = annotation.get('source_sha256', annotation.get('sha256'))
        size = annotation['render_size_pixels']
        render_sha = annotation['render_samples_sha256']
        if (not isinstance(size, list) or len(size) != 2
                or any(type(n) is not int or not 1 <= n <= 20000 for n in size)
                or not SHA.fullmatch(str(render_sha))):
            raise ValueError('Exact retained page render required')
        return source(sha, page, 'render_pixels', render_width_pixels=annotation.get('render_width_pixels', size[0]),
            render_size_pixels=size, render_samples_sha256=render_sha)

    def emit(identifier, building, kind, src, geometry, refs, *, level='reviewed_source_trace',
             assumptions=(), state='unknown', **extras):
        nonlocal point_count
        if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 160
                or any(r['id'] == identifier for r in records)
                or len(records) >= MAX_RECORDS or state not in ('existing', 'proposed', 'unknown')):
            raise ValueError('Bounded unique retained study record required')
        geom = copy.deepcopy(geometry)
        if geom.get('type') not in ('Polygon', 'LineString'):
            raise ValueError('Source polygon or line required')
        def count(value):
            nonlocal point_count
            if isinstance(value, list) and len(value) == 2 and all(type(n) in (int, float) for n in value):
                if any(not math.isfinite(n) or abs(n) > 1_000_000 for n in value):
                    raise ValueError('Finite bounded source coordinates required')
                point_count += 1
                return
            if not isinstance(value, list) or not value:
                raise ValueError('Nonempty source coordinate arrays required')
            for child in value:
                count(child)
        count(geom['coordinates'])
        from shapely.geometry import shape
        checked = shape(geom)
        if (checked.is_empty or not checked.is_valid
                or (geom['type'] == 'Polygon' and checked.area <= 0)
                or (geom['type'] == 'LineString' and checked.length <= 0)):
            raise ValueError('Valid nonempty retained source geometry required')
        if point_count > MAX_POINTS:
            raise ValueError('Retained study point budget exceeded')
        records.append({'id': identifier, 'building_id': building, 'kind': kind, 'source': copy.deepcopy(src),
            'target_geometry': geom, 'review_refs': copy.deepcopy(refs), 'evidence_level': level,
            'assumptions': list(assumptions), 'source_state': state, **copy.deepcopy(extras)})

    # Original pixel traces preserve annotation precision; no furniture scaling.
    path = 'evidence/wicker-architectural-outline-annotations.json'
    outline = read(path)
    for i, sheet in enumerate(outline['sheets']):
        for name, points in sheet['outlines_pixels'].items():
            building = 'wickerman-'+name.split('_')[0]
            kind = 'roof' if name.endswith('_roof') else 'wall'
            emit('wicker-outline-'+str(i)+'-'+name, building, kind, raster(sheet),
                _geometry('Polygon', points), [ref(path, _pointer('sheets', i, 'outlines_pixels', name))],
                state='proposed', assumptions=[
                    'Manually reviewed source envelope; interior pixels are not all roof or wall material.',
                    'Two-pixel endpoint sampling bound; not independent physical or as-built verification.',
                    sheet['line_role_basis']], target_role='plan_envelope')

    path = 'evidence/wicker-shop-floor-annotations.json'
    floor = read(path)
    emit('wicker-shop-floor-envelope', 'wickerman-shop', 'building', raster(floor),
        _geometry('Polygon', floor['outer_corners_pixels']), [ref(path, '/outer_corners_pixels')],
        state='proposed', assumptions=[floor['method'],
            'Original source pixels retained; furniture-derived 1.10 metric normalization is excluded.',
            'Main external envelope only; no interior layout or physical/as-built identity is asserted.'],
        target_role='plan_envelope')
    for i, opening in enumerate(floor['openings']):
        emit('wicker-floor-'+opening['id'], 'wickerman-shop',
            'door' if opening['id'].startswith('door') else 'opening', raster(floor),
            _geometry('LineString', opening['endpoints_pixels']),
            [ref(path, _pointer('openings', i, 'endpoints_pixels'))], state='proposed',
            assumptions=[opening['drawing_role'], 'Endpoint sampling only; full 3D aperture and physical width remain unresolved.'],
            target_role='plan_opening_span')

    path = 'evidence/wicker-shop-vertical-annotations.json'
    vertical = read(path)
    for name, trace in vertical['vertical_traces'].items():
        kind = 'roof' if name.endswith('apex') else 'door' if name.endswith('door') else 'opening' if name.endswith('opening') else 'wall'
        emit('wicker-vertical-'+name, 'wickerman-shop', kind, raster(vertical),
            _geometry('LineString', [trace['top_pixel'], trace['bottom_pixel']]),
            [ref(path, _pointer('vertical_traces', name))], state='proposed',
            assumptions=[vertical['method'], 'This is a source height trace, not a facade silhouette or material mask.',
                'Drawn local floor reference and physical component correspondence remain conditional.'],
            target_role='elevation_height_trace')

    # The corrected seed retains the original source polygons. Later proposal
    # geometry and whole-wing closure hypotheses are not imported as truth.
    path = 'evidence/mutiny-north-wing-source-label-corrected-seed.json'
    wing = read(path)
    for doc in wing['documents'].values():
        document(doc['sha256'])
    for i, opening in enumerate(wing['openings']):
        emit('mutiny-opening-'+opening['id'], 'mutiny-north-range', opening['kind'],
            raster(wing['documents']['elevation'], wing['documents']['elevation']['page']),
            _geometry('Polygon', opening['points_pixels']),
            [ref(path, _pointer('openings', i, 'points_pixels')), ref(path, '/source_label_correction')],
            state='existing', assumptions=[wing['trace_review'],
                'Reviewed aperture outline in the existing elevation; no glazing, passage depth or park placement is established.'],
            target_role='elevation_aperture')
    for name, role, key, kind in [('facade-baseline', 'plan', 'facade_endpoints', 'wall'),
                                  ('elevation-baseline', 'elevation', 'baseline_endpoints', 'wall'),
                                  ('roof-cross-section', 'roof', 'cross_section_points', 'roof')]:
        group = 'elevation_trace' if role == 'elevation' else role+'_trace'
        emit('mutiny-'+name, 'mutiny-north-range', kind, raster(wing['documents'][role]),
            _geometry('LineString', wing[group][key]), [ref(path, _pointer(group, key))],
            state='existing', assumptions=[wing['trace_review'],
                'Original line samples only; plan/elevation and cross-date roof assembly are not verified.',
                'No inferred connecting lines, wall caps or facade triangles are generated.'], target_role='source_trace')
    for pointer in ('/plan_trace/rear_point', '/elevation_trace/eave_point', '/elevation_trace/ridge_point'):
        excluded.append({'id': 'mutiny-unpaired-point:'+pointer, 'reason': 'Single point needs a separate keypoint task; no artificial LineString is created.',
            'review_refs': [ref(path, pointer)]})

    # Source-extracted Prospect members are raster-derived profiles. Invert the
    # exact nominal local affine; do not pretend they are untouched vector paths.
    ground_path = 'voxel_mapper/data/prospect-ground-profiles.json'
    upper_path = 'voxel_mapper/data/prospect-upper-profiles.json'
    ground, upper = read(ground_path), read(upper_path)
    gf_recipe, upper_recipe = 'scripts/extract_prospect_profiles.py', 'scripts/extract_prospect_storeys.py'
    read(gf_recipe); read(upper_recipe)
    def member_profile(profile, path, pointer, sha, centre, scale, recipe, state):
        geometry = copy.deepcopy(profile['geometry'])
        def invert(coords):
            if len(coords) == 2 and all(type(v) in (int, float) for v in coords):
                return [coords[0]/scale+centre[0], centre[1]-coords[1]/scale]
            return [invert(value) for value in coords]
        geometry['coordinates'] = invert(geometry['coordinates'])
        emit('prospect-'+profile['id'].replace(' ', '-').replace('/', '-'), 'prospect-tower', 'structural_member',
            source(sha), geometry, [ref(path, pointer+'/geometry'), ref(recipe)],
            level='source_extracted_profile', state=state, assumptions=[
                'Reviewed member fill extracted at two raster samples per source page point, then simplified at 0.005 nominal metres.',
                'Page-point target reverses the retained printed-scale local affine; it is not an untouched original vector boundary.',
                'No vertical extent, surveyed dimensions, current-condition identity or geographic placement is labelled.'],
            target_role='plan_member_footprint', target_derivation={
                'operation': 'inverse_nominal_profile_affine', 'metres_per_page_point': scale,
                'paper_center': centre, 'source_path_index': profile['path_index'],
                'paper_bbox': profile['paper_bbox']})
    scale = ground['scale_denominator']*.0254/72
    document(ground['source_sha256'], ground['source_url'])
    for i, profile in enumerate(ground['components']):
        member_profile(profile, ground_path, _pointer('components', i), ground['source_sha256'],
            [1011.12, 696.0], scale, gf_recipe, 'existing')
    for j, storey in enumerate(upper['storeys']):
        document(storey['source_sha256'], storey['source_url'])
        for i, profile in enumerate(storey['components']):
            member_profile(profile, upper_path, _pointer('storeys', j, 'components', i), storey['source_sha256'],
                storey['paper_center'], upper['scale_denominator']*.0254/72, upper_recipe, 'existing')

    # Reviewed local rock/wall/planter outlines are useful independent examples;
    # neither provisional alignment nor estimated display heights are labels.
    path = 'voxel_mapper/data/alton-path-details.json'
    details = read(path)
    for i, feature in enumerate(details['features']):
        sha = feature['document_id']
        document(sha, feature['source_url'])
        states = source_states.get(sha, set())
        state = next(iter(states)) if len(states) == 1 else 'unknown'
        entity = ('planning-building-'+sha[:12]+'-'+str(feature['face_index']) if feature['kind'] == 'building'
                  else 'alton-site-details-'+feature['application'].replace('/', '-'))
        emit('detail-'+sha[:12]+'-'+str(feature['page'])+'-'+str(feature['face_index']), entity, feature['kind'],
            source(sha, feature['page']), feature['native_geometry'],
            [ref(path, _pointer('features', i, 'native_geometry')), ref(path, _pointer('features', i, 'label'))],
            state=state, assumptions=[feature['review_method'],
                'MuPDF unrotated page points with Y downward; exact retained reviewed polygon, including source-curve flattening where used.',
                'Semantic footprint only; estimated height, materials and alignment are not 3D supervision.',
                'Site detail grouping is not an additional reconstructed building.'],
            entity_type='building' if feature['kind'] == 'building' else 'site_detail',
            target_role='labelled_plan_footprint')
    for i, entry in enumerate(details['withheld_examples']):
        excluded.append({'id': 'detail-withheld-'+str(i), 'reason': entry['reason'],
            'review_refs': [ref(path, _pointer('withheld_examples', i))]})

    # Additional explicitly reviewed source-local surfaces. Geographic output
    # polygons, widths, stairs, heights and inferred paving extents are excluded.
    frame_doc = 'docs/park-paving.md'
    frame_kernel = 'voxel_mapper/wicker_registration.py'
    read(frame_doc); read(frame_kernel)
    paving_path = 'voxel_mapper/data/alton-paving-extensions.geojson'
    paving = read(paving_path)
    if len(paving['features']) != 4:
        raise ValueError('Exact retained CBeebies path review inventory required')
    for i, feature in enumerate(paving['features']):
        props = feature['properties']
        if (props.get('kind') != 'path' or props.get('page') != 1
                or props.get('geometry_method') != 'Reviewed corridor boundary digitisation in native PDF coordinates; no ride layout generated'
                or props.get('state') != 'historical_proposed'):
            raise ValueError('Explicit historical proposed native corridor review required')
        document(props['document_id'], props['source_url'])
        emit('reviewed-cbeebies-path-'+str(i), 'alton-site-details-SMD-2013-1047', 'path',
            source(props['document_id'], props['page']), _geometry('Polygon', props['native_pdf_polygon']),
            [ref(paving_path, _pointer('features', i, 'properties', 'native_pdf_polygon')),
                ref(paving_path, _pointer('features', i, 'properties', 'geometry_method')),
                ref(frame_doc), ref(frame_kernel)], state='proposed', assumptions=[
                props['geometry_method'], 'Original state is historical_proposed; present or as-built condition is not verified.',
                'Coordinates are MuPDF unrotated page points, Y downward, before the retained alignment Y flip.',
                'Reviewed digitised corridor outline only; geographic alignment, paving height and material estimates are excluded.'],
            entity_type='site_detail', target_role='reviewed_path_footprint')

    gardens_path = 'voxel_mapper/data/alton-gardens-v16.json'
    surfaces_path = 'voxel_mapper/data/alton-garden-surfaces-v19.json'
    gardens, surfaces = read(gardens_path), read(surfaces_path)
    garden_builder, garden_extractor = 'scripts/build_garden_bridges.py', 'scripts/extract_reviewed_gardens.py'
    read(garden_builder); read(garden_extractor)
    sheets = {entry['title']: (i, entry) for i, entry in enumerate(gardens['sources'])}
    for i, surface in enumerate(surfaces['surfaces']):
        source_index, sheet = sheets[surface['sheet']]
        if not surface['geometry_status'].startswith('visually reviewed'):
            raise ValueError('Explicitly reviewed native garden surface required')
        document(sheet['document_id'], sheet['source_url'])
        emit('reviewed-garden-surface-'+str(i), 'alton-site-details-SMD-2013-1105', 'paving_surface',
            source(sheet['document_id']), _geometry('Polygon', surface['polygon']),
            [ref(surfaces_path, _pointer('surfaces', i, 'polygon')),
                ref(surfaces_path, _pointer('surfaces', i, 'geometry_status')),
                ref(gardens_path, _pointer('sources', source_index)), ref(garden_builder), ref(frame_kernel)],
            state='unknown', assumptions=[surface['geometry_status'],
                'Source is a retained 2013 garden sheet with mixed/unknown proposal state; no existing/as-built state is asserted.',
                'MuPDF unrotated page points, Y downward; source page 1 confirmed for the pinned single-page original.',
                'Paving surface includes a reviewed road edge; this umbrella label does not assert pedestrian path or plaza.',
                'Materials, heights, bridge proxies, geographic alignment and current physical condition are not targets.'],
            entity_type='site_detail', target_role='reviewed_paving_footprint')

    path_indices = [i for i, feature in enumerate(gardens['features'])
        if feature.get('kind') == 'path' and feature.get('geometry_status') == 'reviewed_native_boundary_centre_trace_with_estimated_width']
    if path_indices != [27, 28, 29, 30, 31, 262, 263, 264, 265, 266, 267]:
        raise ValueError('Exact retained reviewed garden centreline inventory required')
    sources_by_sha = {entry['document_id']: (i, entry) for i, entry in enumerate(gardens['sources'])}
    for i in path_indices:
        feature = gardens['features'][i]
        source_index, sheet = sources_by_sha[feature['document_id']]
        if feature['native_geometry'].get('type') != 'LineString':
            raise ValueError('Original reviewed path centreline required; no inferred width polygon')
        document(sheet['document_id'], sheet['source_url'])
        emit('reviewed-garden-path-'+str(i), 'alton-site-details-SMD-2013-1105', 'path',
            source(sheet['document_id']), feature['native_geometry'],
            [ref(gardens_path, _pointer('features', i, 'native_geometry')),
                ref(gardens_path, _pointer('features', i, 'geometry_status')),
                ref(gardens_path, _pointer('sources', source_index)), ref(garden_extractor), ref(frame_kernel)],
            state='unknown', assumptions=[
                'Retained manual source path centre between visible grey boundaries; MuPDF unrotated page points, Y downward.',
                'The original extraction explicitly uses page 1; the pinned source is a single-page PDF.',
                'Only the reviewed LineString is a target; estimated width, forced stairs, heights and material proxies are excluded.',
                'Related upper/lower garden sheets stay in one site context; they do not count as independent acquisition groups.',
                'Mixed retained/proposed 2013 scope; current and as-built conditions are not verified.'],
            entity_type='site_detail', target_role='reviewed_path_centreline')

    plaza_path = 'evidence/wicker-reviewed-plaza-source.geojson'
    plaza_record_path = 'docs/evidence/planning-surfaces/source-record.json'
    plaza_source_code = 'voxel_mapper/pilot_surfaces.py'
    plaza_source, plaza_record = read(plaza_path), read(plaza_record_path)
    read(plaza_source_code)
    if plaza_source['coordinate_frame'] != 'unrotated PDF points, x right/y down':
        raise ValueError('Explicit retained native plaza source coordinate frame required')
    document(plaza_record['document_sha256'], plaza_record['source_url'])
    for i in (4, 17, 22):
        feature = plaza_source['features'][i]
        props = feature['properties']
        if (props.get('surface_role') != 'labelled_plaza' or props.get('contained_labels') != ['Plaza']
                or props.get('source_document_sha256') != plaza_record['document_sha256']
                or props.get('source_page') != 1 or props.get('state') not in ('existing', 'new')
                or feature['geometry'].get('type') != 'Polygon'):
            raise ValueError('Exact source-labelled native plaza footprint required')
        refs = [ref(plaza_path, _pointer('features', i, 'geometry')),
            ref(plaza_path, _pointer('features', i, 'properties', 'contained_labels')),
            ref(plaza_path, _pointer('features', i, 'properties', 'surface_role')),
            ref(plaza_path, '/coordinate_frame'), ref(plaza_record_path), ref(plaza_source_code)]
        for key in ('vector_sequence', 'legend_sequence', 'pdf_operation_index',
                    'legend_operation_index', 'pattern_sha256', 'curve_flattening_tolerance_pdf_points'):
            if key in props:
                refs.append(ref(plaza_path, _pointer('features', i, 'properties', key)))
        emit('reviewed-wicker-plaza-'+str(i), 'alton-site-details-SMD-2016-0315', 'plaza',
            source(props['source_document_sha256'], props['source_page']), feature['geometry'], refs,
            level='source_extracted_profile', state='proposed' if props['state'] == 'new' else 'existing',
            assumptions=[
                'Native paving footprint and contained Plaza label extracted from the pinned source; original-page overlay checked in this development session.',
                'MuPDF unrotated page points, X right and Y downward; retained source extraction preserves holes and curves with stated flattening where used.',
                'Legend state is '+props['state']+' within the proposed 2017 site-plan document; proposed state is not as-built verification.',
                'Only source geometry and plaza role are targets; display brick material, printed-scale area, finished heights and map placement are excluded.',
                'The Wicker site context joins retained scenery examples rather than creating another independent building.'],
            entity_type='site_detail', target_role='source_labelled_plaza_footprint')

    contexts = [
        ('evidence/wicker-shop-projection-model.json', 'Conditional assembled roof/wall/canopy geometry and unresolved physical correspondence; context only.'),
        ('evidence/wicker-shop-wall-model.json', 'Conditional 3D wall assembly; source-local trace targets do not certify complete model geometry.'),
        ('evidence/wicker-shop-joined-study-validation.json', 'Estimated wall-to-roof join cells are display hypotheses, not source labels.'),
        ('evidence/wicker-shop-wall-detail-study-validation.json', 'Illustrative fence/trapdoor materials and decorative spacing are not measured targets.'),
        ('evidence/wicker-station-model.json', 'Rounded eave/ridge heights, four-decimetre inset and illustrative apertures remain hypotheses.'),
        ('evidence/wicker-preshow_low-model.json', 'Rounded heights and illustrative apertures are not exact source-to-geometry supervision.'),
        ('evidence/wicker-preshow_tower-model.json', 'Rounded heights and illustrative apertures are not exact source-to-geometry supervision.'),
        ('evidence/mutiny-north-wing-shell-study-seed.json', 'Rear/end closures, wall/floor/roof thicknesses and full-shell assembly are display hypotheses.'),
        ('evidence/mutiny-north-wing-partition-study-seed.json', 'Partition footprint review does not verify its assumed display height.'),
        ('voxel_mapper/reconstruction/prospect.py', 'Study proxy arches, stair treads, balcony envelopes, roof radii and palettes are excluded.'),
    ]
    for path, reason in contexts:
        excluded.append({'id': 'context:'+path, 'reason': reason, 'review_refs': [ref(path)]})
    if len(documents) > 64 or len(excluded) > 64:
        raise ValueError('Retained study catalogue inventory budget exceeded')
    return {'version': VERSION, 'records': records, 'excluded': excluded,
        'input_sha256': dict(sorted(inputs.items())),
        'documents': [documents[k] for k in sorted(documents)]}
