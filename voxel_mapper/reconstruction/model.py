"""Explicit source references and measurement status for every reconstruction."""
from dataclasses import dataclass,field
import math
from shapely.geometry import shape

class EvidenceMissing(ValueError):
    pass

@dataclass(frozen=True)
class Source:
    id:str
    kind:str
    url:str
    license:str
    crs:str
    vertical_datum:str|None=None
    registration_status:str='unregistered'
    sha256:str|None=None
    metadata:dict=field(default_factory=dict)

    def __post_init__(self):
        if not all((self.id,self.kind,self.url,self.license,self.crs)):
            raise ValueError('Source identity, URI, licence and CRS required')

@dataclass
class Feature:
    id:str
    family:str
    geometry:dict
    geometry_source:str
    parameters:dict=field(default_factory=dict)
    metadata:dict=field(default_factory=dict)

    def value(self,name,sources,allow_estimates=False,default=None):
        item=self.parameters.get(name)
        if item is None:
            if default is not None and allow_estimates:return default
            raise EvidenceMissing(f'Missing {name}')
        if not isinstance(item,dict) or item.get('source') not in sources:
            raise EvidenceMissing(f'Unknown source for {name}')
        status=item.get('status')
        if status not in ('documented','measured','estimated'):
            raise EvidenceMissing(f'Missing evidence status for {name}')
        if status=='estimated' and not allow_estimates:
            raise EvidenceMissing(f'Estimated {name} disabled')
        value=item.get('value')
        if isinstance(value,(float,int)) and (isinstance(value,bool) or not math.isfinite(value)):
            raise ValueError(f'Invalid {name}')
        if value is None:raise EvidenceMissing(f'Missing value for {name}')
        return value

    def validate(self,sources,target_datum):
        if not self.id or not self.family:raise ValueError('Feature identity and family required')
        source=sources.get(self.geometry_source)
        if source is None:raise EvidenceMissing('Unknown geometry source')
        if source.kind in ('planning','cad','survey','imagery') and source.registration_status!='accepted':
            raise EvidenceMissing('Geometry registration not accepted')
        review=source.metadata.get('horizontal_registration_review')
        if review is not None:
            from .registration import require_accepted_review
            try:require_accepted_review(review)
            except ValueError as error:raise EvidenceMissing(str(error)) from error
        geom=shape(self.geometry)
        if review is not None:
            from .registration import registration_domain
            if not registration_domain(review).buffer(1e-7).covers(geom):
                raise EvidenceMissing('Geometry outside validated registration domain')
        # A purely vertical 3D line has a zero-length 2D Shapely projection.
        vertical=geom.geom_type=='LineString' and geom.has_z and len(set(tuple(p) for p in geom.coords))>1
        if geom.is_empty or (not geom.is_valid and not vertical):raise ValueError('Invalid geometry')
        if geom.has_z and (not target_datum or source.vertical_datum!=target_datum):
            raise EvidenceMissing('3D geometry vertical datum does not match terrain')
        return geom
