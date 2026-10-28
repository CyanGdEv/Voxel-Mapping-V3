"""Bounded PDOK annual RGB/CIR and native AHN4 height inputs, with source pins."""
import argparse
import io
import json
import math
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import rasterio
import requests
from pyproj import Transformer

from .generation_cycles import atomic_json,file_hash
from .lidar_surface_features import CHANNELS,native_features

RGB='https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0'
CIR='https://service.pdok.nl/hwh/luchtfotocir/wms/v1_0'
AHN='https://service.pdok.nl/rws/ahn/wcs/v1_0'
VERSION='pdok-ahn4-surface-context-v1'
USER_AGENT='VoxelMapper/3.1 (https://github.com/CyanGdEv/Voxel-Mapping-V3)'


def fetch(url,params,limit):
    if url not in (RGB,CIR,AHN):raise ValueError('Known public Dutch source endpoint required')
    payload=bytearray()
    with requests.get(url,params=params,headers={'User-Agent':USER_AGENT},stream=True,timeout=(10,40)) as r:
        r.raise_for_status();request_url=r.url
        for chunk in r.iter_content(65536):
            payload.extend(chunk)
            if len(payload)>limit:raise ValueError('Source response exceeds byte budget')
    return bytes(payload),request_url


def check_capabilities(raw,kind,year=2025):
    if len(raw)>3000000:raise ValueError('Bounded capabilities required')
    root=ET.fromstring(raw)
    if kind=='ahn':
        abstract=' '.join(e.text or '' for e in root.iter() if e.tag.split('}')[-1]=='Abstract')
        ids={e.text for e in root.iter() if e.tag.split('}')[-1]=='CoverageId'}
        if 'versie 4' not in abstract or not {'dsm_05m','dtm_05m'}<=ids:raise ValueError('Explicit AHN4 half-metre source generation required; no automatic latest fallback')
    else:
        layer=str(year)+('_orthoHRIR' if kind=='cir' else '_orthoHR')
        names={e.text for e in root.iter() if e.tag.split('}')[-1]=='Name'}
        if kind not in ('rgb','cir') or year not in (2024,2025,2026) or layer not in names:raise ValueError('Fixed definitive annual high-resolution image layer required')
    return True


def check_grid(bounds,size):
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):raise ValueError('Finite RD bounds required')
    if not isinstance(size,(list,tuple)) or len(size)!=2 or any(type(v) is not int or not 128<=v<=1024 for v in size) or size[0]*size[1]>1048576:raise ValueError('Bounded native image dimensions required')
    x0,y0,x1,y1=bounds
    if not (0<=x0<x1<=300000 and 300000<=y0<y1<=650000):raise ValueError('Dutch RD extent required')
    spacing=[(x1-x0)/size[0],(y1-y0)/size[1]]
    if not all(.049999<=v<=.250001 for v in spacing) or abs(spacing[0]-spacing[1])>1e-7:raise ValueError('Square five-to-25cm image sampling required')
    return spacing[0]


def acquire(bounds,output,capabilities,size=(1024,1024),year=2025,infrared=True):
    spacing=check_grid(bounds,size);out=Path(output);caps=Path(capabilities)
    if out.exists():raise ValueError('Fresh source directory required')
    for kind in ('rgb','ahn')+ (('cir',) if infrared else ()):
        check_capabilities((caps/(kind+'-capabilities.xml')).read_bytes(),kind,year)
    out.mkdir(parents=True)
    for kind in ('rgb','ahn')+ (('cir',) if infrared else ()):shutil.copy2(caps/(kind+'-capabilities.xml'),out/(kind+'-capabilities.xml'))
    requests_log=[]
    for kind,url in [('rgb',RGB)]+([('cir',CIR)] if infrared else []):
        layer=str(year)+('_orthoHRIR' if kind=='cir' else '_orthoHR')
        params={'service':'WMS','request':'GetMap','version':'1.3.0','layers':layer,'styles':'','crs':'EPSG:28992','bbox':','.join(map(str,bounds)),'width':size[0],'height':size[1],'format':'image/jpeg'}
        payload,request_url=fetch(url,params,10000000)
        with Image.open(io.BytesIO(payload)) as im:
            if im.format!='JPEG' or im.size!=tuple(size) or im.mode!='RGB':raise ValueError('Expected source RGB JPEG dimensions required')
            rgb=np.array(im)
            if rgb.std()<2:raise ValueError('Blank or nearly blank image response')
        path=out/('source-image.jpg' if kind=='rgb' else 'infrared.jpg');path.write_bytes(payload);requests_log.append({'kind':kind,'url':request_url,'sha256':file_hash(path),'bytes':len(payload)})
    projected=list(Transformer.from_crs(28992,3857,always_xy=True).transform_bounds(*bounds,densify_pts=21))
    receipt={'version':'pdok-annual-aerial-v1','image_sha256':file_hash(out/'source-image.jpg'),'width':size[0],'height':size[1],
        'grid':{'crs':'EPSG:28992','bounds':list(bounds),'spacing_m':spacing,'pixel_convention':'area edges, centres at half-pixel'},'extent_epsg3857':projected,
        'extent_epsg3857_role':'bounding envelope for geographic indexing only; RGB/height alignment uses the exact RD grid',
        'provider':'PDOK / Het Waterschapshuis / Beeldmateriaal','layer':str(year)+'_orthoHR','capture_year':year,'exact_local_capture_date':None,
        'provider_nominal_resolution_m':[.05,.08] if year>=2025 else [.08],'export_spacing_m':spacing,
        'whole_image_intrinsic_resolution_verified':False,'surveyed_registration_verified':False,
        'license':'CC-BY-4.0','license_url':'https://www.beeldmateriaal.nl/dataroom','attribution':'Beeldmateriaal.nl / Het Waterschapshuis / participating Dutch public authorities',
        'source_request':requests_log[0],'capabilities_sha256':file_hash(out/'rgb-capabilities.xml'),
        'limitations':['Annual orthophoto; local flight day and per-pixel optical resolution are not established by the export grid.','JPEG source compression is retained. No artificial sharpening or super-resolution.','Infrared is a separate CIR visualization, not calibrated reflectance and not a training input.']}
    atomic_json(out/'imagery-receipt.json',receipt)
    # Request native values, never an RGB/greyscale portrayal of height.
    native=[math.floor((bounds[0]-4)*2)/2,math.floor((bounds[1]-4)*2)/2,math.ceil((bounds[2]+4)*2)/2,math.ceil((bounds[3]+4)*2)/2];height_rows={};transforms=[];shapes=[]
    for kind in ('dtm','dsm'):
        params=[('service','WCS'),('version','2.0.1'),('request','GetCoverage'),('coverageId',kind+'_05m'),('subset',f'x({native[0]},{native[2]})'),('subset',f'y({native[1]},{native[3]})'),('format','image/tiff')]
        payload,request_url=fetch(AHN,params,12000000);path=out/(kind+'.tif');path.write_bytes(payload)
        with rasterio.open(path) as ds:
            if ds.crs.to_epsg()!=28992 or ds.count!=1 or ds.res!=(.5,.5) or ds.transform.b or ds.transform.d or ds.transform.e!=-.5 or ds.width*ds.height>1000000 or ds.dtypes[0] not in ('float32','float64'):raise ValueError('Native half-metre float-valued AHN grid required')
            values=ds.read(1,masked=True);valid=~np.ma.getmaskarray(values)&np.isfinite(values.filled(np.nan))
            if valid.sum()<4 or np.any(np.abs(values.filled(0)[valid])>500):raise ValueError('Valid metre-valued AHN elevations required')
            transforms.append(ds.transform);shapes.append(values.shape);height_rows[kind]={'file':path.name,'sha256':file_hash(path),'url':request_url,'valid_fraction':float(valid.mean()),'transform':list(ds.transform),'shape':list(values.shape)}
    if transforms[0]!=transforms[1] or shapes[0]!=shapes[1]:raise ValueError('Matched native AHN terrain/surface grids required')
    height={'version':'ahn4-native-pair-v1','provider':'AHN via PDOK','generation':'AHN4','capture_period':[2020,2022],'exact_local_capture_date':None,'native_resolution_m':.5,'crs':'EPSG:28992','vertical_datum':'NAP','height_units':'metres','license':'CC0-1.0','license_evidence':'AHN WCS capabilities AccessConstraints','capabilities_sha256':file_hash(out/'ahn-capabilities.xml'),'products':height_rows,'gap_policy':'Preserve every source no-data cell; do not interpolate','surface_definition':'AHN4 squared-IDW surface raster from all returns except classified water; terrain from ground-class points','epoch_match_to_rgb':False}
    atomic_json(out/'height-receipt.json',height);atomic_json(out/'acquisition.json',{'version':'pdok-ahn-source-acquisition-v1','image':receipt,'height':height,'requests':requests_log});return receipt,height


def align(receipt,pair_directory,output):
    root=Path(pair_directory);out=Path(output);source=json.loads((root/'height-receipt.json').read_text());grid=receipt.get('grid',{})
    if out.exists() or source.get('version')!='ahn4-native-pair-v1' or source['generation']!='AHN4' or source['native_resolution_m']!=.5 or source['vertical_datum']!='NAP' or grid.get('crs')!='EPSG:28992':raise ValueError('Fresh native RD-aligned AHN4 features required')
    size=(receipt['width'],receipt['height']);check_grid(grid['bounds'],size);arrays=[];masks=[];transforms=[]
    for kind in ('dtm','dsm'):
        if source['products'][kind]['file']!=kind+'.tif':raise ValueError('Known local AHN raster filename required')
        p=root/source['products'][kind]['file']
        if file_hash(p)!=source['products'][kind]['sha256']:raise ValueError('Native AHN source changed')
        with rasterio.open(p) as ds:
            if ds.crs.to_epsg()!=28992 or ds.res!=(.5,.5) or ds.count!=1 or ds.width*ds.height>1000000:raise ValueError('Bounded native AHN raster required')
            values=ds.read(1,masked=True);arrays.append(values.filled(np.nan));masks.append(~np.ma.getmaskarray(values));transforms.append(ds.transform)
    if transforms[0]!=transforms[1] or arrays[0].shape!=arrays[1].shape:raise ValueError('AHN native pair grid differs')
    native=native_features(arrays[0],arrays[1],masks[0],masks[1],resolution=.5);b=grid['bounds'];y,x=np.indices((size[1],size[0]));xx=b[0]+(x+.5)/size[0]*(b[2]-b[0]);yy=b[3]-(y+.5)/size[1]*(b[3]-b[1]);t=transforms[0];col=np.floor((xx-t.c)/t.a).astype(int);row=np.floor((yy-t.f)/t.e).astype(int)
    if t.a!=.5 or t.e!=-.5 or t.b or t.d or np.any(row<0) or np.any(col<0) or np.any(row>=native.shape[0]) or np.any(col>=native.shape[1]):raise ValueError('AHN native crop must cover exact RGB pixel centres')
    features=native[row,col];out.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(out,features=features)
    meta={'version':VERSION,'channels':CHANNELS,'image_sha256':receipt['image_sha256'],'features_sha256':file_hash(out),'shape':list(features.shape),
        'source_height_receipt_sha256':file_hash(root/'height-receipt.json'),'dtm_sha256':source['products']['dtm']['sha256'],'dsm_sha256':source['products']['dsm']['sha256'],
        'generation':'AHN4','capture_period':[2020,2022],'native_resolution_m':.5,'horizontal_crs':'EPSG:28992','vertical_datum':'NAP','height_units':'metres','raw_point_cloud_used':False,
        'relative_height_only':True,'cross_country_absolute_heights_combined':False,'resampling':'Nearest native half-metre cell; no interpolation or no-data filling',
        'roughness_kernel_cells':7,'roughness_window_width_m':3.5,'valid_fraction':float((features[:,:,3]>.5).mean()),'outside_native_raster_fraction':0.,'epoch_match_to_rgb':False,
        'features_are_labels':False,'limitations':['Native half-metre source detail is not eight-centimetre height measurement.','AHN4 and 2025 aerial epochs differ; changed objects are not inferred as ground truth.','NAP absolute heights are never mixed with UK ODN heights; learning uses relative height and slope.']}
    atomic_json(out.with_suffix('.json'),meta);return meta


def validate_context_receipt(receipt):
    """Only the explicit relative-height/NAP processor may join UK inputs."""
    if receipt.get('version')!=VERSION or receipt.get('channels')!=CHANNELS or receipt.get('generation')!='AHN4' or receipt.get('native_resolution_m')!=.5 or receipt.get('vertical_datum')!='NAP' or receipt.get('horizontal_crs')!='EPSG:28992' or receipt.get('height_units')!='metres' or receipt.get('relative_height_only') is not True or receipt.get('cross_country_absolute_heights_combined') is not False or receipt.get('features_are_labels') is not False:
        raise ValueError('Explicit source-pinned relative AHN4/NAP context required')
    return True


def coarse_rgb(rgb,spacing_m=.08,target_m=.25):
    """Controlled information-loss comparison on the unchanged geographic grid."""
    if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3 or rgb.shape[0]*rgb.shape[1]>1048576 or not .05<=spacing_m<target_m<=.5:raise ValueError('Bounded source RGB and coarser sampling required')
    h,w=rgb.shape[:2];small=(max(1,round(w*spacing_m/target_m)),max(1,round(h*spacing_m/target_m)))
    result=np.array(Image.fromarray(rgb).resize(small,Image.Resampling.BOX).resize((w,h),Image.Resampling.BILINEAR))
    return result,{'version':'controlled-rgb-coarsening-v1','source_spacing_m':spacing_m,'requested_coarse_spacing_m':target_m,'coarse_dimensions':list(small),'actual_coarse_spacing_m_xy':[w*spacing_m/small[0],h*spacing_m/small[1]],'downsample':'BOX area average','return_to_original_grid':'bilinear','labels_and_geographic_extent_unchanged':True,'adds_optical_information':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--longitude',type=float,required=True);parser.add_argument('--latitude',type=float,required=True);parser.add_argument('--output',required=True);parser.add_argument('--capabilities');parser.add_argument('--year',type=int,choices=(2024,2025,2026),default=2025);parser.add_argument('--spacing',type=float,choices=(.05,.08,.125,.25),default=.08);parser.add_argument('--size',type=int,default=1024);parser.add_argument('--no-infrared',action='store_true');args=parser.parse_args()
    x,y=Transformer.from_crs(4326,28992,always_xy=True).transform(args.longitude,args.latitude);half=args.size*args.spacing/2;x0=round((x-half)/args.spacing)*args.spacing;y0=round((y-half)/args.spacing)*args.spacing;bounds=[x0,y0,x0+2*half,y0+2*half];check_grid(bounds,(args.size,args.size));out=Path(args.output)
    if args.capabilities:caps=Path(args.capabilities)
    else:
        caps=out.parent/(out.name+'-capabilities')
        if caps.exists():raise ValueError('Fresh capabilities directory or an explicit retained directory required')
        caps.mkdir(parents=True)
        for kind,url in [('rgb',RGB),('ahn',AHN)]+([] if args.no_infrared else [('cir',CIR)]):
            raw,_=fetch(url,{'service':'WCS' if kind=='ahn' else 'WMS','request':'GetCapabilities'},3000000);check_capabilities(raw,kind,args.year);(caps/(kind+'-capabilities.xml')).write_bytes(raw)
    image,height=acquire(bounds,out,caps,(args.size,args.size),args.year,not args.no_infrared);context=align(image,out,out/'height-features.npz');print(json.dumps({'image_sha256':image['image_sha256'],'height_generation':height['generation'],'valid_height_fraction':context['valid_fraction'],'output':str(out)}))
