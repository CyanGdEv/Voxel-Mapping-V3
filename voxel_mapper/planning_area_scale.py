"""Literal paper-qualified scale alternatives; no physical scale verification."""
import math
import re

from shapely.geometry import shape

from .building_spec import digest


def printed_scale(text):
    if not isinstance(text, str) or len(text)>100:return None
    match=re.fullmatch(r'(?:scale\s*)?1\s*[:/]\s*(\d{1,5})(?:\s*@\s*(A[0-5]))?',text.strip(),re.I)
    if not match or not 1<=int(match[1])<=10000:return None
    return {'printed_denominator':int(match[1]), 'paper_size':match[2].upper() if match[2] else None}


def resolve(caption, layout, measurements):
    """Keep the legacy inline/adjacent route; paper alternatives need one site title."""
    if caption.get('glyph_screen',{}).get('status')!='raster_consistent_candidate':
        raise ValueError('visible_complete_plan_caption_required')
    claim=caption['printed_claim']; adjacent=caption.get('adjacent_scale_candidates',[])
    inline=claim.get('printed_scale_denominator')
    if inline is not None or adjacent:
        values=[inline] if inline is not None else [r.get('printed_denominator') for r in adjacent]
        if (len(values)!=1 or type(values[0]) is not int or not 1<=values[0]<=10000
                or any(r.get('printed_denominator')!=values[0] or
                    r.get('glyph_screen',{}).get('status')!='raster_consistent_candidate' for r in adjacent)):
            raise ValueError('One visible unambiguous per-plan scale required')
        return {'printed_scale_denominator':values[0], 'basis':'inline_or_adjacent_printed_scale'}
    if claim.get('view_kind')!='sheet_title' or claim.get('plan_level_or_form') not in ('site','block'):
        raise ValueError('one_visible_plan_scale_required')
    u=caption['reading_direction_pdf_native'];n=(-u[1],u[0])
    def extent(geometry,axis):return [sum(p[k]*axis[k] for k in (0,1)) for p in shape(geometry).exterior.coords]
    a=extent(caption['label_geometry'],u);b=extent(caption['label_geometry'],n);height=max(b)-min(b)
    scales=[]
    for row in layout.get('page_scale_claims',[]):
        sa=extent(row['label_geometry'],u);sb=extent(row['label_geometry'],n)
        if 0<=min(b)-max(sb)<=6*height and abs(min(a)-min(sa))<=3*height:
            scales.append(row)
    if not 1<=len(scales)<=2:raise ValueError('one_or_two_paper_qualified_sheet_scales_required')
    papers=[]
    for row in scales:
        literal=printed_scale(row.get('text'))
        if (literal is None or not literal['paper_size'] or
                any(row.get(k)!=v for k,v in literal.items()) or
                row.get('glyph_screen',{}).get('status')!='raster_consistent_candidate' or
                sum(u[k]*row['reading_direction_pdf_native'][k] for k in (0,1))<1-1e-7):
            raise ValueError('visible_literal_paper_qualified_scales_required')
        papers.append(row['paper_size'])
    if len(set(papers))!=len(papers):raise ValueError('duplicate_paper_scale_claims_withheld')
    sizes={'A0':(841,1189),'A1':(594,841),'A2':(420,594),'A3':(297,420),'A4':(210,297),'A5':(148,210)}
    dimensions=measurements.get('effective_page_dimensions_mm',[])
    if len(dimensions)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in dimensions):
        raise ValueError('original_iso_paper_dimensions_required')
    matches=[name for name,size in sizes.items() if all(abs(a-b)<=1.5 for a,b in zip(dimensions,size))]
    if matches!=measurements.get('matching_paper_sizes'):
        raise ValueError('original_paper_receipt_mismatch')
    selected=[r for r in scales if matches==[r['paper_size']]]
    if len(selected)!=1:raise ValueError('one_printed_scale_matching_original_paper_required')
    selected=selected[0];denominator=selected['printed_denominator']
    for row in scales:
        expected=denominator*2**((int(row['paper_size'][1])-int(selected['paper_size'][1]))/2)
        if not math.isclose(row['printed_denominator'],expected,rel_tol=.01):
            raise ValueError('inconsistent_iso_paper_scale_alternatives')
    return {'printed_scale_denominator':denominator,'basis':'original_page_iso_paper_match',
        'selected_paper_size':selected['paper_size'], 'selected_scale_sha256':digest(selected),
        'scale_alternatives_sha256':digest(scales), 'physical_scale_verified':False}
