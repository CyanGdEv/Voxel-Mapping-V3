"""Bounded native glyph consistency using embedded programs or bound original resources."""
import math
import numpy as np
import pymupdf

VERSION='source-font-glyph-raster-screen-v7'
INK_VERSION='source-font-isolated-glyph-screen-v5'


def _source_rgb(span):
    value=span.get('color')
    if (not isinstance(value,(tuple,list)) or len(value) not in (1,3)
            or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in value)):
        return None
    rgb=tuple(float(v) for v in value)
    return rgb*3 if len(rgb)==1 else rgb


def _colour_support(samples,rgb,threshold):
    """Match original-colour ink blended over white, retaining chromaticity.

    Black paint cannot stand in for grey/coloured text. Surrounding matching
    paint is still rejected by the independent reference-ink ring check.
    """
    delta=255*(1-np.asarray(rgb,dtype=float))
    ink=255-samples.astype(float)
    coverage=np.sum(ink*delta,axis=2)/float(delta@delta)
    residual=np.max(np.abs(ink-coverage[...,None]*delta),axis=2)
    return (coverage>(255-threshold)/255)&(coverage<=1.04)&(residual<=12)


def _colour_match(samples,rgb,reference):
    expected=255-(255-reference.astype(float))[...,None]*(1-np.asarray(rgb))
    padded=np.pad(samples.astype(float),((1,1),(1,1),(0,0)),constant_values=255)
    ink=np.pad(_colour_support(samples,rgb,200),1,constant_values=False)
    height,width=reference.shape
    return np.logical_or.reduce([(np.max(np.abs(padded[y:y+height,x:x+width]-expected),axis=2)<=12)&ink[y:y+height,x:x+width]
        for y in range(3) for x in range(3)])


def _direct_winansi_resource(page,span,fonts):
    """Bind unembedded direct WinAnsi text to its actual original show operator.

    This narrow adapter needs explicit horizontal Tm positioning, no form text,
    standard units and an unchanged native character/glyph/origin inventory.
    It does not infer a resource from its name or eliminate an unknown font by
    failed raster support. Unsupported cases keep the existing font holds.
    """
    import hashlib
    import re
    try:
        from pypdf.generic import ContentStream, DecodedStreamObject
        from pypdf.errors import PdfReadError
    except ImportError:return None
    from .drawing_page_tools import native_inverse
    if (tuple(span['dir'])!=(1.,0.) or page.get_xobjects()
            or page.parent.xref_get_key(page.xref,'UserUnit') not in (('null','null'),('int','1'),('real','1'))):
        return None
    supported={}
    for font in fonts:
        if (font[6]!=0 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*',font[4])
                or font[2] not in ('TrueType','Type1') or font[5]!='WinAnsiEncoding'
                or page.parent.xref_get_key(font[0],'Encoding')!=('name','/WinAnsiEncoding')
                or page.parent.xref_get_key(font[0],'ToUnicode')!=('null','null')
                or page.parent.extract_font(font[0])[3]):
            continue
        supported['/'+font[4]]=font
    if not supported:return None
    content=page.read_contents()
    if len(content)>2000000:return None
    stream=DecodedStreamObject();stream.set_data(content)
    try:operations=ContentStream(stream,None).operations
    except (ValueError,TypeError,KeyError,IndexError,PdfReadError):return None
    if len(operations)>20000:return None
    original=page.get_texttrace()
    if len(original)>10000 or sum(len(r['chars']) for r in original)>100000:return None
    indexed={};occurrences={}
    def char_key(c):return (c[0],c[1],tuple(c[2]),tuple(c[3]))
    for row in original:
        if (any(row.get(k)!=span.get(k) for k in ('font','size','type','color','opacity','dir','layer'))
                or tuple(row['dir'])!=(1.,0.) or row.get('type')!=0 or not row['chars']):continue
        text=''.join(chr(c[0]) for c in row['chars'])
        x,y=row['chars'][0][2]
        key=(text,round(x,3),round(y,3),round(row['size'],6))
        indexed.setdefault(key,[]).append(row)
        for char in row['chars']:occurrences.setdefault(char_key(char),set()).add(row['seqno'])
    if any(len(occurrences.get(char_key(c),set()))!=1 for c in span['chars']):return None
    transform=~native_inverse(page)
    cm=pymupdf.Matrix(1,0,0,1,0,0);font_key=None;size=0.;tm=None;stack=[]
    bindings={};witnesses={};glyph_witnesses={};characters=0
    for op_index,(args,op) in enumerate(operations):
        if op==b'q':
            if len(stack)>=64:return None
            stack.append((cm,font_key,size));tm=None
        elif op==b'Q':
            if not stack:return None
            cm,font_key,size=stack.pop();tm=None
        elif op==b'cm':
            if len(args)!=6:return None
            try:cm=pymupdf.Matrix(*map(float,args))*cm
            except (TypeError,ValueError):return None
            tm=None
        elif op==b'Tf':
            if len(args)!=2:return None
            try:font_key,size=str(args[0]),float(args[1])
            except (TypeError,ValueError):return None
        elif op==b'Tm':
            try:tm=list(map(float,args)) if len(args)==6 else None
            except (TypeError,ValueError):return None
        elif op==b'gs':
            if len(args)!=1:return None
            name=str(args[0]).lstrip('/')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*',name):return None
            kind,value=page.parent.xref_get_key(page.xref,'Resources/ExtGState/'+name)
            if kind=='xref':
                target=re.fullmatch(r'(\d+) 0 R',value)
                if not target or page.parent.xref_get_key(int(target[1]),'Font')!=('null','null'):return None
            elif kind!='dict' or re.search(r'/Font\b',value):return None
        elif op in (b'BT',b'ET',b'Td',b'TD',b'T*',b"'",b'"',b'Ts',b'Tz'):tm=None
        elif op in (b'Tj',b'TJ'):
            positioned=tm;tm=None
            if (font_key not in supported or positioned is None or positioned[:4]!=[1.,0.,0.,1.]
                    or list(cm)[:4]!=[1.,0.,0.,1.]):continue
            parts=[args[0]] if op==b'Tj' else [v for v in args[0] if isinstance(v,(str,bytes))]
            if op==b'TJ':
                first=next((i for i,v in enumerate(args[0]) if isinstance(v,(str,bytes))),len(args[0]))
                if any(isinstance(v,(int,float)) and float(v)!=0 for v in args[0][:first]):continue
            try:encoded=b''.join(v.original_bytes if hasattr(v,'original_bytes') else bytes(v) for v in parts)
            except (AttributeError,TypeError,ValueError,UnicodeError):continue
            characters+=len(encoded)
            if characters>100000:return None
            if not encoded or len(encoded)>500 or any(not 32<=v<=126 for v in encoded):continue
            if not all(math.isfinite(v) for v in (*positioned,*list(cm),size)):return None
            point=pymupdf.Point(positioned[4],positioned[5])*cm*transform
            key=(encoded.decode('ascii'),round(point.x,3),round(point.y,3),round(size,6))
            matching=indexed.get(key,[])
            if len(matching)!=1:continue
            for row in matching:
                if math.dist(row['chars'][0][2],point)>.002:continue
                selected=supported[font_key]
                proof={'operator_index':op_index,'operator':op.decode('ascii'),'font_resource':font_key,
                    'source_font_xref':selected[0],'encoded_ascii_sha256':hashlib.sha256(encoded).hexdigest(),
                    'encoded_character_count':len(encoded),'source_text_matrix':positioned,
                    'source_ctm':list(cm),'source_paint_seqno':row['seqno']}
                witnesses[op_index]=proof
                for char in row['chars']:
                    bindings.setdefault(char_key(char),set()).add(selected[0])
                    glyph_witnesses.setdefault(char_key(char),set()).add(op_index)
    if stack:return None
    resolved=[bindings.get(char_key(c),set()) for c in span['chars']]
    if not resolved or any(len(r)!=1 for r in resolved):return None
    identifiers=set.union(*resolved)
    if len(identifiers)!=1:return None
    selected=next(f for f in supported.values() if f[0] in identifiers)
    # Identical same-name unembedded overprints from distinct resources cannot
    # be proven by the glyph inventory; retain that ambiguity above.
    contributing=set().union(*(glyph_witnesses[char_key(c)] for c in span['chars']))
    relevant=[witnesses[i] for i in sorted(contributing)]
    proof={'basis':'original_direct_text_show_operator_and_native_glyph_binding',
        'source_font_xref':selected[0],'font_resource':selected[4],
        'source_font_dictionary_sha256':hashlib.sha256(page.parent.xref_object(selected[0]).encode()).hexdigest(),
        'source_content_sha256':hashlib.sha256(content).hexdigest(),'source_operations':relevant,
        'position_match_tolerance_pdf_points':.002,'source_font_program_embedded':False,
        'font_appearance_across_renderers_verified':False,'source_pdf_modified':False}
    return selected,proof


def simple_cff_codes(buffer, chars):
    """Validate ASCII WinAnsi codes against name-keyed original CFF glyph IDs."""
    import io
    from fontTools.cffLib import CFFFontSet
    from fontTools.agl import UV2AGL
    font=CFFFontSet();font.decompile(io.BytesIO(buffer),None)
    if len(font.fontNames)!=1:raise ValueError('One original CFF font required')
    top=font[font.fontNames[0]]
    if (hasattr(top,'ROS') or not 1<=len(top.charset)<=256
            or top.charset[0]!='.notdef' or len(set(top.charset))!=len(top.charset)
            or list(top.FontMatrix)!=[.001,0,0,.001,0,0]):
        raise ValueError('Bounded standard-matrix name-keyed CFF required')
    for char in chars:
        if (not 32<=char[0]<=126 or type(char[1]) is not int or not 0<char[1]<len(top.charset)
                or top.charset[char[1]]!=UV2AGL.get(char[0])):
            raise ValueError('Native simple CFF glyph differs from ASCII WinAnsi mapping')
    return [c[0] for c in chars]


def cff_glyph_codes(buffer, chars):
    """Validate native CIDs against the retained CID-keyed CFF charset."""
    import io
    import re
    from fontTools.cffLib import CFFFontSet
    font = CFFFontSet()
    font.decompile(io.BytesIO(buffer), None)
    if len(font.fontNames) != 1:
        raise ValueError('One original CFF font required')
    top = font[font.fontNames[0]]
    if (not hasattr(top, 'ROS') or not 1 <= len(top.charset) <= 65536
            or top.charset[0] != '.notdef'
            or list(top.FontMatrix) != [.001, 0, 0, .001, 0, 0]):
        raise ValueError('Bounded standard-matrix CID-keyed CFF required')
    codes = [0]
    for name in top.charset[1:]:
        match = re.fullmatch(r'cid(\d{1,5})', name)
        if not match or not 1 <= int(match[1]) <= 65535:
            raise ValueError('Unsupported original CFF charset')
        codes.append(int(match[1]))
    if len(set(codes)) != len(codes):
        raise ValueError('Distinct original CFF character identifiers required')
    # MuPDF reports character identifiers, not charset ordinal positions, for
    # these CID-keyed fonts. Never reinterpret an unknown CID as a glyph index.
    supported = set(codes)
    if any(type(c[1]) is not int or c[1] not in supported for c in chars):
        raise ValueError('Native CFF character identifier outside original charset')
    return [c[1] for c in chars]


def grow(mask,steps=1):
    for _ in range(steps):
        padded=np.pad(mask,1);h,w=mask.shape
        mask=np.logical_or.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    return mask


def screen_span(page,span,*,zoom=6,max_pixels=1000000,isolate_glyphs=False):
    """Screen exact native glyph origins against rendered source; never certify source identity."""
    if zoom not in (6,12,24) or type(max_pixels) is not int or not 1<=max_pixels<=1000000:
        raise ValueError('Supported fixed raster scale and bounded raster budget required')
    if type(isolate_glyphs) is not bool:raise ValueError('Boolean glyph isolation required')
    version=INK_VERSION if isolate_glyphs else VERSION
    failure={'status':'withheld','visibility_verified':False,'version':version}
    rgb=_source_rgb(span)
    if (span.get('type')!=0 or span.get('opacity')!=1
            or span.get('layer') or rgb is None
            or not span['chars'] or len(span['chars'])>500
            or any(not 32<=c[0]<=126 for c in span['chars'])):
        return {**failure,'reason':'Unsupported font, rendering, layer or character convention'}
    if max(1-v for v in rgb)*255<48:
        return {**failure,'reason':'Original text colour has insufficient contrast over white'}
    fonts=[f for f in page.get_fonts(full=True) if f[3].split('+')[-1]==span.get('font')]
    if not fonts:return {**failure,'reason':'Source font resource not uniquely identified'}
    import hashlib
    if len(fonts)>128:return {**failure,'reason':'Source font resource budget exceeded'}
    candidates={}
    for font in fonts:
        buffer=page.parent.extract_font(font[0])[3]
        if len(buffer)>2000000:return {**failure,'reason':'Ambiguous or oversized source font'}
        digest=hashlib.sha256(buffer).hexdigest()
        entry=candidates.setdefault(digest,{'buffer':buffer,'fonts':[]})
        entry['fonts'].append(font)
        if len(candidates)>4 or sum(len(c['buffer']) for c in candidates.values())>4000000:
            return {**failure,'reason':'Source font alternative budget exceeded'}
    results=[]
    if any(not c['buffer'] and any(f[3].split('+')[-1]!='Helvetica' for f in c['fonts'])
           for c in candidates.values()):
        bound=_direct_winansi_resource(page,span,fonts)
        if bound is not None:
            font,proof=bound
            result=_screen_font(page,span,[font],b'',zoom=zoom,max_pixels=max_pixels,
                                isolate_glyphs=isolate_glyphs,original_resource_proof=proof)
            return {**result,'font_resource_resolution':proof}
    for digest,candidate in sorted(candidates.items()):
        result=_screen_font(page,span,candidate['fonts'],candidate['buffer'],
                            zoom=zoom,max_pixels=max_pixels,isolate_glyphs=isolate_glyphs)
        results.append((digest,candidate,result))
    if len(results)==1:return results[0][2]
    consistent=[r for _,_,r in results if r['status']=='raster_consistent_candidate']
    resolution={'basis':'original_embedded_font_glyph_raster_comparison',
        'candidate_count':len(results),'consistent_candidate_count':len(consistent),
        'identity_verified':False,'alternatives':[{'source_font_sha256':digest,
            'source_font_xrefs':sorted({f[0] for f in candidate['fonts']}),
            'status':result['status'],**({'reason':result['reason']} if 'reason' in result else {})}
            for digest,candidate,result in results]}
    if any('reason' in result for _,_,result in results):
        return {**failure,'reason':'Not all source font alternatives could be screened',
                'font_resource_resolution':resolution}
    if len(consistent)!=1:
        return {**failure,'reason':'Ambiguous source font raster support' if consistent else 'No source font has consistent glyph raster support',
                'font_resource_resolution':resolution}
    return {**consistent[0],'font_resource_resolution':resolution}


def _screen_font(page,span,fonts,font_buffer,*,zoom,max_pixels,isolate_glyphs,original_resource_proof=None):
    """Screen one retained original font; candidates are never substituted fonts."""
    import hashlib
    version=INK_VERSION if isolate_glyphs else VERSION
    failure={'status':'withheld','visibility_verified':False,'version':version}
    if (not font_buffer and original_resource_proof is None
            and (span.get('font')!='Helvetica' or any(f[2]!='Type1' for f in fonts))):
        return {**failure,'reason':'Unsupported unembedded font'}
    if page.cropbox.x0!=0 or page.cropbox.y0!=0:return {**failure,'reason':'Offset cropbox requires another raster-frame adapter'}
    directions={(1.,0.):0,(0.,-1.):90,(-1.,0.):180,(0.,1.):270}
    angle=directions.get(tuple(span['dir']))
    direction=span['dir']
    if (len(direction)!=2 or any(not math.isfinite(v) for v in direction)
            or abs(math.hypot(*direction)-1)>1e-5 or not 1<=span['size']<=40):
        return {**failure,'reason':'Unsupported glyph transform or size'}
    rotation_matrix=None if angle is not None else pymupdf.Matrix(math.degrees(math.atan2(-direction[1],direction[0])))
    clip=pymupdf.Rect(span['bbox'])+(-.5,-.5,.5,.5)
    if clip.width*clip.height*zoom*zoom>max_pixels:return {**failure,'reason':'Glyph raster budget exceeded'}
    rotation=page.rotation
    try:
        page.set_rotation(0)
        coloured=_source_rgb(span)!=(0.,0.,0.)
        source=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,
            colorspace=pymupdf.csRGB if coloured else pymupdf.csGRAY,alpha=False)
        if coloured:
            pixels=np.frombuffer(source.samples,np.uint8).reshape(source.height,source.width,3)
            source_dark=_colour_support(pixels,_source_rgb(span),100)
            source_ink=_colour_support(pixels,_source_rgb(span),200)
        else:
            source_gray=np.frombuffer(source.samples,np.uint8).reshape(source.height,source.width)
            source_dark=source_gray<100;source_ink=source_gray<200
        isolated=[]
        with pymupdf.open() as document:
            reference=document.new_page(width=page.rect.width,height=page.rect.height)
            font_name='nativeSource' if font_buffer else 'helv'
            direct_glyphs=False;glyph_codes=None;encoding='unicode';code_digits=4
            if original_resource_proof is not None:
                # Retain the original unembedded dictionary, encoding, widths
                # and descriptor. Both rasters use the same PDF renderer; no
                # replacement font program is chosen or inserted here.
                document.insert_pdf(page.parent,from_page=page.number,to_page=page.number)
                reference=document[-1];reference.set_rotation(0)
                font_name=fonts[0][4];glyph_codes=[c[0] for c in span['chars']]
                code_digits=2;direct_glyphs=True;encoding='source_unembedded_winansi_resource'
            elif font_buffer:
                xref=reference.insert_font(fontname=font_name,fontbuffer=font_buffer)
                if font_buffer[:4] in (b'\x00\x01\x00\x00',b'true'):
                    import re
                    kind,children=document.xref_get_key(xref,'DescendantFonts')
                    child=re.fullmatch(r'\[\s*(\d+)\s+0\s+R\s*\]',children) if kind=='array' else None
                    if (child and document.xref_get_key(xref,'Encoding')==('name','/Identity-H')
                            and document.xref_get_key(int(child[1]),'Subtype')==('name','/CIDFontType2')
                            and document.xref_get_key(int(child[1]),'CIDToGIDMap') in (('name','/Identity'),('null','null'))):
                        import io
                        from fontTools.ttLib import TTFont
                        with TTFont(io.BytesIO(font_buffer)) as native_font:
                            glyph_count=native_font['maxp'].numGlyphs
                        direct_glyphs=all(type(c[1]) is int and 0<=c[1]<min(glyph_count,65536) for c in span['chars'])
                        if direct_glyphs:
                            glyph_codes=[c[1] for c in span['chars']];encoding='source_glyph_ids'
                elif font_buffer[:1] == b'\x01':
                    simple=all(f[2]=='Type1' and f[5]=='WinAnsiEncoding'
                        and page.parent.xref_get_key(f[0],'Encoding')==('name','/WinAnsiEncoding') for f in fonts)
                    if simple:
                        try:glyph_codes=simple_cff_codes(font_buffer,span['chars'])
                        except (ValueError,KeyError,IndexError,AssertionError) as error:
                            return {**failure,'reason':str(error)}
                        # Copy the original font dictionary, widths, encoding and
                        # embedded stream. Never synthesize a replacement font.
                        document.insert_pdf(page.parent,from_page=page.number,to_page=page.number)
                        reference=document[-1];reference.set_rotation(0)
                        font_name=fonts[0][4];code_digits=2
                        direct_glyphs=True;encoding='source_type1_winansi_cff'
                    elif any(f[2] != 'Type0' or f[5] != 'Identity-H' for f in fonts):
                        return {**failure,'reason':'Original CFF font requires Identity-H native CID convention'}
                    import re
                    kind,children=document.xref_get_key(xref,'DescendantFonts')
                    child=re.fullmatch(r'\[\s*(\d+)\s+0\s+R\s*\]',children) if kind=='array' else None
                    if (not simple and child and document.xref_get_key(xref,'Encoding')==('name','/Identity-H')
                            and document.xref_get_key(int(child[1]),'Subtype')==('name','/CIDFontType0')):
                        try:
                            glyph_codes=cff_glyph_codes(font_buffer,span['chars'])
                        except (ValueError, KeyError, IndexError, AssertionError) as error:
                            return {**failure,'reason':str(error)}
                        direct_glyphs=True;encoding='source_cff_charset_cids'
            if direct_glyphs:
                # Preserve the actual PDF glyph IDs. CAD subset fonts often
                # have no Unicode cmap, so re-encoding their text loses ink.
                dx,dy=direction;commands=[]
                for character,code in zip(span['chars'],glyph_codes):
                    x,y=character[2]
                    commands.append(f'BT /{font_name} {span["size"]:.12g} Tf {dx:.12g} {-dy:.12g} {dy:.12g} {dx:.12g} {x:.12g} {reference.rect.height-y:.12g} Tm <{code:0{code_digits}x}> Tj ET')
                content=document.get_new_xref();document.update_object(content,'<<>>')
                document.update_stream(content,'\n'.join(commands).encode('ascii'))
                document.xref_set_key(reference.xref,'Contents',f'{content} 0 R')
                if isolate_glyphs:
                    if source.width*source.height*sum(c[0]!=32 for c in span['chars'])>20000000:
                        return {**failure,'reason':'Isolated glyph raster budget exceeded'}
                    # Thin CAD strokes may have no nearly-black pixels at the
                    # fixed raster scale. Match their antialiased ink using
                    # the same threshold in source and isolated reference.
                    support=grow(source_ink)
                    for i,(character,command) in enumerate(zip(span['chars'],commands)):
                        if character[0]==32:continue
                        document.update_stream(content,command.encode('ascii'))
                        glyph=reference.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
                        if (glyph.width,glyph.height,glyph.x,glyph.y)!=(source.width,source.height,source.x,source.y):
                            return {**failure,'reason':'Isolated glyph raster frames differ'}
                        reference_gray=np.frombuffer(glyph.samples,np.uint8).reshape(glyph.height,glyph.width)
                        mask=reference_gray<200
                        if coloured:support=_colour_match(pixels,_source_rgb(span),reference_gray)
                        isolated.append({'character_index':i,'core_pixels':int(mask.sum()),
                            'unsupported_core_pixels':int(np.count_nonzero(mask&~support))})
                    document.update_stream(content,'\n'.join(commands).encode('ascii'))
            else:
                if isolate_glyphs:return {**failure,'reason':'Isolated glyph screen requires original TrueType glyph IDs'}
                for character in span['chars']:
                    options={'rotate':angle} if rotation_matrix is None else {'morph':(pymupdf.Point(character[2]),rotation_matrix)}
                    reference.insert_text(character[2],chr(character[0]),fontname=font_name,fontsize=span['size'],color=(0,0,0),**options)
            expected=reference.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
        if (source.width,source.height,source.x,source.y)!=(expected.width,expected.height,expected.x,expected.y):
            return {**failure,'reason':'Source and reference raster frames differ'}
        a=np.frombuffer(expected.samples,np.uint8).reshape(expected.height,expected.width)
        core=a<60;support=grow(source_dark)
        if coloured:support=_colour_match(pixels,_source_rgb(span),a)
        ring=grow(a<200,2)&~grow(a<200)
        unexpected=int(np.count_nonzero(source_dark&ring));ring_count=int(np.count_nonzero(ring));glyphs=[]
        for i,c in enumerate(span['chars']):
            if c[0]==32:continue
            x0,y0,x1,y1=c[3]
            left=max(0,math.floor(x0*zoom-source.x));right=min(source.width,math.ceil(x1*zoom-source.x))
            top=max(0,math.floor(y0*zoom-source.y));bottom=min(source.height,math.ceil(y1*zoom-source.y))
            mask=core[top:bottom,left:right];count=int(np.count_nonzero(mask))
            missing=int(np.count_nonzero(mask&~support[top:bottom,left:right]))
            glyphs.append({'character_index':i,'core_pixels':count,'unsupported_core_pixels':missing})
        if isolate_glyphs:glyphs=isolated
        supported=bool(glyphs) and all(g['core_pixels']>=3 and g['unsupported_core_pixels']/g['core_pixels']<=.01 for g in glyphs)
        supported=supported and ring_count>0 and unexpected/ring_count<=.01
        return {'status':'raster_consistent_candidate' if supported else 'withheld','version':version,'visibility_verified':False,
                'source_font_sha256':hashlib.sha256(font_buffer).hexdigest() if font_buffer else None,
                'glyph_encoding':encoding,
                'source_font_xrefs':[f[0] for f in fonts],'zoom_pixels_per_pdf_point':zoom,'source_rotation_restored':rotation,'glyphs':glyphs,
                **({'source_font_program_embedded':False,'renderer_font_fallback_may_be_used':True,
                    'font_appearance_across_renderers_verified':False} if original_resource_proof is not None else {}),
                'ring_pixels':ring_count,'unexpected_dark_ring_pixels':unexpected,
                'pixel_position_tolerance':1,'max_unsupported_core_fraction_per_glyph':.01,'max_unexpected_dark_ring_fraction':.01,
                'source_colour_rgb':list(_source_rgb(span)),
                'source_colour_support':('original_rgb_over_white_projection' if coloured else 'legacy_black_grayscale'),
                **({'colour_residual_tolerance_rgb_levels':12,'max_colour_coverage':1.04,
                    'minimum_colour_contrast_rgb_levels':48} if coloured else {}),
                **({'glyph_support_basis':'isolated_original_glyph_ink',
                    'glyph_ink_grayscale_threshold':200,
                    **({'source_colour_match_tolerance_rgb_levels':12} if coloured else {'source_support_grayscale_threshold':200}),
                    'isolated_glyph_pixel_budget':20000000} if isolate_glyphs else {}),
                'limitations':['Raster consistency is a screen, not proof of semantic/material or as-built identity.',
                               'Opaque ASCII text with supported original colour/contrast and one raster-consistent original font candidate; no custom-font substitution.',
                               'A one-pixel position tolerance applies at the retained raster scale.']}
    finally:page.set_rotation(rotation)


def screen_architectural_span(page,span,*,zoom=6,max_pixels=1000000):
    """Recover native-box clipping only through each original glyph's own ink."""
    result=screen_span(page,span,zoom=zoom,max_pixels=max_pixels)
    if (result['status']=='withheld' and result.get('glyph_encoding') in ('source_glyph_ids','source_cff_charset_cids','source_type1_winansi_cff')
            and any(g['core_pixels']<3 for g in result.get('glyphs',[]))):
        isolated=screen_span(page,span,zoom=zoom,max_pixels=max_pixels,isolate_glyphs=True)
        return {**isolated,'native_character_box_screen':result}
    return result
