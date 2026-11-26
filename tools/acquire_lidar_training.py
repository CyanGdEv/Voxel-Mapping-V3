"""Discover/cache matched EA survey evidence and produce a training catalog."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import zipfile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pyproj import Transformer
from shapely.geometry import box, mapping

from voxel_mapper.acquisition import ensure_ea_grid
from voxel_mapper.survey import BASE, METADATA, select_pair, crop_pair, describe_pair
from voxel_mapper.point_cloud import select_cloud, crop_archive, ground_intensity_grid


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def cached_archive_matches(path, year, tile):
    """Only adopt legacy cache names when the native member identifies this tile/year."""
    try:
        with zipfile.ZipFile(path) as archive:
            return any(tile+'_' in member and re.search('_'+year+r'\d{4}_\d{8}\.(?:tif|laz)$',member)
                       for member in archive.namelist())
    except (OSError,zipfile.BadZipFile):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-bounds',type=int,nargs=4,required=True,help='BNG integer metre bounds')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--catalogue',type=Path,help='Reuse an actual EA catalogue response')
    parser.add_argument('--park-id',required=True)
    parser.add_argument('--gis-catalog',type=Path)
    args = parser.parse_args()
    x0,y0,x1,y1 = args.native_bounds
    if not x0 < x1 or not y0 < y1 or (x1-x0)*(y1-y0)>4_000_000:
        parser.error('Use ordered BNG bounds covering at most four million cells')
    receipt_path = args.output/'lidar-evidence.json'
    previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if previous and previous['bounds_bng'] != args.native_bounds:
        raise ValueError('Existing evidence has different bounds; use a fresh output directory')
    args.output.mkdir(parents=True,exist_ok=True)
    args.cache.mkdir(parents=True,exist_ok=True)
    if args.catalogue:
        catalogue = json.loads(args.catalogue.read_text())
    else:
        grid = ensure_ea_grid(args.output)
        if grid['status'] != 'downloaded':
            raise ValueError('OSTN15 datum grid unavailable')
        tf = Transformer.from_crs(27700,4326,always_xy=True,allow_ballpark=False)
        bounds = tf.transform_bounds(x0,y0,x1,y1,densify_pts=21)
        response = requests.post(BASE+'/search',json=mapping(box(*bounds)),
                                 headers={'Content-Type':'application/geo+json'},timeout=(10,45))
        response.raise_for_status()
        if len(response.content)>2_000_000:
            raise ValueError('Survey catalogue byte budget exceeded')
        catalogue = response.json()
    (year,tile),urls = select_pair(catalogue)
    cloud_url = f'{BASE}/national_lidar_programme_point_cloud/{year}/1/{tile}'
    if sum(row.get('uri') == cloud_url for row in catalogue['results']) != 1:
        raise ValueError('No unique advertised matched point-cloud download')
    sources = {**{f'national_lidar_programme_{kind}':url for kind,url in urls.items()},
               'national_lidar_programme_point_cloud':cloud_url}
    def download(item):
        name,url = item
        path = args.cache/f'{name}-{year}-{tile}.zip'
        legacy = args.cache/(name+'.zip')
        if not path.exists() and cached_archive_matches(legacy,year,tile):
            path = legacy
        cached = cached_archive_matches(path,year,tile)
        if not cached:
            temporary = path.with_suffix('.partial')
            try:
                with requests.Session() as session:
                    session.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=.5,
                        status_forcelist=(429,500,502,503,504),respect_retry_after_header=False)))
                    with session.get(url,stream=True,timeout=(10,90)) as response:
                        response.raise_for_status()
                        count = 0
                        with temporary.open('wb') as dest:
                            for chunk in response.iter_content(1_000_000):
                                count += len(chunk)
                                if count>768_000_000:
                                    raise ValueError('Survey archive exceeds 768 MB budget')
                                dest.write(chunk)
                if not zipfile.is_zipfile(temporary):
                    raise ValueError('Survey response is not a ZIP archive')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return name,{'path':path,'url':url,'sha256':digest(path),'bytes':path.stat().st_size,'cache_hit':cached}
    with ThreadPoolExecutor(max_workers=2) as workers:
        archives = dict(workers.map(download,sources.items()))
    if previous and any(previous['archives'].get(name,{}).get('sha256') != details['sha256']
                        for name,details in archives.items()):
        raise ValueError('Survey archive changed; preserve old evidence and use a fresh output directory')
    (args.output/'national-survey-catalogue.json').write_text(json.dumps(catalogue,indent=2))
    payload = {kind:archives['national_lidar_programme_'+kind]['path'].read_bytes() for kind in ('dtm','dsm')}
    survey = crop_pair(payload,args.native_bounds,args.output,year,tile)
    terrain,source = describe_pair(payload,survey,args.output,year,urls,{'method':'native BNG integer bounds; no reprojection'})
    selection = select_cloud(catalogue,source)
    cloud_report = args.output/'classified-cloud-report.json'
    cloud = args.output/'ea-point-cloud.las'
    details = json.loads(cloud_report.read_text()) if cloud_report.exists() else {}
    if not (details.get('bounds') == args.native_bounds and details.get('selection') == selection
            and cloud.exists() and digest(cloud) == details.get('sha256')):
        cloud,details = crop_archive(archives['national_lidar_programme_point_cloud']['path'],selection,args.native_bounds,args.output)
        details.update(bounds=args.native_bounds,selection=selection)
        cloud_report.write_text(json.dumps(details,indent=2))
    intensity = ground_intensity_grid(cloud,args.native_bounds,args.output/'ground-intensity.tif')
    (args.output/'intensity-report.json').write_text(json.dumps(intensity,indent=2))
    meta = {'source_id':f'ea-national-{year}-{survey["survey_id"]}', 'license':'OGL-3.0',
            'observed_date':datetime.strptime(survey['survey_start'],'%Y%m%d').date().isoformat(),
            'vertical_units':'m','vertical_datum':'ODN'}
    park = {'dtm':{**meta,'path':'ea-national-dtm.tif'},'dsm':{**meta,'path':'ea-national-dsm.tif'},
            'intensity':{**meta,'path':'ground-intensity.tif','encoding':'raw_las_uint16','aggregation':intensity['aggregation']}}
    if args.gis_catalog:
        original = json.loads(args.gis_catalog.read_text())['parks'][args.park_id]
        if original.get('gis'):
            park['gis'] = os.path.relpath(args.gis_catalog.resolve().parent/original['gis'],args.output.resolve())
    (args.output/'training-catalog.json').write_text(json.dumps({'parks':{args.park_id:park}},indent=2))
    report = {'schema':'voxel-ea-training-acquisition-v1','bounds_bng':args.native_bounds,
              'retrieved_at':datetime.now(timezone.utc).isoformat(),'survey':survey,
              'license':'OGL-3.0','metadata_url':METADATA,'lineage_family':'environment-agency-P_'+survey['survey_id'].removeprefix('P_'),
              'attribution':'Contains Environment Agency information © Environment Agency and/or database right',
              'horizontal_crs':'EPSG:27700','vertical_datum':'ODN',
              'archives':{k:{a:str(b) if isinstance(b,Path) else b for a,b in v.items()} for k,v in archives.items()},
              'classified_cloud':details,'intensity':intensity,'world_blocks_changed':0,
              'policy':'Shared EA survey lineage; contextual evidence only. Published intensity raster is not substituted for verified raw LAS intensity.'}
    (args.output/'lidar-evidence.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'survey':survey,'retained_points':details['retained_points'],'intensity_cells':intensity['observed_cells']},indent=2))


if __name__ == '__main__':
    main()
