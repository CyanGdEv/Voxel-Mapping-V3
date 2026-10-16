"""Join exact native line fragments for caption reading, never source geometry."""
import re
from shapely.geometry import box,mapping
from shapely.strtree import STRtree


VERSION='native-caption-fragments-v1'


def collect(page,runs,parse,retain):
    if len(runs)>20000:return [],'caption_fragment_budget_withheld',[]
    index=STRtree([box(*r['bbox']) for r in runs]);rows=[];lines=0;contexts=[];checks=0
    for block in page.get_text('dict',flags=0)['blocks']:
        for line in block.get('lines',[]):
            lines+=1
            if lines>20000:return [],'caption_fragment_budget_withheld',[]
            text=''.join(s['text'] for s in line['spans']).strip();claim=parse(text)
            if not claim and not re.search(r'\b(?:plan|elevation|section)s?\b',text,re.I):continue
            region=box(*line['bbox']).buffer(.1,join_style=2)
            group=[runs[int(k)] for k in index.query(region,predicate='intersects')
                   if region.covers(box(*runs[int(k)]['bbox']))]
            checks+=len(group)
            if checks>100000:return [],'caption_fragment_budget_withheld',[]
            if not 2<=len(group)<=16:continue
            direction=tuple(line['dir']);perpendicular=(-direction[1],direction[0])
            group.sort(key=lambda r:sum(r['chars'][0][2][k]*direction[k] for k in (0,1)))
            if any(not r['chars'] or r['font']!=group[0]['font'] or tuple(r['dir'])!=direction for r in group):continue
            sizes=[r['size'] for r in group]
            if min(sizes)<=0 or max(sizes)/min(sizes)>1.02:continue
            origin=group[0]['chars'][0][2]
            if any(abs(sum((r['chars'][0][2][k]-origin[k])*perpendicular[k] for k in (0,1)))>.25 for r in group):continue
            native=''.join(''.join(chr(c[0]) for c in r['chars']) for r in group)
            if re.sub(r'\s+','',native)!=re.sub(r'\s+','',text):continue
            contexts.append({'text':text,'fragment_keys':[
                [r['trace_indices'],r['character_indices']] for r in group],
                'whole_native_line_caption_supported':bool(claim)})
            if not claim:continue
            fragments=[retain(r) for r in group]
            geometries=[f['label_geometry'] for f in fragments]
            from shapely.geometry import shape
            bounds=[shape(g).bounds for g in geometries]
            envelope=box(min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds))
            visible=all(f['glyph_screen']['status']=='raster_consistent_candidate' for f in fragments)
            rows.append(({'text':text,'label_geometry':mapping(envelope),
                'reading_direction_pdf_native':fragments[0]['reading_direction_pdf_native'],
                'caption_fragments':fragments,'fragment_contract':VERSION,
                'text_basis':'native_line_exact_fragment_character_coverage_whitespace_only_normalization',
                'glyph_screen':{'status':'raster_consistent_candidate' if visible else 'withheld',
                    'basis':'all_original_native_fragments_screened_individually','visibility_verified':False,
                    'fragment_count':len(fragments)}},claim))
            if len(rows)>128 or len(contexts)>20000:return [],'caption_fragment_budget_withheld',[]
    return rows,'native_caption_fragments_reviewed',contexts
