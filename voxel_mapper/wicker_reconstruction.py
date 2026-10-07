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


def preview_profile(route, bindings, stations):
    controls = sorted((b['nearest_candidate']['station_m'], b['printed_level_m'])
                      for b in bindings if b['status'] == 'provisional_annotation_binding')
    if len(controls) < 3 or any(not math.isfinite(s+h) for s,h in controls):
        raise ValueError('At least three finite provisional height controls required')
    if any(b[0]-a[0] < .1 for a,b in zip(controls,controls[1:])):
        raise ValueError('Conflicting coincident height controls')
    return np.interp(stations,[p[0] for p in controls],[p[1] for p in controls],period=route['route_length_m'])


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
    heights = preview_profile(route,association['bindings'],stations)
    sources = {s['id']:s for s in config['sources']}
    terrain = Terrain(config['terrain'],local,sources)
    rows = {}
    counts = {}
    def add(x,y,z,material,component,void=False):
        key = (math.floor(x),math.floor(y),math.floor(z))
        # Physical reconstruction always wins over its own excavation cells.
        if key in rows and rows[key]['material'] != 'air':
            return
        rows[key] = {'x':key[0],'y':key[1],'z':key[2],'material':material,'kind':'structure',
                     'feature':'reconstruction/'+component,'source':'wicker-estimated-reconstruction',
                     'material_origin':'estimated_reconstruction_void' if void else 'estimated_reconstruction_shell'}
        if len(rows) > max_voxels:
            raise ValueError('Reconstruction voxel budget exceeded')
    below_ground = 0
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
        paving = json.loads((output/'wicker-man-surface-candidates.geojson').read_text())
        for feature in paving['features']:
            polygon = transform(project.transform,shape(feature['geometry']))
            x0,z0,x1,z1 = polygon.bounds
            for x in range(math.floor(x0),math.ceil(x1)):
                for z in range(math.floor(z0),math.ceil(z1)):
                    if not polygon.covers(Point(x+.5,z+.5)): continue
                    ground = terrain.sample(x+.5,z+.5)
                    if ground is not None:
                        add(x,ground,z,'stone','paving_preview')
    finally:
        terrain.close()
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
              'assumptions':['Printed plan levels treated as ODN for preview only',
                             'Ambiguous height associations excluded; remaining controls linearly interpolated around the closed route',
                             'Track width, tie geometry, 4 m bent spacing and clearance are estimates',
                             'Paving uses provisional alignment and a generic stone material',
                             'Timber bents are a simplified preview, not the actual structural design',
                             'Sound tunnels, effigy, fences and detailed buildings are not reconstructed'],
              'visit_local_xyz_m':[round(line.coords[0][0]),round(float(heights[0])+3),round(line.coords[0][1])]}
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
    (output/'wicker-man-reconstruction.json').write_text(json.dumps(report,indent=2))
    return report
