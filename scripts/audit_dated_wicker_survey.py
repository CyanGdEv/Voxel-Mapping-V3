"""Crop a pinned original dated survey pair and audit Wicker landmark surfaces."""
import argparse,json,sys,math,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rasterio
from pyproj import datadir
from pyproj.transformer import TransformerGroup
from shapely.geometry import Polygon
from shapely.ops import transform,unary_union
from rasterio.windows import from_bounds,Window
from voxel_mapper.survey import crop_pair
from voxel_mapper.boundary_registration import file_hash
from voxel_mapper.raster_landmarks import observations,elevated_regions

PINS={'dtm':'ef7cc8cfb26b1ba8b0ee7bc625601aea3bf726ddd943b2c13a283ac75c336258','dsm':'5376c3059638f814ebc9679732a10bf1ad50dccead02dff67420a52ae60565ae'}
GRID='5d6ed64d2119952c4c559fa1fccbc594b6520fc3ec3ef2fc10be13202c4384fa'
IDS={834919978:'Wicker Man Shop',70689589:'The Burger Kitchen',107259863:'FastTrack'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('dtm','dsm','grid','osm','output'):parser.add_argument('--'+key,required=True)
    a=parser.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    archives={}
    for kind,pin in PINS.items():
        path=Path(getattr(a,kind))
        if path.stat().st_size>100000000 or file_hash(path)!=pin:raise ValueError('Pinned bounded dated archive required')
        archives[kind]=path.read_bytes()
    if file_hash(a.grid)!=GRID:raise ValueError('Pinned datum grid required')
    datadir.append_data_dir(str(Path(a.grid).resolve().parent));group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
    if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:raise ValueError('Best metre-scale transformation required')
    project=group.transformers[0];polygons={}
    for e in json.loads(Path(a.osm).read_text())['elements']:
        if e['type']=='way' and e['id'] in IDS:
            g=Polygon([(p['lon'],p['lat']) for p in e['geometry']])
            if not g.is_valid:raise ValueError('Valid comparison footprint required')
            polygons[e['id']]=transform(project.transform,g)
    if set(polygons)!=set(IDS):raise ValueError('All three comparison outlines required')
    bbox=unary_union(list(polygons.values())).buffer(30).bounds
    survey=crop_pair(archives,bbox,out,'2022','SK0540')
    if (survey['survey_id'],survey['survey_start'],survey['survey_end'])!=('P_10682','20220105','20220105'):raise ValueError('Unexpected dated survey identity')
    rows=[]
    with rasterio.open(out/'ea-national-dtm.tif') as ground,rasterio.open(out/'ea-national-dsm.tif') as surface:
        for identifier,g in polygons.items():
            w=from_bounds(*g.bounds,ground.transform);left,top=math.floor(w.col_off),math.floor(w.row_off);right,bottom=math.ceil(w.col_off+w.width),math.ceil(w.row_off+w.height);window=Window(left,top,right-left,bottom-top)
            values=observations(g,ground.read(1,window=window,masked=True),surface.read(1,window=window,masked=True),ground.window_transform(window))
            rows.append({'reference_id':'osm/way/'+str(identifier),'name':IDS[identifier],**values})
        regions=elevated_regions(ground.read(1,masked=True),surface.read(1,masked=True),ground.transform)
        grid={'crs':ground.crs.to_string(),'shape':list(ground.shape),'transform':list(ground.transform),'bounds':list(ground.bounds),'resolution_m':list(ground.res)}
    tif_hashes={}
    for kind,payload in archives.items():
        import hashlib,io
        with zipfile.ZipFile(io.BytesIO(payload)) as z:tif_hashes[kind]=hashlib.sha256(z.read(survey['archive_files'][kind])).hexdigest()
    report={'status':'dated_survey_observations_only','survey':survey,'grid':grid,'archive_sha256':PINS,'original_raster_sha256':tif_hashes,'crop_sha256':{kind:file_hash(out/f'ea-national-{kind}.tif') for kind in PINS},'datum_grid_sha256':GRID,'osm_sha256':file_hash(a.osm),'horizontal_transform_accuracy_m':project.accuracy,'landmarks':rows,'local_pixel_epoch':'2022-01-05; direct matched survey rasters, no mosaic fallback','accepted_checkpoint_count':0,'registration_verified':False,'world_geometry_additions':0,'limitations':['Survey epoch is established; present-day construction state is not','OSM outlines locate inspection windows and do not identify independent attachment points','Surface elevations are not floor or track rail heights','Original archives differ in byte hash from historical acquisition; current content hashes are separately pinned'],'source_urls':{kind:f'https://environment.data.gov.uk/tiles/collections/survey/national_lidar_programme_{kind}/2022/1/SK0540' for kind in PINS}}
    regions.update(survey_id=survey['survey_id'],survey_date='2022-01-05',crs='EPSG:27700',source_crop_sha256=report['crop_sha256'])
    (out/'elevated-surface-regions.json').write_text(json.dumps(regions,indent=2)+'\n')
    (out/'dated-landmark-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'survey':survey['survey_id'],'date':report['local_pixel_epoch'],'landmarks':rows}))

if __name__=='__main__':main()
