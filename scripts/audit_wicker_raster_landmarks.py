"""Reproduce retained Wicker comparison-footprint raster coverage observations."""
import argparse,json,sys,zipfile,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rasterio
from rasterio.windows import from_bounds,Window
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import shape
from shapely.ops import transform
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.raster_landmarks import observations


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('terrain','surface','grid','references','archive','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();expected='5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa'
    if file_hash(a.grid)!=expected:raise ValueError('Retained grid hash mismatch')
    with zipfile.ZipFile(a.archive) as z:config=json.loads(z.read('park-water-v11/resolved-config.json'))
    lineage=next(s['lineage'] for s in config['sources'] if s['id']=='alton-terrain-mosaic')
    if file_hash(a.terrain)!=lineage['merged_sha256']:raise ValueError('Retained terrain lineage mismatch')
    surface_lineage=next(s['lineage'] for s in config['sources'] if s['id']=='alton-surface-mosaic')
    if file_hash(a.surface)!=surface_lineage['merged_sha256']:raise ValueError('Retained surface lineage mismatch')
    datadir.append_data_dir(str(Path(a.grid).resolve().parent))
    group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Metre-scale retained-grid transformation required')
    project=group.transformers[0];rows=[]
    with rasterio.open(a.terrain) as ground,rasterio.open(a.surface) as top:
        if ground.crs.to_epsg()!=27700 or top.crs!=ground.crs or ground.transform!=top.transform or ground.shape!=top.shape or ground.res!=(1,1):raise ValueError('Matched native BNG one-metre rasters required')
        for f in json.loads(Path(a.references).read_text())['features']:
            if f['id'] not in ('osm/way/834919978','osm/way/70689589','osm/way/107259863'):continue
            g=transform(project.transform,shape(f['geometry']));w=from_bounds(*g.bounds,transform=ground.transform)
            left,bottom=math.floor(w.col_off),math.floor(w.row_off);right,upper=math.ceil(w.col_off+w.width),math.ceil(w.row_off+w.height)
            window=Window(left,bottom,right-left,upper-bottom)
            if left<0 or bottom<0 or right>ground.width or upper>ground.height:raise ValueError('Outline extends beyond raster coverage')
            values=observations(g,ground.read(1,window=window,masked=True),top.read(1,window=window,masked=True),ground.window_transform(window))
            rows.append({'reference_id':f['id'],'name':f['properties'].get('name',''),'outline_crs':'EPSG:27700',**values})
    report={'status':'independent_raster_observations_not_registration','input_sha256':{k:file_hash(getattr(a,k)) for k in ('terrain','surface','grid','references','archive')},'horizontal_transform_accuracy_m':project.accuracy,'rasters_crs':'EPSG:27700','vertical_datum':'ODN','resolution_m':1,'documented_patch_survey':lineage['patch_source']['survey'],'local_pixel_epoch':'unverified; no retained per-pixel patch provenance mask','landmarks':rows,'accepted_checkpoint_count':0,'world_geometry_additions':0,'limitations':['Comparison footprints derive from OSM and do not establish independently measured corners','DSM surfaces can be roofs, trees, supports or other elevated objects','Mixed-epoch mosaic cannot assign 2022 to each sampled pixel','Surface height is not floor height or ride rail elevation']}
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(rows))

if __name__=='__main__':main()
