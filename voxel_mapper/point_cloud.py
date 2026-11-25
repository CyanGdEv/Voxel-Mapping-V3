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


def ground_intensity_grid(cloud, bounds, output, *, max_points=15_000_000):
    """Mean raw class-2 LAS intensity on a native 1m BNG grid; no interpolation.

    Complements the PDAL exporter when only the existing laspy crop is available.
    Averaging preserves the raw uint16 intensity scale, not a calibrated material.
    """
    import rasterio
    from rasterio.transform import from_origin
    x0,y0,x1,y1 = bounds
    if any(not np.isfinite(v) or int(v) != v for v in bounds) or not x0 < x1 or not y0 < y1:
        raise ValueError('Integer metre raster bounds required')
    width,height = int(x1-x0),int(y1-y0)
    if width*height > 4_000_000:
        raise ValueError('Intensity grid pixel budget exceeded')
    sums = np.zeros(width*height,np.float64)
    counts = np.zeros(width*height,np.uint32)
    scanned = 0
    with laspy.open(cloud) as reader:
        if not is_bng(reader.header.parse_crs()) or reader.header.point_count > max_points:
            raise ValueError('Bounded BNG point crop required')
        for points in reader.chunk_iterator(500_000):
            scanned += len(points)
            if scanned > max_points:
                raise ValueError('Intensity point budget exceeded')
            x,y = np.asarray(points.x),np.asarray(points.y)
            valid = (np.asarray(points.classification)==2) & np.isfinite(x) & np.isfinite(y) & (x>=x0) & (x<x1) & (y>y0) & (y<=y1)
            col = np.floor(x[valid]-x0).astype(int)
            row = np.floor(y1-y[valid]).astype(int)
            index = row*width+col
            np.add.at(sums,index,np.asarray(points.intensity)[valid])
            np.add.at(counts,index,1)
        if scanned != reader.header.point_count:
            raise ValueError('Truncated point crop')
    values = np.full(width*height,-9999,np.float32)
    known = counts > 0
    values[known] = sums[known]/counts[known]
    if not known.any():
        raise ValueError('No class-2 intensity observations in raster bounds')
    with rasterio.open(output,'w',driver='GTiff',width=width,height=height,count=1,
                       dtype='float32',crs='EPSG:27700',transform=from_origin(x0,y1,1,1),
                       nodata=-9999,compress='deflate') as dest:
        dest.write(values.reshape(height,width),1)
    return {'encoding':'raw_las_uint16','aggregation':'arithmetic mean of observed class-2 intensities per 1m cell',
            'observed_cells':int(known.sum()),'total_cells':int(known.size),
            'ground_returns':int(counts.sum()),'source_points_scanned':scanned,
            'sha256':hashlib.sha256(Path(output).read_bytes()).hexdigest(),
            'policy':'Unknown cells remain nodata; no intensity-to-material inference or interpolation.'}


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


def summarize_cell_returns(cloud, cells, grid_transform, *, expected_sha256,
                           max_scan_points=15_000_000, max_retained_points=250_000):
    """Observe requested native metre cells without interpolation or raster labels.

    Duplicate XYZ/class/return observations are deduplicated. Counts and quadrant
    coverage describe one survey lineage, not independent evidence sources.
    """
    from affine import Affine
    grid=Affine(*grid_transform);inverse=~grid
    axes=np.array([[grid.a,grid.b],[grid.d,grid.e]])
    if not np.allclose(axes.T@axes,np.eye(2),atol=1e-9):raise ValueError('Metre native grid required')
    wanted={(int(c['x']),int(c['z'])) for c in cells}
    if not wanted or len(wanted)>10_000:raise ValueError('Cell budget exceeded')
    with cloud.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=expected_sha256:raise ValueError('Point-cloud identity mismatch')
    x0,x1=min(x for x,z in wanted),max(x for x,z in wanted)+1
    z0,z1=min(z for x,z in wanted),max(z for x,z in wanted)+1
    corners=[grid*p for p in [(x0,z0),(x1,z0),(x0,z1),(x1,z1)]]
    lo=np.min(corners,axis=0);hi=np.max(corners,axis=0)
    groups={key:[] for key in wanted};discarded=collections.Counter();scanned=raw_retained=excluded_flags=0
    with laspy.open(cloud) as reader:
        if not is_bng(reader.header.parse_crs()):raise ValueError('Verified native BNG point-cloud CRS required')
        if not np.isfinite(reader.header.scales).all() or not np.all(reader.header.scales>0) or not np.isfinite(reader.header.offsets).all():raise ValueError('Invalid point coordinate scales/offsets')
        if reader.header.point_count>max_scan_points:raise ValueError('Point scan budget exceeded')
        for chunk in reader.chunk_iterator(500_000):
            scanned+=len(chunk)
            if scanned>max_scan_points:raise ValueError('Point scan budget exceeded')
            e,n,h=np.asarray(chunk.x),np.asarray(chunk.y),np.asarray(chunk.z)
            keep=(e>=lo[0])&(e<=hi[0])&(n>=lo[1])&(n<=hi[1])&np.isfinite(h)
            withheld=np.asarray(chunk.withheld,dtype=bool);synthetic=np.asarray(chunk.synthetic,dtype=bool)
            classification=np.asarray(chunk.classification);returns=np.asarray(chunk.return_number);totals=np.asarray(chunk.number_of_returns)
            for i in np.flatnonzero(keep):
                fx,fz=inverse*(float(e[i]),float(n[i]));fx,fz=round(fx,8),round(fz,8)
                key=(int(np.floor(fx)),int(np.floor(fz)))
                if key not in wanted:continue
                raw_retained+=1
                if raw_retained>max_retained_points:raise ValueError('Retained point budget exceeded')
                if withheld[i] or synthetic[i]:excluded_flags+=1;discarded[key]+=1;continue
                cls=int(classification[i])
                if cls in (7,18) or not 1<=int(returns[i])<=int(totals[i])<=15:excluded_flags+=1;discarded[key]+=1;continue
                groups[key].append((int(chunk.X[i]),int(chunk.Y[i]),int(chunk.Z[i]),cls,
                   int(returns[i]),int(totals[i]),float(h[i]),fx-key[0],fz-key[1]))
        if scanned!=reader.header.point_count:raise ValueError('Incomplete point scan')
        scales=reader.header.scales.tolist()
    rows=[]
    for (x,z),points in sorted(groups.items()):
        unique={p[:6]:p for p in points};values=list(unique.values())
        ground=[p for p in values if p[3]==2];first=[p for p in ground if p[4]==1]
        quadrants={int(p[7]>=.5)+2*int(p[8]>=.5) for p in first}
        heights=np.array([p[6] for p in values]);gh=np.array([p[6] for p in ground])
        med=float(np.median(gh)) if len(gh) else None
        classes=collections.Counter(p[3] for p in values)
        rows.append({'x':x,'z':z,'observed_points':len(points),'unique_returns':len(values),
            'excluded_points':discarded[x,z],'class_counts':dict(classes),'ground_returns':len(ground),'first_ground_returns':len(first),
            'first_ground_quadrants':sorted(quadrants),
            'first_ground_x_span_m':max(p[7] for p in first)-min(p[7] for p in first) if first else 0.,
            'first_ground_z_span_m':max(p[8] for p in first)-min(p[8] for p in first) if first else 0.,'ground_z_median':med,
            'ground_z_range':float(np.ptp(gh)) if len(gh) else None,
            'all_z_min':float(heights.min()) if len(heights) else None,
            'all_z_max':float(heights.max()) if len(heights) else None,
            'observed_clear_ground':False})
    from .ground_surface import direct_ground_support
    for row in rows:row['observed_clear_ground']=direct_ground_support(row)
    return {'schema':'classified-cell-return-evidence-v1','source_sha256':actual,'scanned_points':scanned,
            'raw_retained_points':raw_retained,'excluded_flagged_or_noise_points':excluded_flags,
            'coordinate_scales_m':scales,'cells':rows,
            'policy':'Direct observed returns only, no interpolated 0.5m survey or independent source votes. Four first-ground-return quadrants, >=0.5m first-ground span in both axes, >=4 first ground returns, only classes1/2 and <=0.15m vertical spread required for observed clear ground; excluded/noise returns also withhold support. Not calibrated confidence or automatic edit acceptance.'}
