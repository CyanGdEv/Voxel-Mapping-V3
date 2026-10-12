"""Evidence-backed garden surface patches and bounded bridge reconstruction."""
import argparse,collections,hashlib,json,math
from pathlib import Path
import amulet,numpy as np,pymupdf
from shapely.geometry import Polygon,LineString,Point,mapping
from shapely.ops import transform
from pyproj import CRS,Transformer
from voxel_mapper.survey import activate_retained_grid
from voxel_mapper.wicker_registration import apply_candidate
from voxel_mapper.reconstruction.garden_bridges import bridge_cells
from voxel_mapper.reconstruction.walking_audit import require_bridge_walks
from voxel_mapper.reconstruction.geometry import roof_cells
from voxel_mapper.paving_palette import palette_block
from voxel_mapper.xsector import apply_overlay


def run(source,output,pdfs,osm,grid,rail_overlay):
 source,output,pdfs=map(Path,(source,output,pdfs));data=Path(__file__).resolve().parents[1]/'voxel_mapper/data'
 q=json.loads((source/'quality-report.json').read_text());cfg=json.loads((source/'resolved-config.json').read_text())
 datum=next(s for s in cfg['sources'] if s['id']=='ea-dtm');datum['coordinate_transform']['grid']['file']=str(Path(grid).resolve());activate_retained_grid(datum)
 survey=json.loads((data/'alton-gardens-v16.json').read_text());review=json.loads((data/'alton-garden-surfaces-v19.json').read_text())
 sheets={s['title']:s for s in survey['sources']}
 for s in sheets.values():assert hashlib.sha256((pdfs/(s['document_id']+'.pdf')).read_bytes()).hexdigest()==s['document_id']
 crs=CRS(q['crs']);b2l=Transformer.from_crs(27700,crs,always_xy=True);ll=Transformer.from_crs(4326,crs,always_xy=True)
 def projected(geom,sheet):
  c=sheets[sheet]['alignment']['candidate']
  def f(x,y,z=None):
   a=apply_candidate(list(zip(x,y)),c);return b2l.transform(a[:,0],a[:,1])
  return transform(f,geom)
 level=amulet.load_level(str(source/'bedrock-world'));chunks={};offset=q['world']['vertical_offset_blocks'];floors={};cells={};stats=[];wet_columns={};known_rails=set()
 rail_file=Path(rail_overlay)
 if rail_file.exists():
  for row in map(json.loads,rail_file.read_text().splitlines()):
   if row['material'] in ('green_stained_glass_pane','iron_bars'):known_rails.add((row['x'],row['y'],row['z']))
 def native(k):
  x,y,z=k;key=x//16,(-z)//16
  if key not in chunks:chunks[key]=level.get_chunk(*key,'minecraft:overworld')
  c=chunks[key];return c.block_palette[int(c.blocks[x%16,y+offset,(-z)%16])]
 def ground(x,z):
  if (x,z) not in floors:
   ys=[y for y in range(110,200) if native((x,y,z)).base_name=='dirt']
   floors[x,z]=max(ys)+1 if ys else None
  return floors[x,z]
 def water_top(x,z):
  if (x,z) not in wet_columns:
   ys=[y for y in range(110,190) if native((x,y,z)).base_name=='water'];wet_columns[x,z]=max(ys) if ys else None
  return wet_columns[x,z]
 def safe(k,clear=False):
  b=native(k).base_name
  return b in ('air','grass_block','dirt','stone','cobblestone','stone_bricks','concrete','slab','stairs','sandstone')
 def put(k,m,id):cells[k]={'x':k[0],'y':k[1],'z':k[2],'material':m,'feature':id,'source':'garden-survey-v19'}
 try:
  for f in review['surfaces']:
   g=projected(Polygon(f['polygon']),f['sheet']);applied=blocked=0
   for x,z in roof_cells(g):
    y=ground(x,z)
    if y is None or not safe((x,y,z)) or native((x,y+1,z)).base_name not in ('air','slab'):blocked+=1;continue
    old=native((x,y,z));m=palette_block(f['material'],x,z)
    # Preserve all existing half-height slope geometry; recolour full paving only.
    if old.base_name in ('slab','stairs'):blocked+=1;continue
    put((x,y,z),m,f['id']);applied+=1
   # Cross-road width derived from projected opposite traced edges, not a default buffer.
   p=f['polygon'];width=LineString([p[0],p[1]]).length*sheets[f['sheet']]['alignment']['candidate']['scale_m_per_pdf_point']
   stats.append({**f,'local_geometry':mapping(g),'emitted_columns':applied,'withheld_columns':blocked,'sample_boundary_separation_m':width,'width_status':'scaled reviewed vertices; variable corridor polygon, not a constant survey width'})
  raw=json.loads(Path(osm).read_text());ways={e['id']:e for e in raw['elements'] if e['type']=='way'}
  bridge_specs=[(106844059,'White Bridge',3.2,177,'white_ashlar_arch',20),(107255927,'Miniature Bridge',1.6,150,'cast_iron_three_span',6),(107257798,'Western garden crossing',2.0,170,'footbridge',6),(107257800,'Cascade stream crossing',2.0,160,'footbridge',6)]
  for id,name,width,top,style,length in bridge_specs:
   line=LineString([ll.transform(p['lon'],p['lat']) for p in ways[id]['geometry']]);geometry_status='retained OSM bridge axis';measured_width=None
   if id==107255927:
    b=review['miniature_bridge'];s=sheets[b['sheet']];p=pymupdf.open(pdfs/(s['document_id']+'.pdf'))[0]
    d=p.get_drawings()[b['vector_path']];pts=[list(i[1]) for i in d['items'] if i[0]=='l'];assert np.allclose(pts[:4],b['outline'][:4],atol=.02)
    edges=[LineString(e) for e in b['inner_edges']];measured_width=edges[0].distance(edges[1])*s['alignment']['candidate']['scale_m_per_pdf_point']
    ends=[((e[0][0]+b['inner_edges'][1][j][0])/2,(e[0][1]+b['inner_edges'][1][j][1])/2) for j,e in enumerate([b['inner_edges'][0][:1],b['inner_edges'][0][1:]])]
    line=projected(LineString(ends),b['sheet']);geometry_status='hash-pinned native vector bridge edges';width=1.6
   planned,clear,walk=bridge_cells(line,width,top,ground,style,length,water_top)
   relocated={k for k in set(planned)|clear if k in known_rails and native(k).base_name in ('stained_glass_pane','bars') and (k[0],k[2]) in walk}
   def bridge_safe(k):return safe(k) or k in relocated
   conflicts=[k for k in planned if not bridge_safe(k) and (k[0],k[2]) in walk]
   conflicts += [k for k in clear if not bridge_safe(k)]
   if conflicts:
    stats.append({'id':name,'status':'withheld','reason':'protected native collision','conflict_count':len(conflicts),'examples':[list(k)+[native(k).base_name] for k in conflicts[:8]]});continue
   emitted=decor_withheld=0
   for k,m in planned.items():
    if not bridge_safe(k):decor_withheld+=1;continue
    put(k,'green_stained_glass_pane' if relocated and m=='iron_bars' and k[1]>=math.ceil(top) else m,name);emitted+=1
   for k in clear:put(k,'air',name)
   stats.append({'id':name,'status':'emitted','osm_way':id,'style':style,'local_axis':mapping(line),'width_m':width,'geometry_status':geometry_status,'walking_top_odn_m':top,'vertical_status':'native approach / surveyed deck estimate with one-metre clearance quantization','measured_inner_width_m':measured_width,'width_status':'scaled plan measurement' if measured_width else 'estimated','source_survey_deck_odn_m':149.5 if id==107255927 else None,'emitted_solid_cells':emitted,'relocated_reviewed_railing_cells':len(relocated),'withheld_decoration_cells':decor_withheld,'walk_columns':len(walk),'walk_heights':[[x,z,h] for (x,z),h in walk.items()],'materials_status':'ashlar/white balustrade and cast iron/stone piers supported by NHLE; deck finishes and unlabelled crossings are proxies'})
 finally:level.close()
 report={'stations':[],'world_name':'Alton Towers V19 — Garden bridges and reviewed paving','registration_verified':False,'base_sha256':hashlib.sha256((source/'park.mcworld').read_bytes()).hexdigest(),'features':stats,'sources':survey['sources'],'railing_provenance_sha256':hashlib.sha256(rail_file.read_bytes()).hexdigest(),'heritage_sources':['https://historicengland.org.uk/listing/the-list/list-entry/1037870','https://historicengland.org.uk/listing/the-list/list-entry/1037878'],'water_policy':'Never overwrite water or bed material; collided ornamental ribs withheld','limitations':review['limitations']+['White Bridge arch curvature, balustrade, approach ramps and bridge elevations are proxies; named heritage records establish topology/material, not dimensions.','Slabs and stairs already in the park are preserved during surface recolouring.','One-metre bridge rail spacing expands the visible envelope beyond fine source profiles.']}
 rows=list(cells.values());apply_overlay(source,output,rows,report,'garden_bridges','garden-bridges-report.json',verify_world=lambda level,offset:require_bridge_walks(level,offset,stats));(output/'garden-bridges-overlay.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));print(json.dumps({'features':[{k:v for k,v in f.items() if k not in ('local_geometry','local_axis','walk_heights','polygon')} for f in stats],'native':report['world_verification'],'walking':report['semantic_verification']},indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('source','output','pdfs','osm','grid','rail-overlay'):p.add_argument('--'+k,required=True)
 a=p.parse_args();run(a.source,a.output,a.pdfs,a.osm,a.grid,a.rail_overlay)
