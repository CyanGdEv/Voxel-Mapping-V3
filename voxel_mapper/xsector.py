"""First X-Sector pass: mapped topology audit and explicitly estimated station shells.

OSM layers and surface observations never supply track heights. An optional
Oblivion preview combines mapped phase boundaries with official relative
dimensions and explicit estimated levels. Apply overlays to a copied park,
preserving other cells and checking them after a Bedrock round trip.
"""
import argparse
import hashlib
import json
import math
import shutil
import zipfile
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, Polygon, mapping

from .terrain import Terrain
from .wicker_track import ordered_route

RIDES = {'The Smiler': 'The Smiler Station', 'Oblivion': 'Oblivion Station'}


def audit_route(ways, project):
    route = ordered_route(ways, project)
    tags = {w['id']: w.get('tags', {}) for w in ways}
    crossings = []
    segments = route['segments']
    for i, a in enumerate(segments):
        first = LineString([a['start'], a['end']])
        for j in range(i+2, len(segments)):
            if i == 0 and j == len(segments)-1:
                continue
            second = LineString([segments[j]['start'], segments[j]['end']])
            hit = first.intersection(second)
            if hit.is_empty:
                continue
            crossings.append({'segment_indices': [i, j], 'geometry': mapping(hit),
                              'status': 'vertical_separation_unresolved'})
    route['plan_length_m'] = route.pop('route_length_m')
    route['crossings'] = crossings
    route['way_tags'] = {str(k): {key: value for key, value in t.items()
                                  if key in ('layer', 'tunnel', 'bridge', 'covered')}
                         for k, t in tags.items()}
    route['direction'] = 'Topological order only; train direction not established'
    route['track_generation'] = 'withheld_pending_3d_controls'
    return route


def station_shell(polygon, ground, surface, feature_id, max_records=100000):
    """Level, hollow footprint shell, not surveyed architecture or loading level.

    Median ground is an estimate for the level slab. The 90th percentile DSM
    elevation is only a roof guide, with a minimum four metre shell clearance.
    Emit air through the previous generic DSM solid extrusion; no openings or
    extra platform levels are invented from proximity to a path.
    """
    if not polygon.is_valid or polygon.is_empty or not 10 <= polygon.area <= 3000:
        raise ValueError('Bounded valid station footprint required')
    cells = []
    x0, z0, x1, z1 = polygon.bounds
    for x in range(math.floor(x0), math.ceil(x1)):
        for z in range(math.floor(z0), math.ceil(z1)):
            if not polygon.covers(Point(x+.5, z+.5)):
                continue
            g, s = ground(x+.5, z+.5), surface(x+.5, z+.5)
            if g is None or s is None or not math.isfinite(g+s):
                raise ValueError('Complete finite station terrain/surface coverage required')
            cells.append((x, z, g, s))
    if not cells:
        raise ValueError('Station footprint has no metre cells')
    floor = math.floor(float(np.median([c[2] for c in cells])))
    roof = max(floor+4, math.ceil(float(np.percentile([c[3] for c in cells], 90))))
    if roof-floor > 25 or max(c[2] for c in cells)-min(c[2] for c in cells) > 15:
        raise ValueError('Station level uncertainty exceeds first-pass shell limits')
    footprint = {(x,z) for x,z,g,s in cells}
    rows = []
    for x,z,g,s in cells:
        edge = any((x+dx,z+dz) not in footprint for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))
        for y in range(min(floor, math.floor(g)), max(roof, math.ceil(s))+1):
            solid = y <= floor or y == roof or (edge and y <= roof)
            rows.append({'x':x, 'y':y, 'z':z, 'kind':'structure',
                         'material':'black_concrete' if solid else 'air',
                         'feature':feature_id, 'source':'xsector-first-pass',
                         'material_origin':'estimated_reconstruction_shell' if solid else 'estimated_reconstruction_void'})
            if len(rows) > max_records:
                raise ValueError('Station overlay exceeds record budget')
    return rows, {'feature':feature_id, 'footprint_area_m2':polygon.area,
                  'floor_odn_m':floor, 'roof_odn_m':roof, 'records':len(rows),
                  'status':'estimated_hollow_shell', 'openings':'not reconstructed',
                  'limitations':['Ground median is not a surveyed loading-platform level',
                                 'Composite DSM may include track or foliage; flat roof and materials are provisional',
                                 'Facade, entrance/exit, interior and platform levels remain unresolved']}


def build_overlay(config, quality, raw, include_oblivion=False):
    project = Transformer.from_crs(4326, CRS.from_wkt(quality['crs']), always_xy=True)
    sources = {s['id']:s for s in config['sources']}
    ground = Terrain(config['terrain'], CRS.from_wkt(quality['crs']), sources)
    surface = Terrain(config['surface'], CRS.from_wkt(quality['crs']), sources)
    report = {'status':'first_pass_station_context', 'rides':{}, 'stations':[],
              'crs':quality['crs'], 'track_geometry_emitted':False,
              'next_controls':['Smiler: both lifts, inversion sequence, bank/roll and branch heights at crossings',
                               'Oblivion: station/lift datum, holding brake, drop shaft and underground exit profile'],
              'planning_application':'SMD/2011/1051: proposed Smiler layout requires as-built comparison'}
    rows = []
    try:
        for ride, station_name in RIDES.items():
            ways = [e for e in raw['elements'] if e.get('tags',{}).get('name')==ride
                    and e.get('tags',{}).get('roller_coaster')=='track']
            report['rides'][ride] = audit_route(ways, project.transform)
            buildings = [e for e in raw['elements'] if e.get('tags',{}).get('name')==station_name
                         and e.get('tags',{}).get('building')]
            if len(buildings)!=1:
                raise ValueError('Exactly one mapped station footprint required for '+ride)
            way = buildings[0]
            polygon = Polygon([project.transform(p['lon'],p['lat']) for p in way['geometry']])
            shell, detail = station_shell(polygon, ground.sample, surface.sample, 'xsector/station/'+str(way['id']))
            detail.update(name=station_name, osm_way_id=way['id'], footprint=mapping(polygon))
            rows.extend(shell); report['stations'].append(detail)
        if include_oblivion:
            from .oblivion_reconstruction import emit_track
            track,detail=emit_track(report['rides']['Oblivion'],
                                    next(s for s in report['stations'] if s['name']=='Oblivion Station'),ground.sample)
            # Track clearance must cut station portals; physical rail wins over
            # its own void. Existing generic station walls cannot hide the ride.
            composed={(r['x'],r['y'],r['z']):r for r in rows}
            composed.update({(r['x'],r['y'],r['z']):r for r in track})
            rows=list(composed.values())
            report['oblivion_reconstruction']=detail
            report['status']='estimated_oblivion_track_and_station_context'
            report['track_geometry_emitted']=True
            report['rides']['Oblivion']['track_generation']='estimated_visible_track'
            report['spawn_minecraft_xyz']=[-855,math.ceil(detail['height_controls_odn_m']['crest'])+quality['world']['vertical_offset_blocks']+8,165]
    finally:
        report['elevation_sources']={'terrain':ground.report(),'surface':surface.report()}
        ground.close(); surface.close()
    if len({(r['x'],r['y'],r['z']) for r in rows}) != len(rows):
        raise ValueError('Overlapping station overlays require explicit composition')
    return rows, report


def apply_overlay(source, output, rows, report, report_key='xsector_reconstruction', report_filename='xsector-report.json'):
    """Copy an existing world; verify every cell of touched chunks, not just solids."""
    import amulet
    from .bedrock import material_block
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Refusing to overwrite world output')
    base = json.loads((source/'quality-report.json').read_text())
    offset = base['world']['vertical_offset_blocks']
    if len({(r['x'],r['y'],r['z']) for r in rows})!=len(rows):
        raise ValueError('Overlay cells must be composed before application')
    by_chunk = {}
    for r in rows:
        x,y,z = r['x'],r['y']+offset,-r['z']
        if not -64<=y<=319:
            raise ValueError('Overlay outside Bedrock vertical limits')
        by_chunk.setdefault((x//16,z//16), []).append((x%16,y,z%16,r['material']))
    output.mkdir(parents=True)
    destination = output/'bedrock-world'
    shutil.copytree(source/'bedrock-world', destination, ignore=shutil.ignore_patterns('LOCK'))
    if (source/'resolved-config.json').exists():
        shutil.copy2(source/'resolved-config.json',output/'resolved-config.json')
    before_hash = hashlib.sha256((source/'park.mcworld').read_bytes()).hexdigest()
    level = amulet.load_level(str(destination))
    snapshots = {}
    solid_delta = 0
    try:
        original_coords = set(level.all_chunk_coords('minecraft:overworld'))
        if not set(by_chunk) <= original_coords:
            raise ValueError('Overlay must remain within existing mapped world chunks')
        for coords, changes in by_chunk.items():
            chunk = level.get_chunk(*coords, 'minecraft:overworld')
            for x,y,z,material in changes:
                old=chunk.block_palette[int(chunk.blocks[x,y,z])]
                solid_delta += int(material!='air')-int(old.base_name!='air')
                chunk.blocks[x,y,z] = chunk.block_palette.get_add_block(material_block(material))
            # Snapshot expected entire sections, including every unchanged cell.
            snapshots[coords] = {s:np.array([str(b) for b in chunk.block_palette],dtype=object)[
                                     chunk.blocks.get_sub_chunk(s)].copy() for s in chunk.blocks.sub_chunks}
            chunk.changed=True
            level.put_chunk(chunk, 'minecraft:overworld')
        if report.get('world_name'):
            from amulet_nbt import StringTag
            level.level_wrapper.root_tag.compound['LevelName']=StringTag(report['world_name'])
        if report.get('spawn_minecraft_xyz'):
            from amulet_nbt import IntTag, StringTag
            spawn=report['spawn_minecraft_xyz']
            if len(spawn)!=3 or not all(isinstance(v,int) for v in spawn) or not -60<=spawn[1]<=316:
                raise ValueError('Finite integer spawn within world height required')
            root=level.level_wrapper.root_tag.compound
            for key,value in zip(('SpawnX','SpawnY','SpawnZ'),spawn):root[key]=IntTag(value)
            root['LevelName']=StringTag(report.get('world_name','Alton Towers — X-Sector visible Oblivion draft'))
        level.save()
    finally:
        level.close()
    level = amulet.load_level(str(destination))
    try:
        if set(level.all_chunk_coords('minecraft:overworld'))!=original_coords:
            raise ValueError('Overlay altered chunk coverage')
        if report.get('spawn_minecraft_xyz'):
            root=level.level_wrapper.root_tag.compound
            actual_spawn=[int(root[k]) for k in ('SpawnX','SpawnY','SpawnZ')]
            if actual_spawn!=report['spawn_minecraft_xyz']:
                raise ValueError('New X-Sector spawn did not survive export')
        for coords, sections in snapshots.items():
            chunk = level.get_chunk(*coords, 'minecraft:overworld')
            palette = np.array([str(b) for b in chunk.block_palette],dtype=object)
            # Bedrock legitimately omits all-air sections. Compare the union
            # semantically, including absent sections as air, not stored keys.
            for s in set(chunk.blocks.sub_chunks)|set(sections):
                expected=sections.get(s)
                if expected is None:
                    expected=np.full((16,16,16),str(material_block('air')),dtype=object)
                actual=palette[chunk.blocks.get_sub_chunk(s)]
                if not np.array_equal(actual, expected):
                    cell=tuple(np.argwhere(actual!=expected)[0])
                    raise ValueError(f'Overlay or preserved-cell round trip failed: chunk {coords}, section {s}, cell {cell}: {expected[cell]} -> {actual[cell]}')
        report['world_verification']={'touched_chunks':len(by_chunk), 'overlay_records':len(rows),
                                    'check':'All cells of touched chunk sections and total chunk coverage verified',
                                    'untouched_chunks':'Copied from previously verified full-park world',
                                    'base_package_sha256':before_hash, 'vertical_offset_blocks':offset,
                                    'composed_block_delta':solid_delta}
    finally:
        level.close()
    report['visit_coordinates'] = [{'name':s['name'], 'minecraft_xyz':[
        math.floor(Polygon(s['footprint']['coordinates'][0]).centroid.x),s['roof_odn_m']+offset+5,
        -math.floor(Polygon(s['footprint']['coordinates'][0]).centroid.y)]} for s in report['stations']]
    (output/report_filename).write_text(json.dumps(report,indent=2))
    (destination/report_filename).write_text(json.dumps(report,indent=2))
    base[report_key]=report
    base['world']['composed_blocks'] += solid_delta
    if report.get('spawn_minecraft_xyz'):base['world']['spawn']=report['spawn_minecraft_xyz']
    base['world'].pop('explicit_air_cells',None)
    base['world']['explicit_air_cells_note']='Original count superseded by overlay; changed sections verified including all air'
    base['world']['round_trip_validation']='Base world previously verified; every cell of changed chunk sections rechecked'
    (destination/'voxel-quality-report.json').write_text(json.dumps(base,indent=2))
    package = output/'park.mcworld'
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(destination.rglob('*')):
            if p.is_file() and p.name!='LOCK':archive.write(p,p.relative_to(destination))
    base['world']['sha256']=hashlib.sha256(package.read_bytes()).hexdigest()
    base['world']['round_trip_validation']='Base world previously verified; every cell of changed chunk sections rechecked'
    (output/'quality-report.json').write_text(json.dumps(base,indent=2))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--park-output',required=True);p.add_argument('--osm-raw',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--include-oblivion',action='store_true',help='Emit explicit estimated track/supports/tunnel clearance; not verified planning geometry')
    p.add_argument('--datum-grid',required=True,help='Retained OSTN15 file; checked against original acquisition hash')
    args=p.parse_args(); source=Path(args.park_output)
    config=json.loads((source/'resolved-config.json').read_text())
    from .survey import activate_retained_grid
    import copy
    datum_source=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'))
    datum_source['coordinate_transform']['grid']['file']=args.datum_grid
    activate_retained_grid(datum_source)
    rows, report=build_overlay(config,
                               json.loads((source/'quality-report.json').read_text()),
                               json.loads(Path(args.osm_raw).read_text()),include_oblivion=args.include_oblivion)
    apply_overlay(source,args.output,rows,report)
    print(json.dumps({k:report[k] for k in ('stations','world_verification','visit_coordinates')},indent=2))


if __name__=='__main__':main()
