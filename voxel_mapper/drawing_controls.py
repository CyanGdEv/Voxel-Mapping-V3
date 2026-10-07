"""Candidate registration from explicitly labelled native PDF coordinate pairs.

Text origins are not surveyed marks. A consistent fit remains a hypothesis.
"""
import copy
import re

from pyproj import CRS
from pyproj.transformer import TransformerGroup
from pyproj.exceptions import ProjError
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject

from .geopdf import inspect_registration

NUMBER = r'([+-]?\d{1,9}(?:\.\d{1,4})?)(?![\d.,eE])'
PAIR = re.compile(r'^\s*(?:E|Easting)\s*[:=]\s*'+NUMBER+r'\s*(?:m\b)?\s*[,;]\s*(?:N|Northing)\s*[:=]\s*'+NUMBER+r'\s*(?:m\b)?\s*$',re.I)
EPSG = re.compile(r'\bEPSG\s*[:=]?\s*(\d{4,6})\b',re.I)


def inspect_coordinate_labels(page, bounds=None, *, reuse_allowed=False,
                              max_fragments=2000, max_text=500_000):
    result={'status':'blocked_reuse','viewports':[],'independent_accuracy':'not_verified'}
    if reuse_allowed is not True:
        return result
    pairs=[]
    codes=set()
    fragments=characters=0

    def visit(text, cm, tm, font, size):
        nonlocal fragments,characters
        fragments+=1
        characters+=len(text)
        if fragments>max_fragments or characters>max_text:
            raise ValueError('Coordinate-label budget exceeded')
        codes.update(int(value) for value in EPSG.findall(text))
        match=PAIR.fullmatch(text)
        if not match:
            return
        x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4]
        y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
        pairs.append((x,y,float(match[1]),float(match[2])))
        if len(pairs)>64:
            raise ValueError('Coordinate control budget exceeded')

    try:
        if page.get('/VP') or page.get('/LGIDict'):
            return {**result,'status':'embedded_registration_present'}
        page.extract_text(visitor_text=visit)
        if len(codes)!=1:
            raise ValueError('One explicit unambiguous EPSG declaration required')
        if len(pairs)<4:
            raise ValueError('At least four explicit paired E/N labels required')
        source=CRS.from_epsg(next(iter(codes)))
        if not source.is_projected or len(source.axis_info)!=2 or any(axis.unit_conversion_factor!=1 for axis in source.axis_info):
            raise ValueError('Declared projected metre CRS required')
        group=TransformerGroup(source,4326,always_xy=True,allow_ballpark=False)
        if not group.best_available or not group.transformers:
            raise ValueError('Best non-ballpark coordinate transformation unavailable')
        projector=group.transformers[0]
        # PROJ leaves accuracy unspecified for pure mathematical conversions.
        # Accept that only when no datum transformation is involved.
        conversion_only=(source.geodetic_crs.equals(CRS.from_epsg(4326),ignore_axis_order=True)
                         and bool(projector.operations)
                         and all(op.type_name=='Conversion' for op in projector.operations))
        accuracy=0 if conversion_only else projector.accuracy
        if not 0<=accuracy<=1:
            raise ValueError('Available non-ballpark transformation of at most one metre required')
        left,bottom,right,top=map(float,page.cropbox)
        local=[]
        geographic=[]
        for x,y,east,north in pairs:
            if not (left<x<right and bottom<y<top):
                raise ValueError('Coordinate label origin outside page crop')
            lon,lat=projector.transform(east,north,errcheck=True)
            local.extend(((x-left)/(right-left),(y-bottom)/(top-bottom)))
            geographic.extend((lat,lon))
        def array(values):
            return ArrayObject([FloatObject(value) for value in values])
        measure=DictionaryObject({NameObject('/Subtype'):NameObject('/GEO'),
            NameObject('/LPTS'):array(local),NameObject('/GPTS'):array(geographic),
            NameObject('/GCS'):DictionaryObject({NameObject('/EPSG'):NumberObject(4326)})})
        candidate=copy.copy(page)
        candidate[NameObject('/VP')]=ArrayObject([DictionaryObject({NameObject('/BBox'):array([left,bottom,right,top]),NameObject('/Measure'):measure})])
        result=inspect_registration(candidate,bounds)
        result['registration_method']='explicit_coordinate_label_origins'
        result['declared_source_crs']=source.to_string()
        result['coordinate_transform_accuracy_m']=accuracy
        result['conversion_only_same_datum']=conversion_only
        for viewport in result['viewports']:
            viewport['control_provenance']='native_text_origin_not_verified_survey_mark'
        result['limitations']=['Text origins are not verified survey marks or grid intersections',
                              'Consistent fit does not prove absolute position; constant label offsets can survive validation',
                              'Only single-line explicitly paired E/N labels and one declared projected metre EPSG are supported',
                              'No OCR, scale-only placement, world insertion or independent accuracy verification']
        return result
    except (ValueError,TypeError,KeyError,IndexError,ProjError) as error:
        return {**result,'status':'rejected','reason':str(error)}
