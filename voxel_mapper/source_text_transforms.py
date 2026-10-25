"""Bounded direct-page PDF show-operator bindings for original glyph transforms.

No font fitting, raster search, inferred text advance, forms or replacement fonts.
Unbound/unsupported sources continue through the existing glyph screen.
"""
import hashlib
import math
import weakref

import pymupdf

from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION='direct-source-text-transform-v1'
MAX_BYTES=16000000
MAX_OPERATORS=500000
MAX_SHOWS=20000
MAX_CHARACTERS=200000
_CACHE=weakref.WeakKeyDictionary()


def _bytes(value):
    if hasattr(value,'original_bytes'):return value.original_bytes
    if isinstance(value,bytes):return value
    raise ValueError('Original encoded PDF string bytes required')


def _numbers(args,count):
    if (len(args)!=count or any(not isinstance(v,(int,float)) or isinstance(v,bool)
            or not math.isfinite(float(v)) for v in args)):
        raise ValueError('Exact finite numeric PDF operands required')
    return list(map(float,args))


def _inventory(page):
    from pypdf.generic import ContentStream, DecodedStreamObject
    from pypdf.errors import PdfReadError
    if (page.get_xobjects() or page.cropbox!=page.mediabox or page.mediabox.x0!=0 or page.mediabox.y0!=0
            or page.parent.xref_get_key(page.xref,'UserUnit') not in (('null','null'),('int','1'),('real','1'))):return None
    content=page.read_contents()
    if len(content)>MAX_BYTES:return None
    fonts=[tuple(f) for f in page.get_fonts(full=True) if f[6]==0]
    if not 1<=len(fonts)<=128:return None
    transform=~native_inverse(page)
    pin=hashlib.sha256(content).hexdigest()
    signature=(pin,tuple(fonts),tuple(transform))
    cached=_CACHE.get(page)
    if cached is not None and cached[0]==signature:return cached[1]
    def finish(value):
        _CACHE[page]=(signature,value)
        return value
    source=DecodedStreamObject();source.set_data(content)
    try:operations=ContentStream(source,None).operations
    except (ValueError,TypeError,KeyError,IndexError,PdfReadError):return finish(None)
    if len(operations)>MAX_OPERATORS:return finish(None)
    resources={}
    for f in fonts:resources.setdefault('/'+f[4],[]).append(f)
    cm=pymupdf.Matrix(1,0,0,1,0,0);font=None;size=0.;horizontal=100.;rise=0.;render=0;tm=None
    stack=[];records={};shows=0;characters=0
    try:
        for index,(args,op) in enumerate(operations):
            if op==b'q':
                if len(stack)>=64:return finish(None)
                stack.append((cm,font,size,horizontal,rise,render));tm=None
            elif op==b'Q':
                if not stack:return finish(None)
                cm,font,size,horizontal,rise,render=stack.pop();tm=None
            elif op==b'cm':cm=pymupdf.Matrix(*_numbers(args,6))*cm;tm=None
            elif op==b'Tf':
                if len(args)!=2 or not isinstance(args[0],str) or not args[0].startswith('/'):
                    return finish(None)
                font=str(args[0]);size=_numbers(args[1:],1)[0]
            elif op==b'Tz':horizontal=_numbers(args,1)[0]
            elif op==b'Ts':rise=_numbers(args,1)[0]
            elif op==b'Tr':
                value=_numbers(args,1)[0]
                if value not in range(8):return finish(None)
                render=int(value)
            elif op==b'Tm':tm=pymupdf.Matrix(*_numbers(args,6))
            elif op in (b'BT',b'ET',b'Td',b'TD',b'T*',b"'",b'"',b'Do'):tm=None
            elif op==b'gs':
                # A graphics-state dictionary may replace the text font.
                # A following explicit Tf is needed before another binding.
                font=None;tm=None
            elif op in (b'Tj',b'TJ'):
                current=tm;tm=None;shows+=1
                if shows>MAX_SHOWS:return finish(None)
                if len(args)!=1:return finish(None)
                if op==b'Tj':encoded=_bytes(args[0])
                else:
                    parts=args[0]
                    if not isinstance(parts,list) or any(not isinstance(v,(str,bytes,int,float)) for v in parts):
                        return finish(None)
                    first=next((i for i,v in enumerate(parts) if isinstance(v,(str,bytes))),len(parts))
                    if any(isinstance(v,(int,float)) and float(v)!=0 for v in parts[:first]):continue
                    encoded=b''.join(_bytes(v) for v in parts if isinstance(v,(str,bytes)))
                characters+=len(encoded)
                if characters>2*MAX_CHARACTERS:return finish(None)
                selected=resources.get(font,[])
                if (current is None or len(selected)!=1 or not 0<len(encoded)<=2000
                        or rise!=0 or render!=0):continue
                basis=pymupdf.Matrix(size*horizontal/100,0,0,size,0,0)*current*cm
                a,b,c,d=basis.a,basis.b,basis.c,basis.d
                xscale=math.hypot(a,b);yscale=math.hypot(c,d)
                if (not all(math.isfinite(v) for v in basis) or not 1<=xscale<=40 or not 1<=yscale<=40
                        or not .5<=xscale/yscale<=2 or a*d-b*c<=0
                        or abs(a*c+b*d)>1e-6*xscale*yscale):continue
                point=pymupdf.Point(current.e,current.f)*cm*transform
                row={'font_xref':selected[0][0],'font_resource':font[1:],
                    'encoded':encoded,'origin':tuple(point),'basis':[a,b,c,d],
                    'operator_index':index,'text_matrix':list(current),'graphics_matrix':list(cm),
                    'font_size':size,'horizontal_scale_percent':horizontal}
                key=(round(point.x,2),round(point.y,2))
                records.setdefault(key,[]).append(row)
        if stack:return finish(None)
    except (ValueError,TypeError,IndexError,OverflowError):return finish(None)
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>MAX_CHARACTERS:return finish(None)
    trace_starts={}
    for i,row in enumerate(traces):
        if row['chars']:
            point=row['chars'][0][2];trace_starts.setdefault((round(point[0],2),round(point[1],2)),[]).append(i)
    return finish({'records':records,'traces':traces,'trace_starts':trace_starts,'content_sha256':pin,
                   'operator_count':len(operations),'shows':shows})


def bind(page,span,fonts,codes,code_digits):
    """Return one exact source show and orthogonal basis, or no new adapter."""
    inventory=_inventory(page)
    if inventory is None:return None
    point=span['chars'][0][2];key=(round(point[0],2),round(point[1],2))
    # Full original runs only: no inferred advance or partial show positioning.
    original=[]
    for index in inventory['trace_starts'].get(key,[]):
        row=inventory['traces'][index]
        if (all(row.get(k)==span.get(k) for k in ('font','size','type','color','opacity','dir','layer'))
                and tuple(row['chars'])==tuple(span['chars'])):original.append(index)
    if len(original)!=1:return None
    try:encoded=bytes.fromhex(''.join(f'{c:0{code_digits}x}' for c in codes))
    except (ValueError,TypeError):return None
    matches=[]
    for row in inventory['records'].get(key,[]):
        if (row['font_xref'] not in {f[0] for f in fonts} or row['encoded']!=encoded
                or math.dist(point,row['origin'])>.002):continue
        a,b,_,_=row['basis'];length=math.hypot(a,b)
        if abs(length-span['size'])>.002 or math.dist((a/length,-b/length),span['dir'])>1e-5:continue
        matches.append(row)
    if len(matches)!=1:return None
    row=matches[0]
    return {'version':VERSION,'basis':'one_original_direct_show_and_exact_native_trace',
        'page_content_sha256':inventory['content_sha256'],'page':page.number+1,
        'source_font_xref':row['font_xref'],'font_resource':row['font_resource'],
        'operator_index':row['operator_index'],'operator_count':inventory['operator_count'],
        'encoded_glyph_bytes_sha256':hashlib.sha256(encoded).hexdigest(),'encoded_glyph_count':len(codes),
        'native_trace_index':original[0],'native_trace_sha256':digest(span['chars']),
        'source_text_matrix':row['text_matrix'],'source_graphics_matrix':row['graphics_matrix'],
        'source_font_size':row['font_size'],'horizontal_scale_percent':row['horizontal_scale_percent'],
        'effective_font_basis_pdf_native':row['basis'], 'physical_identity_verified':False}
