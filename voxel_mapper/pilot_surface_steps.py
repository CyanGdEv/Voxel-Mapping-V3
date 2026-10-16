"""Add bounded estimated joins on planning paving while preserving the prior scene."""
import json

from shapely.geometry import box, mapping
from shapely.ops import unary_union

from .bedrock import material_block
from .pilot_access import (SURFACE_STEP_POLICY, SURFACE_STEP_FEATURE, PATH_STEP_FEATURE,
    _read_inputs, _scene, _mapped_node, _mapped_nodes, _review_surface_nodes, _surface_row,
    _openings, _walkthrough, collision)
from .pilot_navigation import _tree, _walking_nodes, inspect
from .pilot_path_steps import _select_joins, _check_gaps, MAX_CANDIDATES, MAX_SLABS
from .pilot_surface_levels import extract as extract_levels

ARTIFACTS = ['planning-paving-joins-review.json','planning-paving-levels-review.json']


def validate_settings(settings):
    if (not isinstance(settings,dict) or set(settings) != {'policy','max_slabs'}
            or settings.get('policy') != SURFACE_STEP_POLICY or type(settings.get('max_slabs')) is not int
            or not 1 <= settings['max_slabs'] <= MAX_SLABS):
        raise ValueError('Explicit bounded estimated planning paving joins policy required')


def _summary(navigation):
    keys = ('mapped_supported_cells','mapped_reachable_cells_any_walking',
            'mapped_reachable_cells_on_walking_surfaces','planning_review_supported_cells',
            'planning_review_reachable_cells_any_walking','planning_review_reachable_cells_on_walking_surfaces',
            'adjacent_walking_surface_barriers')
    return {**{key:navigation[key] for key in keys},'walking_surface_components':len(navigation['walking_components'])}


def append(output, quality, access, settings, surfaces, source, max_voxels=1_000_000):
    validate_settings(settings)
    if access.get('audit_scope') != 'whole_pilot':
        raise ValueError('Planning paving joins require the whole_pilot native audit')
    records, terrain, paths, bounds = _read_inputs(output,access['component'],whole_area=True)
    if any(row.get('feature') == SURFACE_STEP_FEATURE for row in records.values()):
        raise ValueError('Planning paving joins must be applied once to a fresh scene')
    scene = _scene(records,bounds)
    mapped, review = _mapped_nodes(scene,paths,records), _review_surface_nodes(scene,records)
    walking = _walking_nodes(scene,mapped,records)
    sx, sy, sz = quality['spawn_local_xyz_m']; spawn = sx,sz,2*sy
    protected = {(sx,sz)} | {(x,z) for route in access['routes'] for x,z,_ in route}
    # Keep existing entrance witnesses and every column used by a prior slab's
    # adjacent-height/edge checks fixed. The first generation's joins still verify.
    witnesses = []
    component = access['component']
    if component.get('access_openings'):
        openings, _ = _openings(scene,component,access['footprint'])
        source_openings = {row['id']:row for row in component['access_openings']}
        for opening in openings:
            crossing = {tuple(p) for p in opening['crossing_nodes_x_z_half_y']}
            columns = {tuple(p) for p in source_openings[opening['id']]['columns_local_xz']}
            witness = _walkthrough(scene,spawn,crossing,columns,access['footprint'],2*round(component['floor_elevation_m']),0)
            if witness['status'] == 'native_route_ready':
                witnesses.append(witness['route_local_x_z_half_y'])
                protected.update((x,z) for x,z,_ in witnesses[-1])
    for (x,_,z), row in records.items():
        if row.get('feature') == PATH_STEP_FEATURE:
            protected.update(((x,z),(x-1,z),(x+1,z),(x,z-1),(x,z+1)))
    guard = access['footprint'].buffer(1)
    candidates = {}
    for node in sorted(review):
        x,z,height = node; key = x,height//2-1,z; row = records.get(key,{})
        if (node in mapped or height%2 or not _surface_row(row) or (x,z) in protected
                or guard.intersects(box(x,z,x+1,z+1)) or (x,height//2,z) in records
                or terrain.get((x,z)) != key[1]
                or collision(material_block(row['material'])) != (0,2,2)
                or not scene.clear(x,z,height,height+6)):
            continue
        adjacent = [(nx,nz,nh) for nx,nz in ((x-1,z),(x+1,z),(x,z-1),(x,z+1))
                    for nh in scene.nodes(nx,nz)]
        raised = x,z,height+1
        if any(other[2] < height for other in adjacent):
            continue
        if any(not scene.transition(raised,other) for other in scene.neighbours(node)):
            continue
        upper = sorted(other for nx,nz in ((x-1,z),(x+1,z),(x,z-1),(x,z+1))
                       if (other := (nx,nz,height+2)) in walking)
        if upper:
            candidates[node] = upper
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError('Planning paving join candidate budget exceeded')
    selected = _select_joins(scene,walking,spawn,candidates,settings['max_slabs'])
    adjustments = {node:(node[0],node[1],node[2]+1) for node in selected}
    edges = [(node,other) for node in selected for other in scene.neighbours(node)]
    gaps = [(node,(nx,nz,nh)) for node in selected
            for nx,nz in ((node[0]-1,node[1]),(node[0]+1,node[1]),(node[0],node[1]-1),(node[0],node[1]+1))
            for nh in scene.nodes(nx,nz) if nh != node[2]]
    additions, joins = [], []
    for node, upper in sorted(selected.items()):
        x,z,height = node; original = records[x,height//2-1,z]
        row = {'x':x,'y':height//2,'z':z,'kind':'steps','feature':SURFACE_STEP_FEATURE,
            'source':'provisional-plan-paving','material':'stone_slab',
            'material_origin':'estimated_reconstruction_shell','display_policy':SURFACE_STEP_POLICY,
            'source_document_sha256':original['source_document_sha256'],'source_page':original['source_page'],
            'planning_source_cell':{key:original[key] for key in ('feature','x','y','z')},
            'accepted_physical_geometry':False,'finished_level_verified':False}
        additions.append(row)
        joins.append({'block_local_xyz':[row['x'],row['y'],row['z']],
            'planning_source_cell':row['planning_source_cell'],'before_local_x_z_half_y':list(node),
            'after_local_x_z_half_y':list(adjustments[node]),
            'upper_endpoints_local_x_z_half_y':[list(p) for p in upper]})
    if quality['voxel_records']+len(additions) > max_voxels:
        raise ValueError('Planning paving joins exceed pilot voxel budget')
    updated_records = {**records,**{(r['x'],r['y'],r['z']):r for r in additions}}
    updated = _scene(updated_records,bounds)
    if _mapped_nodes(updated,paths,updated_records) != mapped:
        raise ValueError('Planning paving joins would change an original mapped support')
    expected_review = {adjustments.get(node,node) for node in review}
    if set(_review_surface_nodes(updated,updated_records)) != expected_review:
        raise ValueError('Planning paving joins would lose source-linked paving support')
    for a,b in edges:
        na,nb = adjustments.get(a,a),adjustments.get(b,b)
        if not (updated.standing(na) and updated.standing(nb) and updated.transition(na,nb)):
            raise ValueError('Planning paving joins would break an existing walking edge')
    _check_gaps(updated,adjustments,gaps)
    for witness in witnesses:
        if not all(updated.standing(tuple(p)) for p in witness):
            raise ValueError('Planning paving joins would change an existing entrance witness')
    before_reached,_ = _tree(scene,spawn)
    after_reached,_ = _tree(updated,spawn)
    preserved = {adjustments.get(node,node) for node in set(mapped)|set(review) if node in before_reached}
    if not preserved <= after_reached.keys():
        raise ValueError('Planning paving joins would lose reachable source surfaces')
    before = inspect(scene,spawn,mapped,paths,records,0,[])
    after = inspect(updated,spawn,mapped,paths,updated_records,0,[])
    footprints = json.loads((output/'planning-surfaces-source.geojson').read_text())['features']
    levels = extract_levels(source['pdf'],source['source']['document_sha256'],surfaces['report']['placement'],
        source['operation'],quality['crs'],terrain,footprints,component['floor_elevation_m'])
    report = {'version':SURFACE_STEP_POLICY,'status':'awaiting_native_readback','estimated':True,
        'candidate_columns':len(candidates),'max_slabs':settings['max_slabs'],'added_slab_records':len(additions),
        'before':_summary(before),'planned_after':_summary(after),'joins':joins,
        'stop_reason':'slab_limit' if len(selected)==settings['max_slabs'] else 'no_further_compatible_component_join',
        'selection':'Grow spawn walking component, then merge count and component size; stable coordinate order.',
        'protected_prior_witnesses':len(witnesses),'protected_columns':len(protected),
        'preserved_existing_incident_edges':len(edges),'preserved_nonzero_adjacent_height_gaps':len(gaps),
        'preexisting_nonzero_adjacent_height_gaps_enlarged':0,'terrain_excavation_cells':0,
        'source_records_rewritten':0,'original_native_blocks_replaced':0,'absolute_finished_levels_applied':0,
        'accepted_physical_geometry':False,'training_labels_generated':0,'minecraft_playtest':'not_performed',
        'limitations':['Stone bottom slabs are half-step display estimates, not source-supported site grading or measured steps.',
                       'Only surviving grounded planning paving receives joins; mapped supports, prior joins, approaches and building remain fixed.',
                       'Missing surfaces, consecutive steep rises and bridge/tunnel geometry remain unresolved.',
                       'Conservative centred-player walking graph; no in-game physics or accessibility assessment.']}
    with (output/'voxels.jsonl').open('a',encoding='utf-8') as stream:
        for row in additions:
            stream.write(json.dumps(row)+'\n')
    if additions:
        collection = json.loads((output/'features-local.geojson').read_text())
        geometry = unary_union([box(r['x'],r['z'],r['x']+1,r['z']+1) for r in additions])
        collection['features'].append({'type':'Feature','id':SURFACE_STEP_FEATURE,'geometry':mapping(geometry),
            'properties':{'review_only':True,'accepted_physical_geometry':False,
                          'source':'Estimated joins on recovered planning paving; not surveyed grading.'}})
        _write(output/'features-local.geojson',collection)
    quality['voxel_records'] += len(additions)
    from .cli import file_sha256
    quality['sha256'] = file_sha256(output/'voxels.jsonl')
    quality['planning_paving_joins_review'] = report
    quality['planning_paving_levels_review'] = levels
    _write(output/ARTIFACTS[0],report); _write(output/ARTIFACTS[1],levels)
    return {'report':report,'additions':additions,'adjustments':adjustments,'preserved_edges':edges,
            'preserved_gaps':gaps,'expected_review':expected_review,'expected_mapped':set(mapped),
            'preserved_reachable':preserved,'preserved_witnesses':witnesses,
            'paving_report':surfaces['report'],'component':component,'footprint':access['footprint']}


def verify(output, scene, mapped, records, offset, navigation, prepared):
    for row in prepared['additions']:
        key = row['x'],row['y'],row['z']
        if records.get(key) != row:
            raise ValueError('Saved planning paving join lost its source row')
        reference = row['planning_source_cell']; base = reference['x'],reference['y'],reference['z']
        source = records.get(base,{})
        if not _surface_row(source) or _mapped_node(scene,base,source,records) != (row['x'],row['z'],2*row['y']+1):
            raise ValueError('Saved planning paving join lost its source-linked bearing or headroom')
    review = _review_surface_nodes(scene,records)
    if prepared['expected_review'] != review.keys() or prepared['expected_mapped'] != mapped.keys():
        raise ValueError('Saved planning paving joins changed supported source cells')
    for a,b in prepared['preserved_edges']:
        na,nb = prepared['adjustments'].get(a,a),prepared['adjustments'].get(b,b)
        if not (scene.standing(na) and scene.standing(nb) and scene.transition(na,nb)):
            raise ValueError('Saved planning paving join broke a walking edge')
    _check_gaps(scene,prepared['adjustments'],prepared['preserved_gaps'])
    for witness in prepared['preserved_witnesses']:
        if not (all(scene.standing(tuple(p)) for p in witness)
                and all(scene.transition(tuple(a),tuple(b)) for a,b in zip(witness,witness[1:]))):
            raise ValueError('Saved planning paving joins lost a prior entrance witness')
    reached,_ = _tree(scene,tuple(navigation['spawn_local_x_z_half_y']))
    if not prepared['preserved_reachable'] <= reached.keys():
        raise ValueError('Saved planning paving joins lost reachable source cells')
    for join in prepared['report']['joins']:
        a = tuple(join['after_local_x_z_half_y'])
        if not all(scene.transition(a,tuple(b)) for b in join['upper_endpoints_local_x_z_half_y']):
            raise ValueError('Saved planning paving join lost an upper connection')
        x,y,z = join['block_local_xyz']; join['block_native_xyz'] = [x,y+offset,-z]
    connections = []
    component = prepared['component']
    if component.get('access_openings'):
        walking = _walking_nodes(scene,mapped,records)
        openings,_ = _openings(scene,component,prepared['footprint'])
        source_openings = {o['id']:o for o in component['access_openings']}
        plazas = [f for f in prepared['paving_report'].get('features',[]) if f['surface_role']=='labelled_plaza']
        if len(plazas)*len(openings) > 32:
            raise ValueError('Planning plaza entrance witness budget exceeded')
        for plaza in plazas:
            points = plaza['walkthrough']['route_local_x_z_half_y']
            for opening in openings:
                columns = {tuple(p) for p in source_openings[opening['id']]['columns_local_xz']}
                crossing = {tuple(p) for p in opening['crossing_nodes_x_z_half_y']}
                route = _walkthrough(scene,tuple(points[-1]) if points else (0,0,0),crossing if points else set(),columns,
                    prepared['footprint'],2*round(component['floor_elevation_m']),offset,exterior_walking_nodes=walking)
                if len(route['route_native_xyz']) > 512:
                    route.update(status='unresolved',reason='route_point_budget',doorway_index=None,
                                 horizontal_length_m=None,route_local_x_z_half_y=[],route_native_xyz=[])
                connections.append({'plaza_feature_id':plaza['feature_id'],'opening_id':opening['id'],
                    'surface_scope':'walking surfaces, then this entrance and declared interior floor',**route})
    prepared['report'].update(status='native_joins_verified' if prepared['additions'] else 'no_qualifying_joins',
        verified_joins=len(prepared['additions']),native_after=_summary(navigation),
        plaza_entrance_connections=connections,
        ready_plaza_entrance_connections=sum(r['status']=='native_route_ready' for r in connections),
        unresolved_plaza_entrance_connections=sum(r['status']!='native_route_ready' for r in connections),
        native_readback={'status':'completed','original_mapped_supports_unchanged':True,
                         'all_existing_incident_edges_preserved':True,'no_nonzero_adjacent_height_gap_enlarged':True,
                         'prior_entrance_witnesses_preserved':True,'minecraft_playtest':'not_performed'})
    _write(output/ARTIFACTS[0],prepared['report'])


def _write(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
