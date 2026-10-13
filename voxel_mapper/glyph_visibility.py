"""Bounded raster consistency screen for black native CAD glyphs using their original embedded font."""
import math
import numpy as np
import pymupdf

VERSION='source-font-glyph-raster-screen-v4'
INK_VERSION='source-font-isolated-glyph-screen-v3'


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
    if (span.get('type')!=0 or span.get('opacity')!=1
            or span.get('layer') or span.get('color') not in ((0.,0.,0.),(0.,))
            or not span['chars'] or len(span['chars'])>500
            or any(not 32<=c[0]<=126 for c in span['chars'])):
        return {**failure,'reason':'Unsupported font, rendering, layer or character convention'}
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


def _screen_font(page,span,fonts,font_buffer,*,zoom,max_pixels,isolate_glyphs):
    """Screen one retained original font; candidates are never substituted fonts."""
    import hashlib
    version=INK_VERSION if isolate_glyphs else VERSION
    failure={'status':'withheld','visibility_verified':False,'version':version}
    if not font_buffer and (span.get('font')!='Helvetica' or any(f[2]!='Type1' for f in fonts)):
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
        source=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
        source_gray=np.frombuffer(source.samples,np.uint8).reshape(source.height,source.width)
        isolated=[]
        with pymupdf.open() as document:
            reference=document.new_page(width=page.rect.width,height=page.rect.height)
            font_name='nativeSource' if font_buffer else 'helv'
            direct_glyphs=False;glyph_codes=None;encoding='unicode'
            if font_buffer:
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
                    if any(f[2] != 'Type0' or f[5] != 'Identity-H' for f in fonts):
                        return {**failure,'reason':'Original CFF font requires Identity-H native CID convention'}
                    import re
                    kind,children=document.xref_get_key(xref,'DescendantFonts')
                    child=re.fullmatch(r'\[\s*(\d+)\s+0\s+R\s*\]',children) if kind=='array' else None
                    if (child and document.xref_get_key(xref,'Encoding')==('name','/Identity-H')
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
                    commands.append(f'BT /{font_name} {span["size"]:.12g} Tf {dx:.12g} {-dy:.12g} {dy:.12g} {dx:.12g} {x:.12g} {reference.rect.height-y:.12g} Tm <{code:04x}> Tj ET')
                content=document.get_new_xref();document.update_object(content,'<<>>')
                document.update_stream(content,'\n'.join(commands).encode('ascii'))
                document.xref_set_key(reference.xref,'Contents',f'{content} 0 R')
                if isolate_glyphs:
                    if source.width*source.height*sum(c[0]!=32 for c in span['chars'])>20000000:
                        return {**failure,'reason':'Isolated glyph raster budget exceeded'}
                    # Thin CAD strokes may have no nearly-black pixels at the
                    # fixed raster scale. Match their antialiased ink using
                    # the same threshold in source and isolated reference.
                    support=grow(source_gray<200)
                    for i,(character,command) in enumerate(zip(span['chars'],commands)):
                        if character[0]==32:continue
                        document.update_stream(content,command.encode('ascii'))
                        glyph=reference.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
                        if (glyph.width,glyph.height,glyph.x,glyph.y)!=(source.width,source.height,source.x,source.y):
                            return {**failure,'reason':'Isolated glyph raster frames differ'}
                        mask=np.frombuffer(glyph.samples,np.uint8).reshape(glyph.height,glyph.width)<200
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
        b=np.frombuffer(source.samples,np.uint8).reshape(source.height,source.width)
        core=a<60;support=grow(b<100)
        ring=grow(a<200,2)&~grow(a<200)
        unexpected=int(np.count_nonzero((b<100)&ring));ring_count=int(np.count_nonzero(ring));glyphs=[]
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
                'ring_pixels':ring_count,'unexpected_dark_ring_pixels':unexpected,
                'pixel_position_tolerance':1,'max_unsupported_core_fraction_per_glyph':.01,'max_unexpected_dark_ring_fraction':.01,
                **({'glyph_support_basis':'isolated_original_glyph_ink',
                    'glyph_ink_grayscale_threshold':200,'source_support_grayscale_threshold':200,
                    'isolated_glyph_pixel_budget':20000000} if isolate_glyphs else {}),
                'limitations':['Raster consistency is a screen, not proof of semantic/material or as-built identity.',
                               'Only black ASCII text with a unit rotation and one raster-consistent original font candidate is supported; no custom-font substitution.',
                               'A one-pixel position tolerance applies at the retained raster scale.']}
    finally:page.set_rotation(rotation)


def screen_architectural_span(page,span,*,zoom=6,max_pixels=1000000):
    """Recover native-box clipping only through each original glyph's own ink."""
    result=screen_span(page,span,zoom=zoom,max_pixels=max_pixels)
    if (result['status']=='withheld' and result.get('glyph_encoding') in ('source_glyph_ids','source_cff_charset_cids')
            and any(g['core_pixels']<3 for g in result.get('glyphs',[]))):
        isolated=screen_span(page,span,zoom=zoom,max_pixels=max_pixels,isolate_glyphs=True)
        return {**isolated,'native_character_box_screen':result}
    return result
