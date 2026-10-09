"""Bounded, explicitly estimated courtyard wing shells in existing mapped placement."""
import argparse
import collections
import copy
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from .reconstruction.geometry import roof_cells

RELATION = 5496185


def mapped_courtyard(raw, project):
    relations = [e for e in raw['elements'] if e['type']=='relation' and e['id']==RELATION]
    if len(relations)!=1: raise ValueError('Exactly one retained courtyard relation required')
    relation=relations[0]
    if relation.get('tags',{}).get('building')!='yes': raise ValueError('Courtyard building identity changed')
    members=relation['members']
    if [(m['ref'],m['role']) for m in members]!=[(113576008,'outer'),(106842140,'inner')]:
        raise ValueError('Reviewed courtyard member identities changed')
    rings=[[project(p['lon'],p['lat']) for p in m['geometry']] for m in members]
    polygon=Polygon(rings[0],[rings[1]])
    if not polygon.is_valid or not 800<polygon.area<1600 or len(polygon.interiors)!=1:
        raise ValueError('Bounded courtyard wing ring with one protected hole required')
    return polygon


def wing_shell(polygon, ground, surface):
    """Retain mapped extent; only finite, sufficiently elevated roof observations qualify.

    No plan transform, extensions, entrances or internal room divisions are inferred.
    Low-return edge cells stay as they were rather than receiving invented roofs.
    """
    if not polygon.is_valid or len(polygon.interiors)!=1 or not 10<polygon.area<1600:
        raise ValueError('Valid bounded wing ring required')
    observations=[]
    for x,z in roof_cells(polygon):
        g,s=ground(x+.5,z+.5),surface(x+.5,z+.5)
        if g is None or s is None or not math.isfinite(g+s):
            raise ValueError('Complete finite terrain/surface coverage required')
        observations.append((x,z,g,s))
    qualified={(x,z):(g,s) for x,z,g,s in observations if 3<=s-g<=13}
    if len(qualified)/len(observations)<.8:
        raise ValueError('Insufficient elevated surface support for courtyard wings')
    rows=[]
    for (x,z),(g,s) in sorted(qualified.items()):
        # Keep terrain and its first surface layer. Interior floor is retained,
        # not replaced by a hypothetical level floor across the four wings.
        bottom=math.ceil(g)+1
        roof=math.ceil(s)
        if roof-bottom<2: continue
        edge=any((x+dx,z+dz) not in qualified for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)))
        for y in range(bottom,roof+1):
            material='red_terracotta' if y==roof else 'bricks' if edge else 'air'
            rows.append({'x':x,'y':y,'z':z,'kind':'structure','material':material,
                         'feature':'mutiny/courtyard-wings','source':'mutiny-courtyard-estimate',
                         'material_origin':'estimated_brick_and_tile_shell'})
    return rows, {'mapped_columns':len(observations),'elevated_columns':len(qualified),
                  'withheld_low_or_high_return_columns':len(observations)-len(qualified),
                  'ground_range_odn_m':[min(o[2] for o in observations),max(o[2] for o in observations)],
                  'surface_range_odn_m':[min(v[1] for v in qualified.values()),max(v[1] for v in qualified.values())],
                  'roof_rule':'Nearest one-metre DSM observation, rounded upward; no smoothing or plan-height inference',
                  'shell_rule':'One-cell boundary walls, retained ground/floor, hollow interior; rooms/openings unresolved'}


def guard_native(rows, block_at):
    """Withhold an entire column if another structure or extra block would be overwritten."""
    columns=collections.defaultdict(list)
    for row in rows: columns[row['x'],row['z']].append(row)
    accepted=[];protected=[]
    for column,changes in sorted(columns.items()):
        blocks=[block_at(r['x'],r['y'],r['z']) for r in changes]
        roof=max(r['y'] for r in changes)
        # The former solid extrusion can have a flat cap above the observed
        # sloping roof. Remove only bounded, known generic leftovers there.
        above=[(y,block_at(column[0],y,column[1])) for y in range(roof+1,roof+9)]
        if any(b.base_name not in ('air','stone_bricks','stone') or b.extra_blocks for _,b in above):
            protected.append(list(column));continue
        if any(b.base_name not in ('air','stone_bricks','stone') or b.extra_blocks for b in blocks):
            protected.append(list(column));continue
        # Only existing generic building columns may become estimated shells.
        # Observed foliage/roof over empty space cannot create a new building.
        if not any(b.base_name=='stone_bricks' for b in blocks):
            protected.append(list(column));continue
        accepted.extend(changes)
        accepted.extend(dict(changes[-1],y=y,material='air',material_origin='generic_roof_cap_removal')
                        for y,b in above if b.base_name!='air')
    if not accepted: raise ValueError('No eligible generic building columns')
    return accepted,protected


def build_overlay(source, raw, terrain_path, surface_path, grid_path, cache):
    import amulet
    from .terrain import Terrain
    from .survey import activate_retained_grid
    from .mutiny_bay_review import extract_roof, compare_envelopes
    from shapely.geometry import shape
    source=Path(source)
    config=json.loads((source/'resolved-config.json').read_text())
    quality=json.loads((source/'quality-report.json').read_text())
    datum=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'))
    datum['coordinate_transform']['grid']['file']=str(Path(grid_path).resolve())
    activate_retained_grid(datum)
    project=Transformer.from_crs(4326,quality['crs'],always_xy=True)
    polygon=mapped_courtyard(raw,project.transform)
    sources={s['id']:s for s in config['sources']}
    g=Terrain(dict(config['terrain'],path=terrain_path),quality['crs'],sources)
    s=Terrain(dict(config['terrain'],path=surface_path,source_id='alton-surface-mosaic'),quality['crs'],sources)
    try:
        rows,detail=wing_shell(polygon,g.sample,s.sample)
        elevation={'terrain':g.report(),'surface':s.report()}
    finally:g.close();s.close()
    world=amulet.load_level(str(source/'bedrock-world'));chunks={}
    def native(x,y,z):
        key=x//16,(-z)//16
        if key not in chunks:chunks[key]=world.get_chunk(*key,'minecraft:overworld')
        c=chunks[key]
        return c.block_palette[int(c.blocks[x%16,y+quality['world']['vertical_offset_blocks'],(-z)%16])]
    try: rows,protected=guard_native(rows,native)
    finally:world.close()
    profile=extract_roof(cache)
    to_bng=Transformer.from_crs(quality['crs'],27700,always_xy=True)
    from shapely.ops import transform
    outer=transform(to_bng.transform,Polygon(polygon.exterior))
    hole=transform(to_bng.transform,Polygon(polygon.interiors[0]))
    diagnostics={'outer_envelope':compare_envelopes(shape(profile['roof_envelope_geometry']),outer,profile['scale_m_per_point']),
                 'inner_eaves':compare_envelopes(shape(profile['courtyard_geometry']),hole,profile['scale_m_per_point'])}
    report={'status':'estimated_mapped_courtyard_wing_shells','world_name':'Alton Towers V21 — Mutiny Bay courtyard draft',
            'osm_relation':RELATION,'footprint':mapping(polygon),'protected_courtyard':mapping(Polygon(polygon.interiors[0])),
            'footprint_area_m2':polygon.area,'protected_courtyard_area_m2':Polygon(polygon.interiors[0]).area,
            'profile':detail,'protected_native_columns':protected,'overlay_records':len(rows),
            'elevation_sources':elevation,'planning_profile':profile,'planning_alignment_diagnostics':diagnostics,
            'planning_registration_verified':False,'planning_geometry_emitted':False,
            'materials':{'walls':'bricks','roof':'red_terracotta','status':'Provisional proxies for dated brick walls and tiled roofs'},
            'limitations':['Placement uses existing mapped relation, not a registered planning drawing',
                           'Composite surface dates vary; roof heights are estimates, not a current architectural survey',
                           'Roof colour, one-cell walls, hollow interiors and nearest-pixel roof steps are provisional',
                           'No doors, archways, rooms, tower detailing, annex extensions or ride geometry reconstructed',
                           'Low/high return and conflicting native columns retained unchanged; central canopy and courtyard untouched'],
            'stations':[]}
    return rows,report



def native_hole_signature(world, offset, hole):
    """Hash every native block and extra block in the mapped courtyard columns."""
    chunks={};digest=hashlib.sha256();cells=roof_cells(hole)
    for x,z in sorted(cells):
        key=x//16,(-z)//16
        if key not in chunks:chunks[key]=world.get_chunk(*key,'minecraft:overworld')
        chunk=chunks[key]
        for native_y in range(-64,320):
            block=chunk.block_palette[int(chunk.blocks[x%16,native_y,(-z)%16])]
            digest.update((str(block)+'\n').encode())
    return {'sha256':digest.hexdigest(),'columns':len(cells),'native_y_range':[-64,319],
            'blocks_checked':len(cells)*384}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for option in ('source-output','osm','terrain','surface','datum-grid','cache','output'):p.add_argument('--'+option,required=True)
    a=p.parse_args();source=Path(a.source_output)
    raw_bytes=Path(a.osm).read_bytes()
    rows,report=build_overlay(source,json.loads(raw_bytes),a.terrain,a.surface,a.datum_grid,a.cache)
    report['osm_sha256']=hashlib.sha256(raw_bytes).hexdigest()
    from .xsector import apply_overlay
    from .reconstruction.walking_audit import require_bridge_walks
    bridges=json.loads((source/'bedrock-world'/'garden-bridges-report.json').read_text())['features']
    import amulet
    from shapely.geometry import shape
    hole=shape(report['protected_courtyard'])
    offset=json.loads((source/'quality-report.json').read_text())['world']['vertical_offset_blocks']
    original=amulet.load_level(str(source/'bedrock-world'))
    try: signature=native_hole_signature(original,offset,hole)
    finally: original.close()
    def verify(world,shift):
        actual=native_hole_signature(world,shift,hole)
        if actual!=signature:raise ValueError('Protected courtyard/canopy changed during export')
        return {'protected_courtyard':dict(actual,status='unchanged'),
                'garden_bridges':require_bridge_walks(world,shift,bridges)}
    report=apply_overlay(source,a.output,rows,report,'mutiny_bay_courtyard','mutiny-bay-courtyard-report.json',
                         verify_world=verify)
    (Path(a.output)/'mutiny-bay-courtyard-overlay.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','profile','world_verification','semantic_verification')},indent=2))

if __name__=='__main__':main()
