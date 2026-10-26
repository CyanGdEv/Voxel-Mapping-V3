"""Literal theming limits and vertical queue relationships, without invented routes."""
from concurrent.futures import CancelledError
import math
import re

import pymupdf
from shapely.geometry import Polygon,mapping

from .building_spec import digest
from .drawing_page_tools import native_inverse
from . import ordinary_surfaces,glyph_visibility

VERSION='planning-theming-layer-note-v1'


def parse(text):
    """A printed upper level is not a height above ground or a queue floor level."""
    if not isinstance(text,str) or len(text)>512:return None
    text=re.sub(r'\s+',' ',text).strip()
    match=re.fullmatch(r'Theming Envelope ([1-9][0-9]{0,2}) to ([0-9]{1,4}(?:\s*\.\s*[0-9]{1,3})?)( with (?:queuing|queueing) below)?',text,re.I)
    if not match:return None
    level=float(re.sub(r'\s+','',match[2]))
    if not math.isfinite(level):return None
    return {'version':VERSION,'envelope_number':int(match[1]),'printed_upper_level':level,
        'upper_level_reference':'source drawing level; datum unverified','upper_level_is_building_height':False,
        'queueing_below_stated':bool(match[3]),'queue_floor_level':None,'queue_extent_geometry':None,
        'queue_route_geometry':None,'solid_building_footprint_authorized':False}


def source_digest(evidence):
    return digest({'claim':evidence['claim'],'parts':[{k:r[k] for k in
        ('text','trace_indices','character_indices','geometry_pdf_native')} for r in evidence['parts']]})


def validate(evidence):
    if not isinstance(evidence,dict) or not isinstance(evidence.get('parts'),list) or not 1<=len(evidence['parts'])<=16:
        raise ValueError('Bounded original theming note required')
    text=' '.join(p['text'].strip() for p in evidence['parts'])
    claim=parse(text)
    if (claim is None or claim!=evidence.get('claim')
            or any(p.get('glyph_screen',{}).get('status')!='raster_consistent_candidate' for p in evidence['parts'])
            or source_digest(evidence)!=evidence.get('source_annotation_sha256')):
        raise ValueError('Visible literal theming relationship differs from source proof')
    return evidence


def capture(page,trace_indices,*,cancelled=lambda:False,cache=None):
    if not isinstance(trace_indices,list) or not 1<=len(trace_indices)<=16 or len(set(trace_indices))!=len(trace_indices):
        raise ValueError('Bounded unique original annotation trace indices required')
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>200000:raise ValueError('Theming note text budget exceeded')
    inverse=native_inverse(page);parts=[];cache={} if cache is None else cache
    for index in trace_indices:
        if cancelled():raise CancelledError('Theming note extraction cancelled')
        if type(index) is not int or not 0<=index<len(traces):raise ValueError('Original theming note trace absent')
        runs=ordinary_surfaces.label_runs([traces[index]])
        if len(runs)!=1:raise ValueError('Complete unambiguous theming note run required')
        run=runs[0];run['trace_indices']=[index]
        if index not in cache:cache[index]=glyph_visibility.screen_architectural_span(page,run,zoom=6)
        rect=pymupdf.Rect(run['bbox'])
        parts.append({'text':''.join(chr(c[0]) for c in run['chars']),
            'trace_indices':[index],'character_indices':run['character_indices'],
            'geometry_pdf_native':mapping(Polygon([tuple(p*inverse) for p in (rect.tl,rect.tr,rect.br,rect.bl)])),
            'glyph_screen':cache[index]})
    text=' '.join(r['text'].strip() for r in parts);claim=parse(text)
    if claim is None:raise ValueError('Unsupported literal theming envelope annotation')
    evidence={'claim':claim,'parts':parts}
    evidence['source_annotation_sha256']=source_digest(evidence)
    return validate(evidence)
