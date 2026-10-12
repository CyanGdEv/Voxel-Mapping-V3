"""Bounded native glyph/straight-stroke observations with Form transforms applied.

PyMuPDF retains original font glyph IDs and display-list paint identities. These
are source observations, not independently verified survey correspondences.
"""
import math
import pymupdf
from shapely.geometry import LineString,box
from .drawing_page_tools import native_inverse
from .ordinary_surfaces import label_runs
from .drawing_geometry import subpaths,fill_geometry,validated_options

VERSION='native-survey-form-observations-v1'


def text_runs(page):
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(s['chars']) for s in traces)>500000:
        raise ValueError('Native survey trace budget exceeded')
    inverse=native_inverse(page);runs=[]
    for span in label_runs(traces):
        text=''.join(chr(c[0]) for c in span['chars']).strip()
        if not text or not text.isascii():continue
        point=pymupdf.Point(span['chars'][0][2])*inverse
        runs.append({'text':text,'origin':[point.x,point.y],
            'origin_basis':'original_native_glyph_trace_with_form_transform',
            'paint_seqno':span['seqno'],'trace_indices':span['trace_indices'],
            'character_indices':span['character_indices']})
    return runs


def marks(page,*,max_segments=500):
    inverse=native_inverse(page);paths=page.get_drawings(extended=True)
    if len(paths)>100000:raise ValueError('Native survey path budget exceeded')
    segments=[];paint_refs=[];clips=[];groups=[];options=validated_options({})
    for ordinal,path in enumerate(paths):
        level=path.get('level',0);clips=[c for c in clips if c[0]<level];groups=[g for g in groups if g<level]
        if path['type']=='group':groups.append(level);continue
        if path['type']=='clip':
            try:
                parts,_=subpaths(path,inverse,options)
                rings=[p+[p[0]] if p[0]!=p[-1] else p for p in parts]
                clip=fill_geometry(rings,path.get('even_odd',False),True)
                if clip.is_empty or not clip.is_valid or not clip.equals(box(*clip.bounds)):clip=None
            except (ValueError,KeyError,TypeError):clip=None
            clips.append((level,clip));continue
        if (path['type']!='s' or groups or path.get('layer') or path.get('stroke_opacity',1)!=1
                or any(c[1] is None for c in clips) or not path.get('color') or min(path['color'])>.95
                or path.get('dashes') not in ('[] 0',None)):continue
        # Compound paths and closure are not silently decomposed into marks.
        if len(path['items'])!=1 or path['items'][0][0]!='l' or path.get('closePath'):continue
        segment=[]
        for point in path['items'][0][1:3]:
            point=point*inverse;segment.append([point.x,point.y])
        line=LineString(segment)
        if any(not c[1].covers(line) for c in clips):continue
        if not all(math.isfinite(v) for p in segment for v in p):raise ValueError('Finite native mark coordinates required')
        segments.append(segment);paint_refs.append({'ordinal':ordinal,'seqno':path['seqno']})
        if len(segments)>max_segments:raise ValueError('Native survey segment budget exceeded')
    found={}
    for i,a in enumerate(segments):
        delta=[a[1][k]-a[0][k] for k in (0,1)];length=math.hypot(*delta)
        if not 2<=length<=20:continue
        centre=[(a[0][k]+a[1][k])/2 for k in (0,1)]
        for j,b in enumerate(segments[i+1:],i+1):
            other=[b[1][k]-b[0][k] for k in (0,1)];other_length=math.hypot(*other)
            midpoint=[(b[0][k]+b[1][k])/2 for k in (0,1)]
            if (2<=other_length<=20 and abs(sum(x*y for x,y in zip(delta,other)))/(length*other_length)<1e-6
                    and math.dist(centre,midpoint)<1e-6):
                found.setdefault(tuple(round(v,6) for v in centre),{'page_point':centre,'stroke_indices':set()})['stroke_indices'].update((i,j))
    return {'status':'crosshair_candidates','segments':segments,'segment_paint_references':paint_refs,
        'marks':[{'page_point':m['page_point'],'stroke_indices':sorted(m['stroke_indices'])} for m in found.values()],
        'adapter_version':VERSION,'world_geometry_additions':0}
