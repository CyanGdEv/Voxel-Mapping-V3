"""Recover proposed paving from identical PDF tiling patterns and their painted paths."""
import hashlib
import json
import math

import numpy as np
from pypdf import PdfReader
from pypdf.generic import ContentStream
from shapely.geometry import Point

from .wicker_surfaces import painted_polygon


def pattern_identity(pattern):
    pattern = pattern.get_object()
    if pattern.get('/PatternType') != 1 or pattern.get('/PaintType') != 1:
        return None
    matrix = list(pattern.get('/Matrix',[1,0,0,1,0,0]))
    if matrix[:4] != [1,0,0,1]:
        return None
    objects = pattern.get('/Resources',{}).get('/XObject',{})
    images = {}
    for name,reference in objects.items():
        obj = reference.get_object()
        if obj.get('/Subtype') != '/Image':
            return None
        data = obj.get_data()
        if len(data) > 1_000_000:
            raise ValueError('Pattern image exceeds budget')
        images[str(name)] = {'sha256':hashlib.sha256(data).hexdigest(),
                             'width':obj.get('/Width'),'height':obj.get('/Height'),
                             'colour_space':str(obj.get('/ColorSpace')),
                             'bits':obj.get('/BitsPerComponent'), 'mask':str(obj.get('/ImageMask'))}
    # Include image bytes/palette, not just identical /Im0 drawing operators.
    signature = {'stream':pattern.get_data().hex(),'images':images,
                 'bbox':str(pattern.get('/BBox')),'xstep':str(pattern.get('/XStep')),
                 'ystep':str(pattern.get('/YStep'))}
    return hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()


def flatten_cubic(a,b,c,d,tolerance=.2,depth=0):
    if depth > 16:
        raise ValueError('Curve subdivision budget exceeded')
    # Distance of control points to the chord bounds the curve's deviation.
    def distance(p):
        delta=d-a; length=np.linalg.norm(delta)
        return np.linalg.norm(p-a) if length == 0 else abs(np.cross(delta,p-a))/length
    if max(distance(b),distance(c)) <= tolerance:
        return [d.tolist()]
    ab=(a+b)/2;bc=(b+c)/2;cd=(c+d)/2;abc=(ab+bc)/2;bcd=(bc+cd)/2;mid=(abc+bcd)/2
    return flatten_cubic(a,ab,abc,mid,tolerance,depth+1)+flatten_cubic(mid,bcd,cd,d,tolerance,depth+1)


def painted_patterns(operations, identities, page_height, max_operations=500000):
    if len(operations) > max_operations:
        raise ValueError('PDF operation budget exceeded')
    matrix=np.eye(3); pattern=None; clipping=[]; stack=[]; items=[]; current=None; start=None
    pending_clip=None; output=[]
    def point(x,y):
        px,py,_ = matrix@np.array([float(x),float(y),1.])
        return [float(px),float(page_height-py)]
    for index,(args,op) in enumerate(operations):
        if op == b'q':
            stack.append((matrix.copy(),pattern,clipping[:]))
            if len(stack)>64:raise ValueError('PDF graphics scope budget exceeded')
        elif op == b'Q':
            if not stack:raise ValueError('Unbalanced PDF graphics scopes')
            matrix,pattern,clipping=stack.pop()
        elif op == b'cm':
            a,b,c,d,e,f=map(float,args);matrix=matrix@np.array([[a,c,e],[b,d,f],[0,0,1.]])
        elif op in (b'rg',b'g',b'k',b'cs'):
            pattern=None
        elif op in (b'scn',b'sc'):
            pattern=identities.get(str(args[-1])) if args else None
        elif op == b'm':
            current=point(*args);start=current
        elif op == b'l':
            end=point(*args)
            if current is not None:items.append(['l',current,end])
            current=end
        elif op == b'c':
            if current is None:raise ValueError('Curve has no current point')
            a=np.array(current);b=np.array(point(*args[:2]));c=np.array(point(*args[2:4]));d=np.array(point(*args[4:]))
            for end in flatten_cubic(a,b,c,d):items.append(['l',current,end]);current=end
        elif op == b're':
            x,y,w,h=map(float,args);ring=[point(x,y),point(x+w,y),point(x+w,y+h),point(x,y+h),point(x,y)]
            items.extend([['l',a,b] for a,b in zip(ring,ring[1:])]);current=ring[-1];start=ring[0]
        elif op == b'h':
            if current is not None and current != start:items.append(['l',current,start]);current=start
        elif op in (b'W',b'W*'):
            pending_clip=painted_polygon({'items':items,'even_odd':op==b'W*'})
            if pending_clip is None:pending_clip=False
        elif op in (b'f',b'f*',b'F',b'B',b'B*',b'b',b'b*',b'S',b's',b'n'):
            if pattern and op in (b'f',b'f*',b'F',b'B',b'B*',b'b',b'b*'):
                polygon=painted_polygon({'items':items,'even_odd':op in (b'f*',b'B*',b'b*')})
                if polygon is not None and all(c is not False for c in clipping):
                    for clip in clipping:polygon=polygon.intersection(clip)
                    if not polygon.is_empty and polygon.geom_type in ('Polygon','MultiPolygon'):
                        output.append({'polygon':polygon,'pattern_sha256':pattern,'pdf_operation_index':index})
            if pending_clip is not None:clipping.append(pending_clip);pending_clip=None
            items=[];current=start=None
        elif op in (b'v',b'y'):
            # Unsupported curve shorthand invalidates only this path.
            items.append(['unsupported'])
        if len(items)>20000:raise ValueError('PDF path budget exceeded')
    return output


def extract_pattern_surfaces(path, annotations, scale, expected_sha):
    data=path.read_bytes()
    if len(data)>10_000_000 or hashlib.sha256(data).hexdigest()!=expected_sha:
        raise ValueError('Pattern source PDF size/hash mismatch')
    reader=PdfReader(path);page=reader.pages[0]
    if page.get('/Rotate',0)!=0:raise ValueError('Pattern source must be unrotated')
    identities={str(name):pattern_identity(obj) for name,obj in page['/Resources'].get('/Pattern',{}).items()}
    paths=painted_patterns(ContentStream(page.get_contents(),reader).operations,identities,float(page.mediabox.top))
    label=next(a for a in annotations if a['text']=='New Paving with levels')
    x0,y0,x1,y1=label['bbox']
    swatches=[]
    for p in paths:
        a,b,c,d=p['polygon'].bounds
        if 0<=x0-c<=100 and max(b,y0)<min(d,y1) and 20<=c-a<=120 and 10<=d-b<=60:
            swatches.append(p)
    if len(swatches)!=1:raise ValueError('Unique painted new-paving pattern swatch required')
    swatch=swatches[0]; candidates=[];seen=set()
    for p in paths:
        polygon=p['polygon']
        if p['pattern_sha256']!=swatch['pattern_sha256'] or polygon.bounds[2]>=swatch['polygon'].bounds[0]:continue
        identity=polygon.normalize().wkb
        if identity in seen or not 2<=polygon.area*scale**2<=10000:continue
        seen.add(identity)
        labels=[a['text'] for a in annotations if a['text']=='Plaza' and polygon.covers(Point((a['bbox'][0]+a['bbox'][2])/2,(a['bbox'][1]+a['bbox'][3])/2))]
        candidates.append({**p,'state':'new','legend_text':label['text'],
                           'legend_operation_index':swatch['pdf_operation_index'],
                           'area_m2_printed_scale':polygon.area*scale**2,'contained_labels':labels,
                           'material':None,'material_status':'Pattern identifies proposed paving, not an as-built material',
                           'curve_flattening_tolerance_pdf_points':.2})
    return candidates,{'status':'matched_tiling_pattern_and_image_resources',
                       'polygon_candidates':len(candidates),'pattern_sha256':swatch['pattern_sha256']}
