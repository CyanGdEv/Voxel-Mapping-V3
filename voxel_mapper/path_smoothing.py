"""Native paving transitions: smooth the existing footprint, not a new strip."""
import argparse,collections,copy,json,math
from pathlib import Path
from pyproj import CRS,Transformer
from shapely.geometry import Point,LineString,shape
from .bedrock import ALLOWED_MATERIALS,material_block
from .terrain import Terrain
from .survey import activate_retained_grid
from .transport import transport_kind,transport_profile
from .reconstruction.geometry import roof_cells
from .reconstruction.garden_surfaces import path_transitions
from .xsector import apply_overlay


def reconstruct(source,baseline,output,osm,boundary,grid):
    import amulet
    source,baseline,output=map(Path,(source,baseline,output))
    if output.exists():raise ValueError('Refusing to overwrite smoothing output')
    report16=json.loads((source/'garden-report.json').read_text());quality=json.loads((source/'quality-report.json').read_text());config=json.loads((source/'resolved-config.json').read_text())
    sources={s['id']:copy.deepcopy(s) for s in config['sources']};sources['ea-dtm']['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(sources['ea-dtm'])
    crs=CRS.from_wkt(quality['crs']);project=Transformer.from_crs(4326,crs,always_xy=True);terrain=Terrain(config['terrain'],crs,sources);border=shape(json.loads(Path(boundary).read_text()))
    worlds=[amulet.load_level(str(p/'bedrock-world')) for p in (source,baseline)];caches=[{},{}];offset=quality['world']['vertical_offset_blocks'];cells={}
    def actual(k,index=0):
        x,y,z=k;ck=x//16,(-z)//16
        if ck not in caches[index]:caches[index][ck]=worlds[index].get_chunk(*ck,'minecraft:overworld')
        ch=caches[index][ck];return ch.block_palette[int(ch.blocks[x%16,y+offset,(-z)%16])]
    def block(k):return material_block(cells[k]['material']) if k in cells else actual(k)
    def put(k,m,feature):cells[k]={'x':k[0],'y':k[1],'z':k[2],'material':m,'feature':feature}
    protected=set();water={(c['x'],c['z']) for c in json.loads(Path('park-water-v11/water-columns.json').read_text())}
    for file in [baseline/'foliage-overlay.jsonl',Path('recovery/Alton_Towers_Wicker_Trestles_V9_Evidence/completion-overlay.jsonl')]:
        for line in file.open():
            a=json.loads(line);protected.add((a['x'],a['y'],a['z']))
    protected.update(tuple(k) for k in json.loads(Path('recovery/Alton_Towers_Wicker_Trestles_V9_Evidence/rider-envelope.json').read_text()))
    for t in json.loads((baseline/'park-foliage-report.json').read_text())['trees']:protected.add((t['x'],t['base_odn_m'],t['z']))
    removed={'Bandstand stair connection','Western cascade descent','Lower gardens long stair flight','Pagoda east connection'};restored=0;inverse={str(material_block(m)):m for m in ALLOWED_MATERIALS};withheld=collections.Counter();surfaces={};waystats=[]
    try:
        for line in (source/'garden-overlay.jsonl').open():
            a=json.loads(line);k=a['x'],a['y'],a['z']
            if a['feature'] in removed:
                old=actual(k,1);m=inverse.get(str(old))
                if m is None:raise ValueError('Unmapped original restoration material: '+str(old))
                put(k,m,'restore-misaligned-trace');restored+=1
            elif a['feature'] not in {f['id'] for f in report16['features'] if f['kind']=='path'}:protected.add(k)
        routes=[]
        for e in json.loads(Path(osm).read_text())['elements']:
            t=e.get('tags',{});kind=transport_kind(t);coords=e.get('geometry',[])
            if kind not in ('path','steps','sidewalk','queue') or len(coords)<2 or t.get('bridge')=='yes' or t.get('tunnel')=='yes':continue
            points=[project.transform(p['lon'],p['lat']) for p in coords];line=LineString(points)
            if line.length<.5 or line.length>10000:continue
            width=transport_profile(t,kind,True)['width_m'];routes.append((f"osm/{e['type']}/{e['id']}",line,width,kind=='steps'))
        for f in report16['features']:
            if f['kind']=='path' and f['id'] not in removed:routes.append((f['id'],shape(f['local_geometry']),f['width_m'],False))
        for identity,line,width,steps in routes:
            found=0
            candidates=set();radius=min(width,12)/2
            for station in range(0,math.ceil(line.length),80):
                p0=line.interpolate(station);p1=line.interpolate(min(line.length,station+80))
                # Include intermediate vertices so curves retain their actual route.
                from shapely.ops import substring
                part=substring(line,station,min(line.length,station+80))
                candidates.update(roof_cells(part.buffer(radius)))
                if len(candidates)>100000:raise ValueError('Mapped path cell budget exceeded')
            for x,z in candidates:
                point=Point(x+.5,z+.5)
                if not border.covers(point) or (x,z) in water:continue
                h=terrain.sample(x+.5,z+.5)
                if h is None:continue
                y=math.floor(h)+4
                while y>=math.floor(h)-3 and block((x,y,z)).base_name=='air':y-=1
                b=block((x,y,z));name=b.base_name;family={'stone':'stone','stone_bricks':'stone_brick','cobblestone':'stone','brick_block':'brick','sandstone':'sandstone'}.get(name)
                top=y+1
                if name in ('slab','stairs'):
                    family=b.properties.get('material');family=family.py_data if family else None
                    if name=='slab' and b.properties.get('type') and b.properties['type'].py_data=='bottom':top=y+.5
                if family not in ('stone','stone_brick','brick','sandstone','oak','spruce','dark_oak'):continue
                if (x,y,z) in protected or any(block((x,yy,z)).base_name!='air' for yy in (y+1,y+2)):continue
                s=line.project(point);p0=line.interpolate(max(0,s-1));p1=line.interpolate(min(line.length,s+1));distance=line.distance(point)
                if (x,z) in surfaces and surfaces[(x,z)]['distance']<=distance:continue
                surfaces[(x,z)]={'top':top,'y':y,'partial':name in ('slab','stairs'),'top_slab':name=='slab' and b.properties['type'].py_data=='top','family':family,'tangent':(p1.x-p0.x,p1.y-p0.y),'steps':steps,'distance':distance,'source':identity};found+=1
            waystats.append({'id':identity,'accepted_path_columns':found})
        normalized=0
        for (x,z),a in surfaces.items():
            if not a['top_slab']:continue
            m={'stone_brick':'stone_bricks','brick':'bricks','oak':'oak_planks','spruce':'spruce_planks','dark_oak':'dark_oak_planks'}.get(a['family'],a['family'])
            put((x,a['y'],z),m,a['source']);a['partial']=False;normalized+=1
        transitions=path_transitions(surfaces);accepted=[]
        for (x,z),change in transitions.items():
            k=x,change['y'],z;a=surfaces[(x,z)];m=change['material']
            if k in protected or any((x,yy,z) in protected or block((x,yy,z)).base_name!='air' for yy in (k[1]+1,k[1]+2)):
                withheld['headroom_or_protected_cell']+=1;continue
            if change['kind']=='slab' and block(k).base_name!='air':withheld['occupied_slab_site']+=1;continue
            if block((x,k[1]-1,z)).base_name=='air':withheld['unsupported_transition']+=1;continue
            put(k,m,a['source']);accepted.append({'x':x,'z':z,'original_top':a['top'],**change,'source':a['source']})
    finally:
        terrain.close()
        for w in worlds:w.close()
    rows=list(cells.values());report={'world_name':'Alton Towers — Aligned path transitions V17','stations':[], 'restored_misaligned_stair_traces':sorted(removed),'restored_original_cells':restored,'mapped_routes':len(routes),'native_paved_columns':len(surfaces),'normalized_top_slab_landings':normalized,'transition_count':len(accepted),'transition_kinds':dict(collections.Counter(t['kind'] for t in accepted)),'material_counts':dict(collections.Counter(r['material'] for r in rows)),'withheld':dict(withheld),'transitions':accepted,'routes':waystats,'limitations':['Transitions only change actual paved columns inside existing mapped/retained path footprints.','Original native elevations are retained; this inserts half-step transitions, not an engineering regrade.','Protected foliage, water, ride clearance and V16 barriers/walls are not modified.','Existing gaps and rises greater than one metre are not bridged without geometry evidence.','Four provisional planning stair traces are restored to V15 and replaced by smoothing mapped native paths.']}
    apply_overlay(source,output,rows,report,'path_smoothing','path-smoothing-report.json');(output/'path-smoothing-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));print(json.dumps({k:report[k] for k in ('restored_original_cells','native_paved_columns','transition_count','transition_kinds','withheld','world_verification')},indent=2),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','baseline','output','osm','boundary','grid'):p.add_argument('--'+name,required=True)
    a=p.parse_args();reconstruct(a.source,a.baseline,a.output,a.osm,a.boundary,a.grid)
if __name__=='__main__':main()
