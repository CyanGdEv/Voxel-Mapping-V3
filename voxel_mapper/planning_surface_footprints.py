"""Fine native boundaries around visible path, plaza and material labels.

The search rectangle selects whole paint primitives. It cannot close a path,
remove a known competing enclosure, establish scale or accept physical geometry.
"""
from concurrent.futures import CancelledError
from collections import Counter
import json
import heapq
import math
import re

import pymupdf
from shapely.geometry import Polygon, shape, box
from shapely.strtree import STRtree

from . import glyph_visibility, ordinary_surfaces, planning_outline_semantics, planning_view_geometry
from .building_spec import digest
from .drawing_page_tools import native_inverse
from .paving_palette import material_label, polygon_surface

VERSION = 'planning-surface-boundaries-v3'
FRAME = 'pdf_native_points_y_up'
SEARCH_MARGIN_POINTS = 144
LIMITS = {'max_surface_labels': 256, 'max_native_candidates': 10000,
          'max_native_points': 200000, 'max_outlines': 500,
          'max_association_checks': 64000, 'max_output_bytes': 8000000,
          'max_regions':32, 'max_scan_work_paths':3200000,
          'max_region_merge_checks':65536}
ROLES = {'path', 'plaza', 'surface'}


def _coalesce_windows(windows,maximum_checks,check):
    """Cover every original scope with bounded non-increasing-area rectangles.

    Search bounds can merge; source primitives and recovered faces never do.
    The schedule depends only on source bounds, not recovery success or quotas.
    """
    active={i:(tuple(w),(i,)) for i,w in enumerate(windows)};heap=[];checks=0
    def area(w):return (w[2]-w[0])*(w[3]-w[1])
    def offer(i,j):
        nonlocal checks
        check();checks+=1
        if checks>maximum_checks:raise ValueError('surface_region_merge_work_budget_exceeded')
        a,am=active[i];b,bm=active[j]
        ix=max(0,min(a[2],b[2])-max(a[0],b[0]));iy=max(0,min(a[3],b[3])-max(a[1],b[1]))
        if ix*iy<=0:return
        bounds=(min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))
        combined=area(bounds)
        if combined>area(a)+area(b):return
        added=combined-area(a)-area(b)+ix*iy
        heapq.heappush(heap,(added,combined,bounds,am,bm,i,j))
    for i,w in enumerate(windows):
        if len(w)!=4 or not all(math.isfinite(v) for v in w) or w[0]>=w[2] or w[1]>=w[3]:
            raise ValueError('Finite original source window required')
        for j in range(i+1,len(windows)):offer(i,j)
    next_id=len(windows);merges=0
    while heap:
        check();_,_,bounds,_,_,i,j=heapq.heappop(heap)
        if i not in active or j not in active:continue
        members=tuple(sorted(active.pop(i)[1]+active.pop(j)[1]))
        identity=next_id;next_id+=1;active[identity]=(bounds,members);merges+=1
        for other in sorted(active):
            if other!=identity:offer(other,identity)
    rows=[{'region_native_points':list(w),'source_window_indices':list(m)}
          for w,m in sorted(active.values())]
    return rows,{'pair_checks':checks,'merges':merges,
        'original_window_count':len(windows),'coalesced_region_count':len(rows),
        'original_summed_area_pdf_points_squared':sum(area(w) for w in windows),
        'coalesced_summed_area_pdf_points_squared':sum(area(r['region_native_points']) for r in rows)}


def _regional_faces(page,sha,number,visible,limits,check):
    frame=planning_view_geometry._native_frame(page).bounds
    windows=sorted({(max(frame[0],b[0]-SEARCH_MARGIN_POINTS),
        max(frame[1],b[1]-SEARCH_MARGIN_POINTS),min(frame[2],b[2]+SEARCH_MARGIN_POINTS),
        min(frame[3],b[3]+SEARCH_MARGIN_POINTS))
        for b in (shape(r['geometry_pdf_native']).bounds for r in visible)})
    extraction={'status':'unplaced_geometry_candidates','strategy':'per_label_native_windows',
        'region_schedule':'bounded_coalesced_source_windows',
        'source_windows':[list(w) for w in windows],
        'regions':[],'candidates':0,'retained_points':0,'raw_paths':0,'scan_work_paths':0,
        'rejections':{},'world_geometry_additions':0}
    recovery={'status':'enclosed_faces_only','counts':{},'recovered_faces':0}
    faces={};geometry_ids={};covered=0;rejections=Counter();counts=Counter()
    def fail(reason):
        extraction.update(status='regional_surface_scan_withheld',reason=reason)
        return [],extraction,recovery,covered
    try:regions,coalescing=_coalesce_windows(windows,limits['max_region_merge_checks'],check)
    except ValueError as error:return fail(str(error))
    extraction['coalescing']=coalescing
    if len(regions)>limits['max_regions']:return fail('surface_region_budget_exceeded')
    check();cache=ordinary_surfaces._source_page_cache(page)
    extraction['raw_paths']=len(cache['compact'])
    if len(regions)*len(cache['compact'])>limits['max_scan_work_paths']:
        return fail('surface_scan_work_budget_exceeded')
    options={'region_native_windows':[r['region_native_points'] for r in regions],
        'min_line_length_points':.25,'max_candidates':limits['max_native_candidates'],
        'max_total_points':limits['max_native_points'],'max_paths':100000,
        'max_scan_paths':100000,'regional_fallback':False,'source_face_primitives_only':True}
    check();parents,shared=ordinary_surfaces.extract_page(page,sha,number,_paths=cache['compact'],**options)
    check();extraction.update(shared_native_extraction=shared,shared_extraction_options=options,
        candidates=shared.get('candidates',0),retained_points=shared.get('retained_points',0),
        scan_work_paths=len(regions)*len(cache['compact']),source_path_passes=1,
        region_schedule='coalesced_shared_native_union')
    rejections.update(shared.get('rejections',{}));extraction['rejections']=dict(rejections)
    if shared.get('status')!='unplaced_geometry_candidates':
        return fail('shared_native_'+str(shared.get('status')))
    buckets=[[] for _ in regions]
    for parent in parents:
        check();references={}
        for paint in parent['paint_references']:
            for index in paint.get('source_region_indices',[]):
                extraction['scan_work_paths']+=1
                if extraction['scan_work_paths']>limits['max_scan_work_paths']:
                    return fail('surface_scan_work_budget_exceeded')
                references.setdefault(index,[]).append(paint)
        for index,paints in sorted(references.items()):
            if index in parent.get('source_face_ineligible_regions',[]):continue
            if not box(*regions[index]['region_native_points']).covers(shape(parent['geometry'])):
                return fail('shared_native_geometry_crosses_source_region')
            buckets[index].append({**parent,'paint_references':paints})
    extraction['shared_parent_inventory_sha256']=digest(parents)
    for index,region in enumerate(regions):
        window=region['region_native_points']
        check()
        scoped=buckets[index]
        part={'status':'unplaced_geometry_candidates','raw_paths':len(cache['compact']),
            'candidates':len(scoped),'region_native_points':window,
            'shared_parent_inventory_sha256':extraction['shared_parent_inventory_sha256'],
            'candidate_and_point_work_charged_at_shared_extraction':True}
        rows,part,found,occluded=ordinary_surfaces.closed_source_faces(page,sha,number,
            recovery_options={'max_face_provenance':2048},_cache=cache,_parents=(scoped,part))
        check();covered+=occluded
        counts.update(found.get('counts',{}))
        extraction['rejections']=dict(rejections);recovery['counts']=dict(counts)
        inventory=ordinary_surfaces._outline_inventory(rows,part,found,limits['max_outlines'])
        receipt={'index':index,**region,'extraction_options':extraction['shared_extraction_options'],
            'extraction':part,'recovery':found,'inventory_complete':inventory['inventory_complete'],
            'source_inventory_sha256':digest(inventory),
            'source_records':[{'candidate_id':r['candidate_id'],'source_record_sha256':r['source_record_sha256']}
                              for r in inventory['records']]}
        extraction['regions'].append(receipt)
        if not inventory['inventory_complete']:
            return fail('regional_'+str(inventory['reason']))
        for row in inventory['records']:
            geometry=shape(row['candidate']['geometry']).normalize().wkb_hex
            # Identical whole boundaries need one canonical original witness.
            # Distinct source boundaries stay separate, even when nested.
            if geometry in geometry_ids:continue
            if row['candidate_id'] in faces:
                return fail('conflicting_regional_source_identity')
            geometry_ids[geometry]=row['candidate_id'];faces[row['candidate_id']]=row['candidate']
            if len(faces)>limits['max_outlines']:return fail('combined_surface_outline_budget_exceeded')
        if len(json.dumps([extraction,list(faces.values())],allow_nan=False).encode())>limits['max_output_bytes']:
            return fail('surface_output_budget_exceeded')
    recovery['recovered_faces']=len(faces)
    return list(faces.values()),extraction,recovery,covered


def page_candidates(page, sha, number, inventory, associations, *, options=None,
                    cancelled=lambda: False):
    """Return source-bound surface hypotheses; no physical identity is accepted."""
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-set(LIMITS):
        raise ValueError('Known surface boundary limits required')
    limits = {**LIMITS, **options}
    if any(type(v) is not int or not 1 <= v <= LIMITS[k] for k, v in limits.items()):
        raise ValueError('Lower-only surface boundary limits required')
    if limits['max_output_bytes'] < 16384:
        raise ValueError('Surface boundary metadata needs 16384 bytes')
    if (not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            or type(number) is not int or number < 1 or page.number+1 != number
            or not isinstance(inventory, dict)
            or inventory.get('version') != ordinary_surfaces.OUTLINE_VERSION
            or inventory.get('status') != 'complete_source_outline_inventory'
            or inventory.get('inventory_complete') is not True
            or not isinstance(associations, dict)
            or associations.get('version') != planning_outline_semantics.VERSION
            or associations.get('document_sha256') != sha or associations.get('page') != number
            or associations.get('source_inventory_sha256') != digest(inventory)
            or associations.get('inventory_complete') is not True):
        raise ValueError('Complete same-source surface outline associations required')
    records = inventory.get('records')
    if not isinstance(records, list) or len(records) > 500:
        raise ValueError('Bounded source outline records required')
    coarse_geometries = []
    identifiers = set()
    coarse_points = 0
    for record in records:
        candidate = record.get('candidate', {})
        identifier = record.get('candidate_id')
        if (not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier)
                or identifier in identifiers or candidate.get('id') != identifier
                or record.get('source_record_sha256') != digest(candidate)
                or any(r.get('document_sha256') != sha or r.get('page') != number
                       or r.get('coordinate_frame') != FRAME for r in (record, candidate))):
            raise ValueError('Unchanged same-source unique outline records required')
        geometry = shape(candidate.get('geometry'))
        if (geometry.geom_type != 'Polygon' or geometry.is_empty or not geometry.is_valid
                or not all(math.isfinite(v) for v in geometry.bounds)):
            raise ValueError('Finite complete source polygons required')
        coarse_points += len(geometry.exterior.coords)+sum(len(r.coords) for r in geometry.interiors)
        if coarse_points > 200000:
            raise ValueError('Bounded complete source outline point inventory required')
        identifiers.add(identifier); coarse_geometries.append(geometry)
    def check():
        if cancelled():
            raise CancelledError('Surface boundary recovery cancelled')
    checks = 0
    def charge():
        nonlocal checks
        check(); checks += 1
        if checks > limits['max_association_checks']:
            raise OverflowError('surface_association_work_budget_exceeded')
    check()
    source_labels = associations.get('labels')
    if not isinstance(source_labels, list) or len(source_labels) > 128:
        raise ValueError('Bounded source role labels required')
    labels = []
    result = {'version': VERSION, 'document_sha256': sha, 'page': number,
        'coordinate_frame': FRAME, 'limits': limits,
        'source_inventory_sha256': digest(inventory),
        'source_associations_sha256': digest(associations),
        'status': 'no_visible_surface_labels', 'analysis_complete': True,
        'candidates': [], 'boundary_decisions': [], 'labels': labels,
        'physical_identity_verified': False, 'view_scope_verified': False,
        'registration_verified': False, 'scale_verified': False,
        'world_placement_eligible': False, 'world_geometry_additions': 0,
        'training_labels_generated': 0, 'model_weights_updated': False,
        'geometric_accuracy': None,
        'limitations': ['A visible contained label supports a source boundary hypothesis only.',
            'Material labels do not establish physical horizontal surface identity or drawing scope.',
            'Original holes are preserved; labels inside a hole do not bind to its surrounding face.',
            'No endpoint snapping, gap repair, nearest/smallest selection, clipping or guessed width.',
            'Scale, physical boundary role, finished levels, current state and park alignment remain unresolved.']}
    def finish(reason=None):
        if reason:
            result.update(status='surface_boundaries_withheld', analysis_complete=False,
                          reason=reason, candidates=[])
        visible = [r for r in labels if r['glyph_screen']['status'] == 'raster_consistent_candidate']
        resolved = {r['id'] for c in result['candidates'] for r in c['labels']}
        result.update(surface_labels=len(labels), visible_surface_labels=len(visible),
                      association_checks=checks)
        result['summary'] = {'surface_boundary_candidates': len(result['candidates']),
            'surface_labels': len(labels), 'visible_surface_labels': len(visible),
            'unresolved_surface_labels': len(labels)-len(resolved)}
        if len(json.dumps(result, allow_nan=False).encode()) > limits['max_output_bytes']:
            for key in ('fine_associations', 'fine_inventory_records', 'extraction', 'recovery'):
                result.pop(key, None)
            result.update(status='surface_boundaries_withheld', analysis_complete=False,
                reason='surface_output_budget_exceeded', candidates=[], boundary_decisions=[], labels=[])
            result['summary'].update(surface_boundary_candidates=0,
                                     unresolved_surface_labels=len(labels))
        check(); return result
    # Reuse the already screened literal role evidence; material labels retain
    # separate native trace/character identities and their original glyph proof.
    seen = set()
    for row in source_labels:
        if row.get('claim', {}).get('role') in ROLES:
            label = {**row, 'material': None, 'label_source': 'literal_surface_role'}
            labels.append(label)
            seen.add((tuple(row['trace_indices']), tuple(row['character_indices'])))
    if len(labels) > limits['max_surface_labels']:
        return finish('surface_label_budget_exceeded')
    raw = page.get_texttrace()
    if len(raw) > 10000 or sum(len(r['chars']) for r in raw) > 500000:
        return finish('surface_text_budget_exceeded')
    inverse = native_inverse(page)
    for run in ordinary_surfaces.label_runs(raw):
        check()
        text = ''.join(chr(c[0]) for c in run['chars']).strip()
        material = material_label(text)
        key = (tuple(run['trace_indices']), tuple(run['character_indices']))
        if material is None or key in seen:
            continue
        if len(labels) >= limits['max_surface_labels']:
            return finish('surface_label_budget_exceeded')
        rect = pymupdf.Rect(run['bbox'])
        geometry = Polygon([tuple(p*inverse) for p in (rect.tl, rect.tr, rect.br, rect.bl)])
        screen = glyph_visibility.screen_architectural_span(page, run, zoom=24 if run['size'] < 4 else 6)
        labels.append({'id': digest([VERSION, sha, number, run['trace_indices'], run['character_indices']]),
            'text': text, 'claim': {'role': 'surface', 'scope': 'enclosure', 'printed_state': 'unspecified'},
            'material': material, 'label_source': 'literal_surface_material',
            'trace_indices': run['trace_indices'], 'character_indices': run['character_indices'],
            'geometry_pdf_native': {'type': 'Polygon', 'coordinates': [list(geometry.exterior.coords)]},
            'glyph_screen': screen})
        seen.add(key)
    visible = [r for r in labels if r['glyph_screen']['status'] == 'raster_consistent_candidate']
    if not visible:
        return finish()
    coarse_index = STRtree(coarse_geometries)
    try:
        for label in visible:
            polygon = shape(label['geometry_pdf_native'])
            if (polygon.geom_type != 'Polygon' or not polygon.is_valid or polygon.is_empty
                    or not all(math.isfinite(v) for v in polygon.bounds)):
                raise ValueError('Finite native surface label geometry required')
            matches = []
            for position in coarse_index.query(polygon, predicate='intersects'):
                charge()
                if coarse_geometries[int(position)].contains(polygon):
                    matches.append(records[int(position)]['candidate_id'])
            label['coarse_candidate_ids'] = sorted(matches)
    except OverflowError as error:
        return finish(str(error))
    bounds = [shape(r['geometry_pdf_native']).bounds for r in visible]
    frame = planning_view_geometry._native_frame(page).bounds
    region = [max(frame[0], min(b[0] for b in bounds)-SEARCH_MARGIN_POINTS),
              max(frame[1], min(b[1] for b in bounds)-SEARCH_MARGIN_POINTS),
              min(frame[2], max(b[2] for b in bounds)+SEARCH_MARGIN_POINTS),
              min(frame[3], max(b[3] for b in bounds)+SEARCH_MARGIN_POINTS)]
    extraction_options = {'region_native_points': region, 'min_line_length_points': .25,
        'max_candidates': limits['max_native_candidates'], 'max_total_points': limits['max_native_points'],
        'max_paths': 100000, 'max_scan_paths': 100000, 'regional_fallback': False}
    result.update(search_region_pdf_native=region, search_margin_pdf_points=SEARCH_MARGIN_POINTS,
                  extraction_options=extraction_options)
    check()
    try:
        faces, extraction, recovery, covered = _regional_faces(page,sha,number,visible,limits,check)
    except (ValueError, RuntimeError, OverflowError) as error:
        result['error'] = str(error)[:512]
        return finish('fine_source_geometry_failed')
    check()
    # A complete coarse enclosure may legitimately extend beyond every focused
    # window. Retain its unchanged source boundary only when no fine enclosure
    # contains this label and the complete coarse inventory has exactly one.
    # Never use this to select among competing fine or coarse enclosures.
    if extraction['status']=='unplaced_geometry_candidates':
        fine_index=STRtree([shape(r['geometry']) for r in faces])
        existing={r['id'] for r in faces};fallback=[]
        for label in visible:
            check();polygon=shape(label['geometry_pdf_native'])
            matches=fine_index.query(polygon,predicate='within')
            coarse=label['coarse_candidate_ids']
            if len(matches)==0 and len(coarse)==1:
                record=next(r for r in records if r['candidate_id']==coarse[0])
                if record['candidate_id'] not in existing:
                    faces.append(record['candidate']);existing.add(record['candidate_id'])
                    fallback.append({'candidate_id':record['candidate_id'],
                        'source_record_sha256':record['source_record_sha256'],
                        'reason':'complete_coarse_boundary_exceeds_regional_scope'})
        extraction['complete_coarse_fallbacks']=fallback
        added=[shape(r['geometry']) for r in faces if r['id'] in {f['candidate_id'] for f in fallback}]
        extraction['candidates']+=len(added)
        extraction['retained_points']+=sum(len(g.exterior.coords)+sum(len(r.coords) for r in g.interiors) for g in added)
        if (extraction['candidates']>limits['max_native_candidates']
                or extraction['retained_points']>limits['max_native_points']):
            extraction.update(status='regional_surface_scan_withheld',reason='combined_surface_native_budget_exceeded')
            faces=[]
    fine_inventory = ordinary_surfaces._outline_inventory(faces, extraction, recovery, limits['max_outlines'])
    result.update(extraction=extraction, recovery=recovery, covered_boundaries_withheld=covered,
        fine_inventory_sha256=digest(fine_inventory),
        fine_inventory_records=[{'candidate_id': r['candidate_id'], 'source_record_sha256': r['source_record_sha256']}
                                for r in fine_inventory['records']])
    if extraction['status']!='unplaced_geometry_candidates':
        return finish(extraction.get('reason','complete_regional_surface_scan_required'))
    if not fine_inventory['inventory_complete']:
        return finish(fine_inventory['reason'])
    fine = planning_outline_semantics.page_candidates(page, sha, number, fine_inventory, cancelled=cancelled)
    result['fine_associations'] = fine
    if not fine['inventory_complete']:
        return finish('fine_label_associations_incomplete')
    fine_records = fine_inventory['records']; geometries = [shape(r['candidate']['geometry']) for r in fine_records]
    index = STRtree(geometries); bound = {}; competing = set()
    try:
        for label in visible:
            polygon = shape(label['geometry_pdf_native']); matches = []
            for position in index.query(polygon, predicate='intersects'):
                charge()
                if geometries[int(position)].contains(polygon):
                    matches.append(fine_records[int(position)]['candidate_id'])
            label['candidate_ids'] = sorted(matches)
            if len(label['coarse_candidate_ids'])>1:
                result['boundary_decisions'].append({'candidate_id':None,'label_ids':[label['id']],
                    'status':'withheld','reason':'coarse_competing_enclosures_require_interpretation'})
            label['status'] = ('ambiguous_source_enclosures_withheld' if len(matches) > 1 else
                              'unique_visible_source_enclosure' if len(matches) == 1 else 'no_supported_source_enclosure')
            if len(matches) == 1:
                bound.setdefault(matches[0], []).append(label)
            elif len(matches) > 1:
                competing.update(matches)
    except OverflowError as error:
        return finish(str(error))
    semantic_outlines = {r['candidate_id']: r for r in fine['outlines']}
    for record in fine_records:
        check(); identifier = record['candidate_id']; support = bound.get(identifier, [])
        if not support:
            continue
        semantic = semantic_outlines.get(identifier)
        role = semantic.get('source_role_hint') if semantic else 'surface'
        reason = ('competing_label_context_withheld' if identifier in competing else
                  'coarse_competing_enclosures_require_interpretation' if any(len(r['coarse_candidate_ids']) > 1 for r in support) else
                  semantic['status'] if semantic and semantic['status'] != 'visible_label_enclosure_hint' else
                  'conflicting_source_roles_withheld' if role not in ROLES else None)
        materials = [r['text'] for r in support if r['material'] is not None]
        surface = polygon_surface(materials)
        if reason is None and surface is None:
            reason = 'conflicting_surface_materials_withheld'
        decision = {'candidate_id': identifier, 'label_ids': [r['id'] for r in support],
                    'status': 'withheld', 'reason': reason}
        result['boundary_decisions'].append(decision)
        if reason:
            continue
        candidate = {'id': digest([VERSION, sha, number, identifier, sorted(r['id'] for r in support)]),
            'status': 'source_surface_boundary_hypothesis', 'document_sha256': sha, 'page': number,
            'coordinate_frame': FRAME, 'geometry_pdf_native': record['candidate']['geometry'],
            'source_outline': record, 'labels': support, 'source_role_hint': role,
            'surface': surface, 'material_basis': 'bound source labels' if materials else 'user stone default on labelled surface',
            'physical_identity_verified': False, 'world_placement_eligible': False, 'geometric_accuracy': None}
        result['candidates'].append(candidate)
        decision.update(status='source_surface_boundary_hypothesis', reason=None)
    result['status'] = 'source_surface_boundary_candidates'
    return finish()
