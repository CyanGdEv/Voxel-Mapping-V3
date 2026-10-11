"""Printed benchmark/value layout evidence; no surveyed datum or control acceptance."""
from collections import Counter
import hashlib
import json
import math
import re
import pymupdf
from shapely.geometry import Polygon,mapping
from .ordinary_surfaces import label_runs
from .drawing_geometry import native_inverse
from .glyph_visibility import screen_architectural_span

VERSION='native-benchmark-label-evidence-v1'
MARKER=re.compile(r'(?:o\.?\s*s\.?\s*b\.?\s*m\.?|bench\s*mark)',re.I)
VALUE=re.compile(r'\(\s*value\s+([+-]?\d+(?:\.\d+)?)\s*(m|mm)\s*\)',re.I)


def review(page,sha,number,*,max_checks=10000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded benchmark checks required')
    if not re.fullmatch('[0-9a-f]{64}',sha) or type(number) is not int or number<1:raise ValueError('Source page identity required')
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>500000:raise ValueError('Bounded benchmark source text required')
    markers=[];values=[];inverse=native_inverse(page)
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        match=VALUE.fullmatch(text)
        if not MARKER.fullmatch(text) and not match:continue
        rect=pymupdf.Rect(run['bbox']);points=[pymupdf.Point(x,y)*inverse for x,y in
            [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
        origin=pymupdf.Point(0,0)*inverse;direction=pymupdf.Point(*run['dir'])*inverse
        u=(direction.x-origin.x,direction.y-origin.y);length=math.hypot(*u)
        u=[v/length for v in u]
        row={'text':text,'label_geometry':mapping(Polygon([(p.x,p.y) for p in points])),
            'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'reading_direction_pdf_native':u,'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
        row['id']=hashlib.sha256(json.dumps([sha,number,row],sort_keys=True).encode()).hexdigest()
        if match:row.update(printed_value=float(match[1]),printed_units=match[2].lower());values.append(row)
        else:markers.append(row)
        if len(markers)+len(values)>1000:raise ValueError('Bounded benchmark label inventory required')
    checks=0;links=[]
    for marker in markers:
        u=marker['reading_direction_pdf_native'];n=(-u[1],u[0])
        points=marker['label_geometry']['coordinates'][0]
        along=[x*u[0]+y*u[1] for x,y in points];across=[x*n[0]+y*n[1] for x,y in points]
        height=max(across)-min(across);candidates=[]
        for value in values:
            checks+=1
            if checks>max_checks:break
            v=value['reading_direction_pdf_native']
            if u[0]*v[0]+u[1]*v[1]<1-1e-7:continue
            vp=value['label_geometry']['coordinates'][0]
            va=[x*u[0]+y*u[1] for x,y in vp];vn=[x*n[0]+y*n[1] for x,y in vp]
            # Layout candidate only: no label is moved, no nearest value is selected.
            overlap=min(max(along),max(va))-max(min(along),min(va))
            gap=max(min(vn)-max(across),min(across)-max(vn),0)
            if overlap>0 and gap<=3*height:candidates.append(value['id'])
        if checks>max_checks:break
        visible=marker['glyph_screen']['status']=='raster_consistent_candidate'
        supported=[identifier for identifier in candidates if next(v for v in values if v['id']==identifier)['glyph_screen']['status']=='raster_consistent_candidate']
        links.append({'marker_id':marker['id'],'candidate_value_ids':sorted(candidates),
            'visible_candidate_value_ids':sorted(supported),
            'status':'one_visible_printed_value_layout_candidate' if visible and len(candidates)==len(supported)==1 else
                'benchmark_visibility_withheld' if not visible else 'missing_or_competing_value_layout',
            'benchmark_location_verified':False,'vertical_datum_verified':False,'coordinate_control_verified':False})
    exhausted=checks>max_checks
    if exhausted:markers=[];values=[];links=[]
    return {'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'status':'benchmark_budget_withheld' if exhausted else 'printed_benchmark_layout_evidence_only',
        'markers':markers,'printed_values':values,'layout_links':links,'checks':checks,'max_checks':max_checks,
        'counts':dict(Counter(r['status'] for r in links)),
        'vertical_datum_verified':False,'coordinate_control_verified':False,'world_geometry_additions':0,
        'limitations':['Printed OSBM and value labels are source claims, not verified benchmark identity or vertical datum.',
            'Label coordinates are not physical benchmark coordinates. Layout association does not identify a survey symbol.',
            'Repeated underlying survey drawings are not independent controls or datum checks.']}
