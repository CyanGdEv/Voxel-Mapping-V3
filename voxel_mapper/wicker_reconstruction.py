"""Opt-in visible reconstruction preview; no verified planning claims."""
import json
import math
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import Point, LineString, shape
from shapely.ops import transform

from .terrain import Terrain
from .wicker_track import ordered_route
from .wicker_station import station_context, phase_controls, lift_profile, serializable_context


def preview_profile(route, bindings, stations):
    controls = sorted((b['nearest_candidate']['station_m'], b['printed_level_m'])
                      for b in bindings if b['status'] in
                      ('provisional_annotation_binding', 'reviewed_plan_marker_binding', 'estimated_phase_control'))
    length = route['route_length_m']
    if not math.isfinite(length) or length <= 0:
        raise ValueError('Finite positive closed route length required')
    if len(controls) < 3 or any(not math.isfinite(s+h) for s,h in controls):
        raise ValueError('At least three finite provisional height controls required')
    if any(b[0]-a[0] < .1 for a,b in zip(controls,controls[1:])):
        raise ValueError('Conflicting coincident height controls')
    if controls[0][0] < 0 or controls[-1][0] >= length or length-controls[-1][0]+controls[0][0] < .1:
        raise ValueError('Height controls must be distinct around the closed route')
    query = np.asarray(stations,dtype=float)
    if not np.all(np.isfinite(query)):
        raise ValueError('Finite profile stations required')
    x = np.array([s for s,h in controls]); y = np.array([h for s,h in controls])
    x = np.r_[x[-1]-length,x,x[0]+length]; y = np.r_[y[-1],y,y[0]]
    query = query % length
    index = np.clip(np.searchsorted(x,query,side='right')-1,0,len(x)-2)
    t = (query-x[index])/(x[index+1]-x[index])
    # Labelled HP/LP controls are extrema. Zero-slope cubic spans preserve
    # their exact levels and cannot overshoot between sparse controls.
    return y[index]+(y[index+1]-y[index])*(t*t*(3-2*t))


def local_height_bindings(association, route):
    """Transfer segment fractions, not BNG metre stations, into local CRS."""
    result = []
    for binding in association['bindings']:
        candidate = binding.get('nearest_candidate')
        if candidate is None:
            continue
        index = candidate['segment_index']
        segment = route['segments'][index]
        # The association retains the fraction in its reference projection.
        fraction = candidate.get('segment_fraction')
        if fraction is None:
            raise ValueError('Height binding requires a reference segment fraction')
        if not 0 <= fraction <= 1:
            raise ValueError('Height binding fraction must lie on its segment')
        station = segment['station_start_m']+fraction*(segment['station_end_m']-segment['station_start_m'])
        result.append({**binding,'nearest_candidate':{**candidate,'station_m':station}})
    return result


def emit_preview(config, quality, raw_osm, output, max_voxels=200000):
    output = Path(output)
    association = json.loads((output/'wicker-man-track-association.json').read_text())
    if association.get('status') != 'route_association_candidates':
        raise ValueError('Mapped route and provisional height associations required')
    local = CRS.from_wkt(quality['crs'])
    project = Transformer.from_crs(4326,local,always_xy=True)
    ways = [e for e in raw_osm['elements'] if e.get('tags',{}).get('name') == 'Wicker Man'
            and e['tags'].get('roller_coaster') == 'track']
    route = ordered_route(ways,project.transform)
    line = LineString([route['segments'][0]['start']]+[s['end'] for s in route['segments']])
    stations = np.arange(0,line.length,.5)
    bindings = local_height_bindings(association,route)
    evidence = json.loads((output/'wicker-man-planning-evidence.json').read_text())
    context = station_context(raw_osm,route,project.transform,evidence,bindings)
    bindings += phase_controls(context)
    heights = preview_profile(route,bindings,stations)
    lift_mask = (stations >= context['lift_start_m']) & (stations <= context['lift_crest_station_m'])
    heights[lift_mask] = lift_profile(stations[lift_mask],context['lift_start_m'],context['lift_crest_station_m'],
                                      context['lift_foot_level_m'],context['lift_crest_level_m'])
    sources = {s['id']:s for s in config['sources']}
    terrain = Terrain(config['terrain'],local,sources)
    surface = Terrain(config['surface'],local,sources)
    rows = {}
    counts = {}
    def add(x,y,z,material,component,void=False):
        key = (math.floor(x),math.floor(y),math.floor(z))
        # Physical reconstruction always wins over its own excavation cells.
        if key in rows and rows[key]['material'] != 'air':
            if not (component.startswith('proposed_') and rows[key]['feature'] == 'reconstruction/paving_preview'):
                return
        rows[key] = {'x':key[0],'y':key[1],'z':key[2],'material':material,'kind':'structure',
                     'feature':'reconstruction/'+component,'source':'wicker-estimated-reconstruction',
                     'material_origin':'estimated_reconstruction_void' if void else 'estimated_reconstruction_shell'}
        if len(rows) > max_voxels:
            raise ValueError('Reconstruction voxel budget exceeded')
    below_ground = 0
    rail_below_ground = 0
    minimum_clearance = math.inf
    plaza_target = None
    try:
        for station,height in zip(stations,heights):
            point = line.interpolate(float(station))
            a = line.interpolate(max(0,float(station)-.3)); b = line.interpolate(min(line.length,float(station)+.3))
            dx,dz = b.x-a.x,b.y-a.y; length = math.hypot(dx,dz)
            if length == 0: continue
            nx,nz = -dz/length,dx/length
            ground = terrain.sample(point.x,point.y)
            if ground is None: raise ValueError('Ground observation missing under preview track')
            below_ground += height < ground+1
            rail_below_ground += height < ground
            minimum_clearance = min(minimum_clearance,float(height-ground))
            # Rails sit on timber ties; their width and profile interpolation are estimates.
            for side in (-1.2,1.2):
                add(point.x+side*nx,height,point.y+side*nz,'iron_block','track_rails')
            for side in np.arange(-1.5,1.51,.5):
                add(point.x+side*nx,height-1,point.y+side*nz,'dark_oak_planks','track_ties')
                for y in range(math.floor(height)+1,math.floor(height)+4):
                    add(point.x+side*nx,y,point.y+side*nz,'air','track_clearance',True)
            if abs(station/4-round(station/4)) < .01:
                for side in (-1.5,1.5):
                    sx,sz = point.x+side*nx,point.y+side*nz
                    base = terrain.sample(sx,sz)
                    if base is None: continue
                    for y in range(math.floor(base)+1,math.floor(height)-1):
                        add(sx,y,sz,'dark_oak_planks','timber_bents')
                # Crossbeam immediately below each tie deck.
                for side in np.arange(-1.5,1.51,.5):
                    add(point.x+side*nx,height-2,point.y+side*nz,'dark_oak_planks','timber_bents')
            if context['lift_start_m'] <= station <= context['lift_crest_station_m']:
                # An explicit chain line identifies the lift instead of a generic hill.
                add(point.x,height,point.y,'black_concrete','lift_chain')
                add(point.x+2*nx,height-1,point.y+2*nz,'dark_oak_planks','lift_walkway')
        corridor = line.buffer(2)
        for part in context['parts']:
            polygon = part['polygon']; x0,z0,x1,z1 = polygon.bounds
            cells = [(x,z) for x in range(math.floor(x0),math.ceil(x1))
                     for z in range(math.floor(z0),math.ceil(z1)) if polygon.covers(Point(x+.5,z+.5))]
            roof_samples = [value for x,z in cells if (value := surface.sample(x+.5,z+.5)) is not None]
            if len(roof_samples) < len(cells)/2:
                raise ValueError('Insufficient observed surface coverage over station complex')
            floor = math.floor(part['floor_level_m'])
            roof = max(floor+4,math.floor(float(np.median(roof_samples))))
            clear_top = max(roof,math.ceil(max(roof_samples)))+1
            if clear_top-floor > 32:
                raise ValueError('Station surface outlier exceeds bounded shell height')
            part.update(roof_level_m=roof,roof_method='Flat median DSM surface estimate; minimum 4 m above floor',
                        surface_sample_count=len(roof_samples))
            for x,z in cells:
                point = Point(x+.5,z+.5); on_track = corridor.covers(point)
                for y in range(floor+1,clear_top+1):
                    add(x,y,z,'air','station_complex_clearance',True)
                if not on_track:
                    add(x,floor,z,'dark_oak_planks',part['role']+'_platform')
                    if polygon.boundary.distance(point) < 1:
                        for y in range(floor+1,roof):
                            add(x,y,z,'dark_oak_planks',part['role']+'_walls')
                add(x,roof,z,'dark_oak_planks',part['role']+'_roof')
        paving = json.loads((output/'wicker-man-surface-candidates.geojson').read_text())
        for feature in paving['features']:
            polygon = transform(project.transform,shape(feature['geometry']))
            proposed = feature['properties'].get('state') == 'new'
            component = 'proposed_plaza_paving' if proposed and 'Plaza' in feature['properties'].get('contained_labels',[]) else ('proposed_paving' if proposed else 'paving_preview')
            if component == 'proposed_plaza_paving':
                plaza_target = polygon.representative_point()
            x0,z0,x1,z1 = polygon.bounds
            for x in range(math.floor(x0),math.ceil(x1)):
                for z in range(math.floor(z0),math.ceil(z1)):
                    if not polygon.covers(Point(x+.5,z+.5)): continue
                    ground = terrain.sample(x+.5,z+.5)
                    if ground is not None:
                        add(x,ground,z,'stone_bricks' if proposed else 'stone',component)
    finally:
        terrain.close()
        surface.close()
    for row in rows.values():
        counts[row['feature']] = counts.get(row['feature'],0)+1
    with (output/'voxels.jsonl').open('a') as stream:
        for row in rows.values(): stream.write(json.dumps(row)+'\n')
    quality['sources'].append({'id':'wicker-estimated-reconstruction','url':'https://github.com/CyanGdEv/Voxel-Mapping-V3',
                               'license':'Derived preview; underlying OSM, EA and drawing source terms retained',
                               'attribution':'Estimated Wicker Man geometry; not verified as-built'})
    report = {'status':'emitted_estimated_preview','verified':False,'route_length_m':line.length,
              'emitted_voxel_records':len(rows),'component_records':counts,
              'below_ground_profile_samples':int(below_ground),
              'rail_below_observed_ground_samples':int(rail_below_ground),
              'minimum_rail_ground_clearance_m':minimum_clearance,
              'profile_method':'Periodic cubic course/station-exit spans; explicit level station and two-incline lift with short slope blends',
              'station_lift':serializable_context(context),
              'proposed_paving_footprints':sum(f['properties'].get('state') == 'new' for f in paving['features']),
              'profile_controls':[{'point_label':b['point_label'],'station_local_m':b['nearest_candidate']['station_m'],
                                   'level_m':b['printed_level_m'],'anchor_kind':b.get('anchor_kind'),
                                   'status':b['status']} for b in bindings if b['status'] in
                                  ('provisional_annotation_binding','reviewed_plan_marker_binding','estimated_phase_control')],
              'assumptions':['Printed plan levels treated as ODN for preview only',
                             'Drawing crosshairs replace text centres; four crossing branches were reviewed against drawing 373/95/7 B and remain provisional',
                             'Cubic height spans preserve printed extrema; intermediate track shape remains estimated',
                             'Track width, tie geometry, 4 m bent spacing and clearance are estimates',
                             'Existing and proposed paving use provisional alignment and generic stone palettes; proposed paving pattern is matched to the printed legend',
                             'Timber bents are a simplified preview, not the actual structural design',
                             'Station, maintenance and pre-lift buildings now have estimated hollow shells; detailed interiors/roof forms remain unknown',
                             'Sound tunnels, effigy and fences are not reconstructed'],
              'visit_local_xyz_m':[round(line.coords[0][0]),round(float(heights[0])+3),round(line.coords[0][1])]}
    # Stand on the station platform, away from the track opening.
    station_polygon = context['station']['polygon']
    x0,z0,x1,z1 = station_polygon.bounds
    platform = [(x,z) for x in range(math.floor(x0),math.ceil(x1))
                for z in range(math.floor(z0),math.ceil(z1))
                if station_polygon.buffer(-1).covers(Point(x+.5,z+.5))
                and line.distance(Point(x+.5,z+.5)) > 2]
    if not platform:
        raise ValueError('No safe station platform spawn available')
    sx,sz = min(platform,key=lambda p:Point(p[0]+.5,p[1]+.5).distance(station_polygon.centroid))
    report['visit_local_xyz_m'] = [sx,math.floor(context['station']['floor_level_m'])+2,sz]
    report['station_platform_local_xyz_m'] = report['visit_local_xyz_m'][:]
    plaza_blocks = [row for row in rows.values() if row['feature'] == 'reconstruction/proposed_plaza_paving']
    if plaza_target is not None and plaza_blocks:
        visit = min(plaza_blocks,key=lambda row:Point(row['x']+.5,row['z']+.5).distance(plaza_target))
        report['plaza_local_visit_xyz_m'] = [visit['x'],visit['y']+2,visit['z']]
        report['visit_local_xyz_m'] = report['plaza_local_visit_xyz_m'][:]
    (output/'wicker-man-reconstruction.json').write_text(json.dumps(report,indent=2))
    quality['estimated_reconstruction'] = report
    quality['voxel_records'] += len(rows)
    quality['spawn_local_xyz_m'] = report['visit_local_xyz_m']
    return report


def verify_preview(output, world, report):
    """Count preview blocks in the reopened world, separately from as-built accuracy."""
    import amulet
    from .bedrock import material_block
    output = Path(output)
    groups = {}
    with (output/'voxels.jsonl').open() as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('source') == 'wicker-estimated-reconstruction':
                groups.setdefault((row['x']//16,(-row['z'])//16),[]).append(row)
    if not groups:
        raise ValueError('No emitted reconstruction records to verify')
    counts = {}
    level = amulet.load_level(str(output/'bedrock-world'))
    try:
        for (cx,cz),rows in groups.items():
            chunk = level.get_chunk(cx,cz,'minecraft:overworld')
            for row in rows:
                y = row['y']+world['vertical_offset_blocks']
                actual = chunk.block_palette[int(chunk.blocks[row['x']%16,y,(-row['z'])%16])]
                expected = material_block(row['material'])
                if actual.namespaced_name != expected.namespaced_name or any(actual.properties.get(k) != v for k,v in expected.properties.items()):
                    raise ValueError('Reconstruction block missing after export: '+str((row['x'],y,-row['z'])))
                if row['material'] != 'air':
                    counts[row['feature']] = counts.get(row['feature'],0)+1
            level.unload()
    finally:
        level.close()
    report.update(world_emission_check='passed',world_component_blocks=counts)
    report['plaza_connection_check'] = verify_plaza_connection(output,world,report)
    (output/'wicker-man-reconstruction.json').write_text(json.dumps(report,indent=2))
    return report


def connected_paving(cells, start):
    """Four-neighbour paving reachable without a jump larger than one block."""
    from collections import deque
    if start not in cells:
        return set()
    seen = {start}
    pending = deque([start])
    while pending:
        x,z = pending.popleft()
        for target in ((x+1,z),(x-1,z),(x,z+1),(x,z-1)):
            if target in cells and target not in seen and abs(cells[target]-cells[(x,z)]) <= 1:
                seen.add(target)
                pending.append(target)
    return seen


def verify_plaza_connection(output, world, report):
    """Check exposed paving and a continuous entrance-to-existing-path route."""
    import amulet
    from .bedrock import material_block
    columns = {}
    plaza = set()
    existing = set()
    with (Path(output)/'voxels.jsonl').open() as stream:
        for line in stream:
            row = json.loads(line)
            feature = row.get('feature','')
            if not feature.startswith('reconstruction/') or 'paving' not in feature:
                continue
            key = (row['x'],row['z'])
            if key not in columns or row['y'] > columns[key]['y']:
                columns[key] = row
            if feature == 'reconstruction/proposed_plaza_paving':
                plaza.add(key)
            if feature == 'reconstruction/paving_preview':
                existing.add(key)
    if not plaza:
        return {'status':'unavailable_no_recovered_plaza'}
    groups = {}
    for key,row in columns.items():
        groups.setdefault((key[0]//16,(-key[1])//16),[]).append((key,row))
    exposed = {}
    level = amulet.load_level(str(Path(output)/'bedrock-world'))
    try:
        for (cx,cz),entries in groups.items():
            chunk = level.get_chunk(cx,cz,'minecraft:overworld')
            for key,row in entries:
                x,z = key[0]%16,(-key[1])%16
                y = row['y']+world['vertical_offset_blocks']
                blocks = [chunk.block_palette[int(chunk.blocks[x,y+d,z])] for d in (0,1,2)]
                if (blocks[0].namespaced_name == material_block(row['material']).namespaced_name
                        and all(b.base_name == 'air' for b in blocks[1:])):
                    exposed[key] = row['y']
            level.unload()
    finally:
        level.close()
    spawn = report['plaza_local_visit_xyz_m']
    start = (spawn[0],spawn[2])
    reached = connected_paving(exposed,start)
    # Require a substantial route outside the plaza, not an adjacent stray tile.
    main_path = {key for key in reached & existing if math.hypot(key[0]-start[0],key[1]-start[1]) >= 20}
    if not main_path or not plaza <= set(exposed):
        raise ValueError('Entrance plaza must be exposed and continuously connected to existing main paving')
    return {'status':'passed','exposed_plaza_blocks':len(plaza),
            'reachable_paving_blocks':len(reached),'reachable_existing_path_blocks':len(main_path),
            'method':'Reopened world paving with two air blocks overhead; four-neighbour route, maximum one-block step'}
