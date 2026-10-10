"""Bounded raster consistency screen for black native CAD glyphs using their original embedded font."""
import math
import numpy as np
import pymupdf

VERSION='source-font-glyph-raster-screen-v1'


def grow(mask,steps=1):
    for _ in range(steps):
        padded=np.pad(mask,1);h,w=mask.shape
        mask=np.logical_or.reduce([padded[y:y+h,x:x+w] for y in range(3) for x in range(3)])
    return mask


def screen_span(page,span,*,zoom=6,max_pixels=1000000):
    """Screen exact native glyph origins against rendered source; never certify source identity."""
    if zoom!=6 or type(max_pixels) is not int or not 1<=max_pixels<=1000000:
        raise ValueError('Fixed six-pixel scale and bounded raster budget required')
    failure={'status':'withheld','visibility_verified':False,'version':VERSION}
    if (span.get('type')!=0 or span.get('opacity')!=1
            or span.get('layer') or span.get('color') not in ((0.,0.,0.),(0.,))
            or not span['chars'] or len(span['chars'])>500
            or any(not 32<=c[0]<=126 for c in span['chars'])):
        return {**failure,'reason':'Unsupported font, rendering, layer or character convention'}
    fonts=[f for f in page.get_fonts(full=True) if f[3].split('+')[-1]==span.get('font')]
    if not fonts:return {**failure,'reason':'Source font resource not uniquely identified'}
    import hashlib
    buffers=[page.parent.extract_font(f[0])[3] for f in fonts]
    if len({hashlib.sha256(b).hexdigest() for b in buffers})!=1 or len(buffers[0])>2000000:
        return {**failure,'reason':'Ambiguous or oversized source font'}
    font_buffer=buffers[0]
    if not font_buffer and (span.get('font')!='Helvetica' or any(f[2]!='Type1' for f in fonts)):
        return {**failure,'reason':'Unsupported unembedded font'}
    if page.cropbox.x0!=0 or page.cropbox.y0!=0:return {**failure,'reason':'Offset cropbox requires another raster-frame adapter'}
    directions={(1.,0.):0,(0.,-1.):90,(-1.,0.):180,(0.,1.):270}
    angle=directions.get(tuple(span['dir']))
    if angle is None or not 1<=span['size']<=40:return {**failure,'reason':'Unsupported glyph transform or size'}
    clip=pymupdf.Rect(span['bbox'])+(-.5,-.5,.5,.5)
    if clip.width*clip.height*zoom*zoom>max_pixels:return {**failure,'reason':'Glyph raster budget exceeded'}
    rotation=page.rotation
    try:
        page.set_rotation(0)
        source=page.get_pixmap(matrix=pymupdf.Matrix(zoom,zoom),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
        with pymupdf.open() as document:
            reference=document.new_page(width=page.rect.width,height=page.rect.height)
            font_name='nativeSource' if font_buffer else 'helv'
            if font_buffer:reference.insert_font(fontname=font_name,fontbuffer=font_buffer)
            for character in span['chars']:
                reference.insert_text(character[2],chr(character[0]),fontname=font_name,fontsize=span['size'],rotate=angle,color=(0,0,0))
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
        supported=bool(glyphs) and all(g['core_pixels']>=3 and g['unsupported_core_pixels']/g['core_pixels']<=.01 for g in glyphs)
        supported=supported and ring_count>0 and unexpected/ring_count<=.01
        return {'status':'raster_consistent_candidate' if supported else 'withheld','version':VERSION,'visibility_verified':False,
                'source_font_sha256':hashlib.sha256(font_buffer).hexdigest() if font_buffer else None,
                'source_font_xrefs':[f[0] for f in fonts],'zoom_pixels_per_pdf_point':zoom,'source_rotation_restored':rotation,'glyphs':glyphs,
                'ring_pixels':ring_count,'unexpected_dark_ring_pixels':unexpected,
                'pixel_position_tolerance':1,'max_unsupported_core_fraction_per_glyph':.01,'max_unexpected_dark_ring_fraction':.01,
                'limitations':['Raster consistency is a screen, not proof of semantic/material or as-built identity.',
                               'Only black ASCII text in cardinal directions with one identified native font is supported; no custom-font substitution.',
                               'A one-pixel position tolerance applies at six pixels per PDF point.']}
    finally:page.set_rotation(rotation)
