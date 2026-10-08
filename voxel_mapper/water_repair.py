"""Repair retained water footprints with level surfaces and solid preview beds."""
import argparse,collections,json,math
from pathlib import Path
import amulet,numpy as np
from pyproj import CRS
from shapely.geometry import shape,Point
from .terrain import Terrain
from .survey import activate_retained_grid
from .water import surface_level,flowing_level,estimated_bed_y
from .xsector import apply_overlay


def repair(source,features_path,output,grid=None):
    source,output=Path(source),Path(output)
    q=json.loads((source/'quality-report.json').read_text());config=json.loads((source/'resolved-config.json').read_text())
    sources={s['id']:s for s in config['sources']}
    if grid:
        for s in sources.values():
            if s.get('coordinate_transform',{}).get('grid'):
                s['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(s)
    terrain=Terrain(config['terrain'],CRS.from_wkt(q['crs']),sources)
    features=[f for f in json.loads(Path(features_path).read_text())['features'] if f['properties'].get('kind')=='water']
    world=amulet.load_level(str(source/'bedrock-world'));cache={};coords=set(world.all_chunk_coords('minecraft:overworld'));offset=q['world']['vertical_offset_blocks'];rows={};columns={};reports=[];foundations={};protected=collections.Counter()
    natural={'air','water','flowing_water','grass_block','dirt','stone','granite','gravel','sand','coarse_dirt'}
    def old(x,y,z):
        key=x//16,(-z)//16
        if key not in coords or not -64<=y+offset<320:return None
        if key not in cache:cache[key]=world.get_chunk(*key,'minecraft:overworld')
        chunk=cache[key];return chunk.block_palette[int(chunk.blocks[x%16,y+offset,(-z)%16])]
    def put(x,y,z,material,feature):
        b=old(x,y,z)
        if b is None:return
        if b.base_name not in natural:protected[b.base_name]+=1;return
        rows[x,y,z]={'x':x,'y':y,'z':z,'kind':'water' if material=='water' else 'lakebed','material':material,'source':config['terrain']['source_id'],'feature':feature,
                     'geometry_method':'terrain_water_surface_with_estimated_shore_shelf','bed_status':'estimated_visual_bed; no surveyed bathymetry'}
        if len(rows)>1_500_000:raise ValueError('Water repair budget exceeded')
    try:
        for f in features:
            geom=shape(f['geometry']);p=f['properties'];level,message=surface_level(geom,terrain)
            flowing=p.get('waterway') in ('stream','river','drain','ditch') or (p.get('waterway')=='canal' and level is None)
            if level is None and not flowing:
                reports.append({'feature':f['id'],'status':'withheld','reason':message});continue
            count=0;levels=[];a,b,c,d=geom.bounds
            if (c-a)*(d-b)>500000:raise ValueError('Water footprint scan budget exceeded')
            for x in range(math.floor(a),math.ceil(c)):
                for z in range(math.floor(b),math.ceil(d)):
                    if not geom.covers(Point(x+.5,z+.5)) or (x//16,(-z)//16) not in coords:continue
                    local=flowing_level(geom,terrain,x,z) if flowing else level
                    if local is None:continue
                    top=math.floor(local);bed=estimated_bed_y(geom,x,z,local,max_depth_m=2 if flowing else 3)
                    key=x//16,(-z)//16
                    if key not in foundations:
                        vals=[terrain.sample(xx+.5,zz+.5) for xx in range(key[0]*16,key[0]*16+16,4) for zz in range(-key[1]*16-15,-key[1]*16+1,4)]
                        valid=[v for v in vals if v is not None and math.isfinite(v)]
                        foundations[key]=math.floor(min(valid))-16 if valid else bed-16
                    floor=min(bed-2,max(bed-32,foundations[key]))
                    for y in range(floor,bed+1):put(x,y,z,'gravel' if y==bed else 'dirt' if y>=bed-2 else 'stone',f['id'])
                    for y in range(bed+1,top+1):put(x,y,z,'water',f['id'])
                    # Remove obsolete water/ground caps only inside the mapped water.
                    ground=terrain.sample(x+.5,z+.5)
                    ceiling=max(top+1,math.ceil(ground) if ground is not None else top+1)
                    for y in range(top+1,ceiling+2):
                        block=old(x,y,z)
                        if block is not None and block.base_name in natural and block.base_name!='air':put(x,y,z,'air',f['id'])
                    columns[x,z]={'top':top,'bed':bed,'floor':floor,'feature':f['id']};count+=1;levels.append(top)
            reports.append({'feature':f['id'],'status':'repaired','columns':count,'surface_levels_m':[min(levels),max(levels)] if levels else None,'surface_method':'local_stream_terrain' if flowing else 'consistent_interior_terrain','bed_method':'estimated shore-distance shelf, maximum 2m for streams / 3m for lakes'})
    finally:world.close();terrain.close()
    report={'stations':[],'world_name':config.get('location','Park').split(',')[0]+' — Water surfaces and solid beds V10','water_features':reports,'columns':len(columns),'overlay_records':len(rows),'protected_structure_cells':dict(protected),
            'limitations':['Bed depths, substrate and artificial foundation fill are visual estimates, not surveyed bathymetry.','Lake levels use consistent interior DTM; streams use local terrain, not surveyed hydraulic profiles.']}
    apply_overlay(source,output,list(rows.values()),report,report_key='water_repair',report_filename='water-repair-report.json')
    world=amulet.load_level(str(output/'bedrock-world'));cache={};missing_water=[];missing_floor=[]
    try:
        for (x,z),col in columns.items():
            # Non-natural bridge/path/building blocks were deliberately protected.
            for y in range(col['bed']+1,col['top']+1):
                block=old(x,y,z)
                if block.base_name in natural and block.base_name not in ('water','flowing_water'):missing_water.append((x,y,z))
            for y in range(col['floor'],col['bed']+1):
                if old(x,y,z).base_name in ('air','water','flowing_water'):missing_floor.append((x,y,z))
    finally:world.close()
    checks={'water_columns_checked':len(columns),'missing_water_cells':len(missing_water),'missing_solid_bed_or_fill_cells':len(missing_floor)}
    (output/'water-checks.json').write_text(json.dumps(checks,indent=2));(output/'water-columns.json').write_text(json.dumps([{'x':x,'z':z,**col} for (x,z),col in columns.items()]));(output/'water-overlay.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows.values()))
    if missing_water or missing_floor:raise ValueError(f'Water repair validation failed: {checks}')
    print(json.dumps(checks));return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','features','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--datum-grid');args=parser.parse_args();repair(args.source,args.features,args.output,args.datum_grid)
if __name__=='__main__':main()
