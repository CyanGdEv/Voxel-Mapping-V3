"""Bounded automatic acquisition of survey-matched raw LiDAR evidence.

Raw returns are not semantic meshes, materials, interiors or bathymetry.
"""
import collections
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path

import laspy
from lazrs import LazrsError
import numpy as np
import requests
from pyproj.transformer import TransformerGroup
from pyproj import Transformer, CRS
from shapely import points as make_points
from shapely.geometry import shape
from shapely.strtree import STRtree

from .acquisition import USER_AGENT
from .survey import BASE, METADATA


def is_bng(crs):
    if crs is None or not crs.is_projected:
        return False
    if crs.to_epsg()==27700:
        return True
    # EA's actual WKT rounds the scale factor to 0.999601272; PROJ may
    # decline to resolve that to EPSG even though the header declares 27700.
    # Require explicit authority, the OSGB36 base CRS, metre units and the
    # complete expected projection/ellipsoid; tolerate only that rounding.
    if crs.to_json_dict().get('id')!={'authority':'EPSG','code':27700} or crs.geodetic_crs.to_json_dict().get('id')!={'authority':'EPSG','code':4277}:
        return False
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        actual,expected=crs.to_dict(),CRS.from_epsg(27700).to_dict()
    if set(actual)!=set(expected):return False
    return all(abs(actual[k]-expected[k])<=1e-9 if k=='k' else actual[k]==expected[k] for k in expected)


def select_cloud(catalogue, terrain_source):
    if catalogue.get('count')!=len(catalogue.get('results',[])) or catalogue.get('count',0)>2000:
        raise ValueError('Incomplete or oversized point-cloud catalogue')
    survey=terrain_source.get('survey',{})
    if not all(survey.get(k) for k in ('survey_id','survey_start','survey_end')):
        raise ValueError('Dated terrain survey identity required')
    match=re.fullmatch(re.escape(BASE)+r'/national_lidar_programme_dtm/(20\d{2})/1/([A-Z]{2}\d{4})',terrain_source['url'])
    if not match:
        raise ValueError('Matched National LIDAR terrain tile required')
    year,tile=match.groups()
    url=f'{BASE}/national_lidar_programme_point_cloud/{year}/1/{tile}'
    found=[e for e in catalogue['results'] if e['product']['id']=='national_lidar_programme_point_cloud'
           and e['year']['id']==year and e['resolution']['id']=='1' and e['tile']['id']==tile]
    if len(found)!=1 or found[0]['uri']!=url:
        raise ValueError('Unique advertised survey-matched point-cloud URI required')
    filename=f"{tile}_{survey['survey_id']}_{survey['survey_start']}_{survey['survey_end']}.laz"
    return {'url':url,'filename':filename,'survey':survey,'year':year,'tile':tile}


def crop_archive(archive_path, selection, bounds, output, max_scan_points=150_000_000,
                 max_retained_points=15_000_000):
    path=output/'ea-point-cloud.las'
    scanned,retained=0,0
    classes=collections.Counter()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries=archive.infolist()
            if len(entries)!=1 or entries[0].filename!=selection['filename'] or entries[0].file_size>2_000_000_000:
                raise ValueError('One bounded survey-identity-matched LAZ file required')
            with archive.open(entries[0]) as stream, laspy.open(stream) as reader:
                header=reader.header
                crs=header.parse_crs()
                if not is_bng(crs):
                    raise ValueError('Point cloud must explicitly declare EPSG:27700 metre coordinates')
                if header.point_count>max_scan_points:
                    raise ValueError('Point-cloud scan budget exceeded')
                if not np.all(np.isfinite(header.scales)) or not np.all(header.scales>0):
                    raise ValueError('Invalid point-cloud scales')
                if not (header.mins[0]<=bounds[0]<bounds[2]<=header.maxs[0] and
                        header.mins[1]<=bounds[1]<bounds[3]<=header.maxs[1]):
                    raise ValueError('Requested bounds not covered by point-cloud header extent')
                with laspy.open(path,mode='w',header=copy.deepcopy(header)) as writer:
                    for points in reader.chunk_iterator(500_000):
                        scanned+=len(points)
                        if scanned>max_scan_points:
                            raise ValueError('Point-cloud scan budget exceeded')
                        x,y,z=np.asarray(points.x),np.asarray(points.y),np.asarray(points.z)
                        mask=(x>=bounds[0])&(x<=bounds[2])&(y>=bounds[1])&(y<=bounds[3])&np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
                        sub=points[mask]
                        retained+=len(sub)
                        if retained>max_retained_points:
                            raise ValueError('Point-cloud retained-point budget exceeded')
                        if len(sub):
                            writer.write_points(sub)
                            labels,counts=np.unique(np.asarray(sub.classification),return_counts=True)
                            classes.update({int(k):int(v) for k,v in zip(labels,counts)})
                if scanned!=header.point_count or not retained:
                    raise ValueError('Truncated point cloud or no finite points in requested bounds')
        with path.open('rb') as stream:
            checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        return path,{'scanned_points':scanned,'retained_points':retained,'classifications':dict(classes),
                     'sha256':checksum,'crs':'EPSG:27700','units':'m','vertical_datum':'ODN',
                     'vertical_datum_basis':'EA published dataset declaration; header horizontal CRS checked',
                     'scope':'observed returns only; no semantic geometry, interpolation, floor or lakebed inference'}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def acquire_point_cloud(bounds, output, terrain_source):
    evidence={'provider':'ea-national-point-cloud','status':'unavailable','geometry_use':'classified_building_returns'}
    catalogue_path=output/'national-survey-catalogue.json'
    if terrain_source.get('vertical_datum')!='ODN' or not terrain_source.get('survey') or not catalogue_path.exists():
        evidence.update(status='not_supported',reason='Requires the automatically acquired matched dated terrain catalogue and ODN datum')
        return None,None,evidence
    archive_path=output/'ea-point-cloud-download.zip'
    try:
        selection=select_cloud(json.loads(catalogue_path.read_text()),terrain_source)
        group=TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
        if not group.best_available or not group.transformers or not 0<=group.transformers[0].accuracy<=1:
            raise ValueError('Best metre-scale horizontal transformation required')
        native=group.transformers[0].transform_bounds(*bounds,densify_pts=21)
        downloaded=0
        with requests.get(selection['url'],headers={'User-Agent':USER_AGENT},stream=True,timeout=(10,60)) as response:
            response.raise_for_status()
            with archive_path.open('wb') as stream:
                for chunk in response.iter_content(1_000_000):
                    downloaded+=len(chunk)
                    if downloaded>2_000_000_000:
                        raise ValueError('Point-cloud download exceeds 2 GB disk budget')
                    stream.write(chunk)
        with archive_path.open('rb') as stream:
            archive_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        path,details=crop_archive(archive_path,selection,native,output)
        source={'id':'ea-point-cloud','url':selection['url'],'metadata_url':METADATA,'license':'OGL-UK-3.0',
                'attribution':'Contains Environment Agency information © Environment Agency and/or database right',
                'survey':selection['survey'],'archive_sha256':archive_hash,'archive_bytes':downloaded,**details}
        source['coordinate_transform']={'best_available':True,'accuracy_m':group.transformers[0].accuracy}
        evidence.update(status='downloaded',selected=source)
        return {'path':str(path.resolve()),'source_id':source['id'],'units':'m','vertical_datum':'ODN',
                'crs':'EPSG:27700','geometry_use':'classified_building_returns'},source,evidence
    except (ValueError,KeyError,TypeError,OSError,RuntimeError,EOFError,requests.RequestException,zipfile.BadZipFile,laspy.errors.LaspyException,LazrsError) as error:
        evidence['reason']=str(error)
        return None,None,evidence
    finally:
        archive_path.unlink(missing_ok=True)


def building_returns(config, accepted_features, local_crs, terrain, resolution,
                     max_voxels=500_000, max_points=15_000_000):
    """Observed class-6 cells inside accepted footprints; no solid extrusion."""
    report={'method':'classified_point_surface','status':'unavailable','minimum_returns_per_voxel':2,
            'warnings':['Source building classification and footprint/survey epoch alignment are unverified',
                        'Materials are generic; unseen walls, floors, interiors and gaps are not inferred']}
    buildings=[f for f in accepted_features if f['properties'].get('kind')=='building' and
               shape(f['geometry']).geom_type in ('Polygon','MultiPolygon')]
    if not buildings:
        report['reason']='No accepted building footprints';return [],report
    tree=STRtree([shape(f['geometry']) for f in buildings])
    projector=Transformer.from_crs(27700,local_crs,always_xy=True)
    cells=collections.Counter();scanned=0;ambiguous=0;ground_cache={}
    with laspy.open(config['path']) as reader:
        if not is_bng(reader.header.parse_crs()) or reader.header.point_count>max_points:
            raise ValueError('Invalid point-cloud crop CRS or point budget')
        for chunk in reader.chunk_iterator(500_000):
            scanned+=len(chunk)
            if scanned>max_points:raise ValueError('Point-cloud geometry scan budget exceeded')
            mask=(np.asarray(chunk.classification)==6)&(~np.asarray(chunk.withheld,dtype=bool))&(~np.asarray(chunk.synthetic,dtype=bool))
            subset=chunk[mask]
            if not len(subset):continue
            px,pz=projector.transform(np.asarray(subset.x),np.asarray(subset.y))
            py=np.asarray(subset.z)
            query=tree.query(make_points(px,pz),predicate='within')
            if not query.size:continue
            identities,counts=np.unique(query[0],return_counts=True)
            ambiguous+=int(np.count_nonzero(counts>1))
            unique=set(map(int,identities[counts==1]))
            for index,building in zip(*query):
                if int(index) not in unique or not np.isfinite([px[index],py[index],pz[index]]).all():continue
                x,z=int(np.floor(px[index]/resolution)),int(np.floor(pz[index]/resolution))
                if (x,z) not in ground_cache:
                    ground_cache[x,z]=terrain.sample((x+.5)*resolution,(z+.5)*resolution)
                ground=ground_cache[x,z]
                if ground is None or not -.5<=py[index]-ground<=120:continue
                cells[int(building),x,int(np.floor(py[index]/resolution)),z]+=1
                if len(cells)>max_voxels:raise ValueError('Point-cloud occupied-cell budget exceeded')
    if scanned!=reader.header.point_count:raise ValueError('Truncated point-cloud geometry crop')
    rows=[];feature_counts=collections.Counter()
    for (building,x,y,z),returns in sorted(cells.items()):
        if returns<2:continue
        fid=buildings[building]['id'];feature_counts[fid]+=1
        rows.append({'x':x,'y':y,'z':z,'kind':'structure','material':'stone_bricks','feature':fid,
                     'source':config['source_id'],'elevation_source':config['source_id'],
                     'geometry_method':'classified_point_surface','observed_returns':returns})
    report.update(status='observed_partial_surfaces' if rows else 'no_eligible_surfaces',scanned_points=scanned,
                  occupied_voxels=len(rows),ambiguous_footprint_points=ambiguous,
                  single_return_cells_omitted=sum(v<2 for v in cells.values()),features=dict(feature_counts))
    return rows,report
