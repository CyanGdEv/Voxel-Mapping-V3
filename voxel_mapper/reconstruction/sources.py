"""Adapters reuse retained data; acquisition stays with the existing providers."""
import hashlib,json
from pathlib import Path
from pyproj import CRS,Transformer
from shapely.geometry import shape,mapping
from shapely.ops import transform
from .model import Feature,EvidenceMissing
from ..transport import width_metres


def evidence(value,source,status='documented'):
    return {'value':value,'source':source,'status':status}


def geojson_adapter(data,source):
    features=[]
    for item in data.get('features',[]):
        p=item.get('properties',{});family=p.get('reconstruction_family')
        if not family:
            family={'path':'paving','plaza':'paving','sidewalk':'paving','road':'paving','queue':'paving','building':'building_shell','barrier':'wall'}.get(p.get('kind'))
        if not family:family='unclassified'
        parameters=dict(p.get('reconstruction_parameters',{}))
        for key,target in [('surface','surface'),('minecraft_material','material'),('height_m','height_m'),('height','height_m'),('width_m','width_m'),('width','width_m')]:
            if key in p and target not in parameters:
                value=width_metres(p[key]) if target.endswith('_m') else p[key]
                parameters[target]=evidence(value,source.id)
        features.append(Feature(str(item.get('id') or p.get('id') or f'{source.id}/{len(features)}'),family,item['geometry'],source.id,parameters,
                                {'tags':p,'source_kind':source.kind}))
    return features


def osm_adapter(data,source):
    # Reuse the existing relation/hole parser; add explicitly mapped ride lines
    # and barriers that the legacy extrusion pipeline deliberately excludes.
    from ..cli import parse_osm
    collection,_=parse_osm(data);features=geojson_adapter(collection,source);represented={f.id for f in features}
    for element in data.get('elements',[]):
        if element.get('type')!='way' or len(element.get('geometry',[]))<2:continue
        tags=element.get('tags',{});family=None
        if tags.get('roller_coaster')=='track':family='track'
        elif tags.get('aerialway')=='gondola':family='cable'
        elif tags.get('railway')=='monorail':family='beam'
        elif tags.get('barrier') in ('fence','wall','retaining_wall'):family='wall'
        if not family:continue
        identifier='osm/'+str(element['id'])
        if identifier in represented:continue
        features.append(Feature(identifier,family,{'type':'LineString','coordinates':[[p['lon'],p['lat']] for p in element['geometry']]},source.id,{},
                                {'tags':tags,'source_kind':'osm','needs':'3D route and material evidence' if family in ('track','cable','beam') else 'wall height and material evidence'}))
    return features


def planning_adapter(data,source):
    from ..planning_geometry import physical_features
    if CRS.from_user_input(source.crs)!=CRS.from_epsg(4326):raise ValueError('Existing registered planning adapter expects WGS84 polygons')
    collection,decisions=physical_features(data['records'],{source.id:source.__dict__},data['bbox'],source.vertical_datum)
    features=geojson_adapter({'features':collection},source)
    for feature in features:feature.metadata['planning_adapter_decisions']=decisions
    return features,decisions


class AdapterRegistry:
    def __init__(self):self.adapters={'geojson':geojson_adapter,'osm':osm_adapter,'planning_records':planning_adapter,'imagery_masks':None}
    def register(self,name,adapter):
        if name in self.adapters:raise ValueError('Adapter already registered')
        self.adapters[name]=adapter
    def load(self,feeds,sources,target_crs,base_directory):
        features=[];reports=[];target=CRS.from_user_input(target_crs)
        if not target.is_projected or any(abs(a.unit_conversion_factor-1)>1e-9 for a in target.axis_info[:2]):
            raise ValueError('Reconstruction target CRS must use projected metres')
        for feed in feeds:
            source=sources[feed['source']];adapter=self.adapters.get(feed['adapter'])
            if adapter is None and feed['adapter']!='imagery_masks':raise EvidenceMissing('Unsupported input adapter')
            path=(Path(base_directory)/feed['file']).resolve();content=path.read_bytes();digest=hashlib.sha256(content).hexdigest()
            if feed.get('sha256') and feed['sha256']!=digest:raise ValueError('Retained feed hash changed')
            if feed['adapter']=='imagery_masks':
                from .imagery import imagery_masks_adapter
                result=imagery_masks_adapter(json.loads(content),source,base_directory)
            else:result=adapter(json.loads(content),source)
            records,decisions=result if isinstance(result,tuple) else (result,[])
            projector=Transformer.from_crs(source.crs,target,always_xy=True)
            for feature in records:
                feature.geometry=mapping(transform(projector.transform,shape(feature.geometry)))
                feature.metadata.update(input_sha256=digest,input_file=feed['file'])
            features.extend(records);reports.append({'source':source.id,'adapter':feed['adapter'],'sha256':digest,'features':len(records),'decisions':decisions})
        return features,reports
