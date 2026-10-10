"""Place the 1:1 Prospect Tower using the explicitly reviewed location estimate."""
import argparse, hashlib, json, math
from pathlib import Path
import amulet
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, box, LineString, mapping
from voxel_mapper.reconstruction.prospect import components
from voxel_mapper.reconstruction.model import Source, Feature
from voxel_mapper.reconstruction.sources import evidence
from voxel_mapper.reconstruction.engine import Context, ReconstructionEngine
from voxel_mapper.reconstruction.generators import default_registry
from voxel_mapper.reconstruction.replacement import compose_replacement
from voxel_mapper.survey import activate_retained_grid
from voxel_mapper.xsector import apply_overlay


def run(source, output, osm_path, grid):
    source=Path(source); output=Path(output)
    if hashlib.sha256((source/'park.mcworld').read_bytes()).hexdigest() != 'bd726ed32c376113e726531bc30794e836f1ba28ad3bd5b2a33e9a96ee4fd401':
        raise ValueError('This reviewed placement requires the retained V17 baseline')
    q=json.loads((source/'quality-report.json').read_text()); config=json.loads((source/'resolved-config.json').read_text())
    datum=next(s for s in config['sources'] if s['id']=='ea-dtm')
    datum['coordinate_transform']['grid']['file']=str(Path(grid).resolve()); activate_retained_grid(datum)
    crs=CRS.from_user_input(q['crs']); trans=Transformer.from_crs(27700,crs,always_xy=True)
    bng=[407744.2079,343322.4628]; anchor=trans.transform(*bng);east=trans.transform(bng[0]+1,bng[1])
    angle=math.degrees(math.atan2(east[1]-anchor[1],east[0]-anchor[0]))
    osm=json.loads(Path(osm_path).read_text());way=next(e for e in osm['elements'] if e['type']=='way' and e['id']==70689521)
    ll=Transformer.from_crs(4326,crs,always_xy=True);placeholder=Polygon([ll.transform(p['lon'],p['lat']) for p in way['geometry']])
    existing={}; ground={}; offset=q['world']['vertical_offset_blocks']
    level=amulet.load_level(str(source/'bedrock-world'))
    try:
        for x in range(math.floor(anchor[0])-13,math.floor(anchor[0])+14):
            for z in range(math.floor(anchor[1])-13,math.floor(anchor[1])+14):
                ch=level.get_chunk(x//16,(-z)//16,'minecraft:overworld')
                for y in range(150,210):
                    existing[x,y,z]=ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])].base_name
                soil=[y for y in range(150,210) if existing[x,y,z]=='dirt']
                if soil:ground[x,z]=max(soil)+1
    finally:level.close()
    # Existing approach pavement at (-191,-114) is ODN cell 182 (walk level 183).
    # This estimate is explicitly tied to the retained native world, not survey.
    base=183
    parts=components(1)
    sources={
        'study-profiles':Source('study-profiles','relative_drawing_profile','https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/ApplicationSearchServlet?PKID=71254','unconfirmed-drawing-reuse','LOCAL_METRIC_STUDY','ODN','accepted',metadata={'registration_scope':'local paper profiles only; geographic anchor is estimated'}),
        'study-proxies':Source('study-proxies','draft_design','local://prospect-draft','project',q['crs'],'ODN','accepted'),
        'estimated-placement':Source('estimated-placement','estimated_anchor','local://prospect-location-review','project',q['crs'],'ODN','unregistered',metadata={'bng':bng,'method':'AL3.42 north-up location plan station-centroid translation to retained OSM station','status':'estimated'})}
    feature=Feature('prospect-tower-draft','architectural_components',mapping(Point(*anchor)),'estimated-placement',
        {k:evidence(v,'study-proxies','estimated') for k,v in {'base_elevation_m':base,'rotation_degrees':angle,'components':parts}.items()}, {'placement':'estimated; not independently registered','scale':1})
    model,plan=ReconstructionEngine(default_registry()).plan([feature],Context(sources,lambda x,z:182,box(anchor[0]-13,anchor[1]-13,anchor[0]+14,anchor[1]+14),'ODN',True))
    if not model:raise ValueError(plan['decisions'])
    # Inferred two-block approach, explicitly distinct from traced planning paving.
    route=LineString([(-194.5,-115.5),(-192.5,-114.5),(-190.5,-113.5)]).buffer(.7)
    approach=[]
    for x in range(-196,-189):
        for z in range(-117,-112):
            if route.covers(Point(x+.5,z+.5)):
                if ground[x,z]!=182:raise ValueError('Approach estimate no longer matches level terrain')
                approach.append({'x':x,'y':182,'z':z,'material':'sandstone','kind':'inferred-approach'})
    # Solid platform footings down to retained terrain, restricted to deck cells.
    for r in model:
        if r['y']==182:
            for y in range(ground[r['x'],r['z']],182):
                approach.append({'x':r['x'],'y':y,'z':r['z'],'material':'sandstone','kind':'platform-foundation'})
    rows,checks=compose_replacement(existing,ground,placeholder,model,approach)
    spawn=[-190,base+offset+2,114]
    report={'stations':[],'world_name':'Alton Towers V18 — Prospect Tower estimated placement',
        'spawn_minecraft_xyz':spawn,'landmark_visit_coordinates':spawn,
        'placement_status':'estimated','anchor_bng_m':bng,'anchor_local_m':anchor,'rotation_degrees':angle,
        'base_odn_m':base,'base_method':'Existing native approach walk level 183 ODN; not surveyed tower floor',
        'blocks_per_source_metre':1,'component_count':len(parts),'model_voxel_cells':len(model),
        'placeholder_osm_id':'way/70689521','placeholder_geometry':mapping(placeholder),
        'approach_geometry':mapping(route),'approach_status':'inferred short level link; not traced planning geometry',
        'composition':checks,'geometry_plan':plan,
        'limitations':['Location uses station-centroid alignment without independent checkpoints.',
            'Existing 2014 drawing dimensions and proposed colours; current condition unverified.',
            'One-metre blocks merge fine members; internal stair treads and carved detail remain proxies.',
            'Roof, railing and balcony envelopes retain the relative-study approximations.',
            'No in-game visual fidelity validation.'],
        'sources':[s.__dict__ for s in sources.values()]}
    apply_overlay(source,output,rows,report,report_key='prospect_tower_draft',report_filename='prospect-placement-report.json')
    (output/'prospect-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    print(json.dumps({'composition':checks,'native_validation':report['world_verification'],'spawn':spawn},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('source','output','osm','grid'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.source,a.output,a.osm,a.grid)
