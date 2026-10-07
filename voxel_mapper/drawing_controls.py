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
from .drawing_marks import extract_marks, mark_for_label
from .drawing_grid import extract_grid_controls

NUMBER = r'([+-]?\d{1,9}(?:\.\d{1,4})?)(?![\d.,eE])'
PAIR = re.compile(r'^\s*(?:E|Easting)\s*[:=]\s*'+NUMBER+r'\s*(?:m\b)?\s*[,;]\s*(?:N|Northing)\s*[:=]\s*'+NUMBER+r'\s*(?:m\b)?\s*$',re.I)
EPSG = re.compile(r'\bEPSG\s*[:=]?\s*(\d{4,6})\b',re.I)


def inspect_coordinate_labels(page, bounds=None, *, reuse_allowed=False,
                              max_fragments=2000, max_text=500_000, require_marks=False, require_grid=False):
    result={'status':'blocked_reuse','viewports':[],'independent_accuracy':'not_verified'}
    if reuse_allowed is not True:
        return result
    pairs=[]
    codes=set()
    fragments=characters=0
    marks=None

    def visit(text, cm, tm, font, size):
        nonlocal fragments,characters
        fragments+=1
        characters+=len(text)
        if fragments>max_fragments or characters>max_text:
            raise ValueError('Coordinate-label budget exceeded')
        codes.update(int(value) for value in EPSG.findall(text))
        if require_grid:
            return
        match=PAIR.fullmatch(text)
        if not match:
            return
        x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4]
        y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
        if require_marks:
            anchor=mark_for_label(marks,(x,y))
            if anchor is None:
                raise ValueError('Coordinate label requires one explicit leader-connected crosshair')
            x,y=anchor
        pairs.append((x,y,float(match[1]),float(match[2])))
        if len(pairs)>64:
            raise ValueError('Coordinate control budget exceeded')

    try:
        if require_grid and require_marks:
            raise ValueError('Select one registration control mode')
        if page.get('/VP') or page.get('/LGIDict'):
            return {**result,'status':'embedded_registration_present'}
        if require_marks:
            marks=extract_marks(page,reuse_allowed=True)
            if marks['status']!='crosshair_candidates':
                raise ValueError('Supported straight crosshair geometry required')
        page.extract_text(visitor_text=visit)
        if require_grid:
            grid=extract_grid_controls(page,reuse_allowed=True,max_fragments=max_fragments,max_text=max_text)
            if grid['status']!='grid_intersection_candidates':
                raise ValueError(grid.get('reason','Grid controls unavailable'))
            pairs.extend(grid['pairs'])
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
        result['registration_method']='leader_connected_crosshair_candidates' if require_marks else 'explicit_coordinate_label_origins'
        if require_grid:
            result['registration_method']='explicit_labelled_grid_intersections'
        result['declared_source_crs']=source.to_string()
        result['coordinate_transform_accuracy_m']=accuracy
        result['conversion_only_same_datum']=conversion_only
        for viewport in result['viewports']:
            viewport['control_provenance']='leader_connected_crosshair_not_verified_survey_mark' if require_marks else 'native_text_origin_not_verified_survey_mark'
            if require_grid:
                viewport['control_provenance']='labelled_grid_intersection_not_independently_verified'
        result['limitations']=['Text origins are not verified survey marks or grid intersections',
                              'Consistent fit does not prove absolute position; constant label offsets can survive validation',
                              'Only single-line explicitly paired E/N labels and one declared projected metre EPSG are supported',
                              'No OCR, scale-only placement, world insertion or independent accuracy verification']
        if require_marks:
            result['limitations']=['Centred orthogonal strokes and explicit leader attachment are candidate survey symbols',
                                  'Leader attachment uses a one-point PDF tolerance; no nearest-mark or text-origin fallback',
                                  'Drawing coordinates and construction status still need independent verification',
                                  'No general grid detection, OCR or world insertion']
        if require_grid:
            result['limitations']=grid['limitations']+['Residual fit is internal consistency, not independent surveyed accuracy']
        return result
    except (ValueError,TypeError,KeyError,IndexError,ProjError) as error:
        return {**result,'status':'rejected','reason':str(error)}
