"""Native elevation captions and material enclosures; no plan or height projection."""
from collections import Counter
import re
import pymupdf
from shapely.geometry import Polygon,shape,mapping
from shapely.strtree import STRtree
from .drawing_geometry import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span

VERSION='elevation-interpretation-v1'
MATERIALS={'brick','stone','timber','render','tiles','slate','metal','concrete'}


def caption(text):
    if not isinstance(text,str) or len(text)>500:return None
    # Match exact caption grammars only, preserving original text separately.
    value=re.sub(r'\s+','',text.lower())
    match=re.fullmatch(r'(north|south|east|west)(?:range(courtyard|gable)?\((north|south|east|west)\))?elevation(?:[\'’]as(existing|proposed)[\'’])?(?:\|1:(\d{1,5}))?',value)
    if match:
        denominator=int(match[5]) if match[5] else None
        if denominator is not None and not 1<=denominator<=10000:return None
        return {'kind':'view_caption','range_or_direction':match[1],
            'range_part':match[2],'view_direction':match[3] or match[1],
            'printed_state':match[4] or 'unspecified','printed_scale_denominator':denominator}
    match=re.fullmatch(r'(existing|proposed)elevations(?:sheet)?(?:\d+of\d+)?',value)
    if not match:match=re.fullmatch(r'courtyardelevations[\'’]as(existing|proposed)[\'’]',value)
    if match:return {'kind':'sheet_title','printed_state':match[1]}
    return None


def review_page(page,sha,number,polygons,scale_review):
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Elevation text budget exceeded')
    runs=list(label_runs(traces));captions=[];materials=[];inverse=native_inverse(page)
    def retained(run):
        rect=pymupdf.Rect(run['bbox'])
        corners=[pymupdf.Point(x,y)*inverse for x,y in [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
        return {'text':''.join(chr(c[0]) for c in run['chars']).strip(),
            'label_geometry':mapping(Polygon([(p.x,p.y) for p in corners])),
            'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],
            'glyph_screen':screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)}
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip();printed=caption(text)
        if printed:
            if len(captions)>=32:raise ValueError('Elevation caption budget exceeded')
            captions.append({**retained(run),'printed_caption':printed})
    if not captions:return None
    if (len(polygons)>20000 or any(r['document_sha256']!=sha or r['page']!=number
            or r.get('coordinate_frame')!='pdf_native_points_y_up' for r in polygons)
            or scale_review.get('document_sha256')!=sha or scale_review.get('page')!=number):
        raise ValueError('Source-bound elevation page required')
    visible=[r for r in captions if r['glyph_screen']['status']=='raster_consistent_candidate']
    states={r['printed_caption']['printed_state'] for r in visible if r['printed_caption']['printed_state']!='unspecified'}
    # Mixed plan/elevation sheets need independently delimited views.
    plan_labels=[ ''.join(chr(c[0]) for c in r['chars']).strip() for r in runs
        if re.fullmatch(r'(?:existing|proposed)?(?:(?:ground|first|second)?floorplan|roofplan)(?:[\'’]as(?:existing|proposed)[\'’])?(?:\|1:\d+)?',
                        re.sub(r'\s+','', ''.join(chr(c[0]) for c in r['chars']).lower()))]
    usable=bool(visible) and not plan_labels
    candidates={r['id']:r for r in polygons if r['geometry']['type']=='Polygon' and r.get('extraction_kind')!='linework_envelopes'}
    if len(candidates)!=sum(r['geometry']['type']=='Polygon' and r.get('extraction_kind')!='linework_envelopes' for r in polygons):
        raise ValueError('Unique elevation enclosure identities required')
    geometries=[shape(r['geometry']) for r in candidates.values()];ids=list(candidates)
    if any(g.is_empty or not g.is_valid for g in geometries):raise ValueError('Valid elevation enclosures required')
    index=STRtree(geometries)
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        if text.lower() not in MATERIALS:continue
        if len(materials)>=500:raise ValueError('Elevation material-label budget exceeded')
        row=retained(run);row.update(printed_material=text.lower(),candidate_id=None,association_status='view_scope_withheld')
        if usable and row['glyph_screen']['status']=='raster_consistent_candidate':
            label=shape(row['label_geometry'])
            hits=[int(i) for i in index.query(label,predicate='intersects') if geometries[int(i)].contains(label)]
            row['association_status']='no_complete_enclosure' if not hits else 'ambiguous_enclosures'
            if len(hits)==1:row.update(candidate_id=ids[hits[0]],association_status='unique_complete_elevation_material_enclosure')
        elif row['glyph_screen']['status']!='raster_consistent_candidate':row['association_status']='glyph_screen_withheld'
        materials.append(row)
    associations=[{'candidate_id':identifier,'source_candidate':candidates[identifier],
        'material_label_indices':[i for i,r in enumerate(materials) if r['candidate_id']==identifier],
        'printed_materials':sorted({r['printed_material'] for r in materials if r['candidate_id']==identifier}),
        'material_assignment_verified':False,
        'physical_identity_verified':False,'view_projection_verified':False,'height_application_verified':False,
        'world_geometry_additions':0}
        for identifier in sorted({r['candidate_id'] for r in materials if r['candidate_id'] is not None})]
    view_scales=sorted({r['printed_caption']['printed_scale_denominator'] for r in visible
        if r['printed_caption'].get('printed_scale_denominator') is not None})
    return {'version':VERSION,'document_sha256':sha,'page':number,
        'status':'elevation_material_candidates_only' if usable else 'elevation_view_scope_withheld',
        'captions':captions,'mixed_plan_labels':plan_labels,'printed_state':next(iter(states)) if len(states)==1 else 'unspecified_or_conflicting',
        'material_labels':materials,'material_region_associations':associations,
        'counts':{'captions':len(captions),'visible_captions':len(visible),'material_labels':len(materials),
            'bound_material_labels':sum(r['candidate_id'] is not None for r in materials),'material_regions':len(associations)},
        'printed_material_counts':dict(Counter(r['printed_material'] for r in materials)),
        'view_scale_denominators':view_scales,'page_scale_review':scale_review,
        'scale_scope_status':'page_view_scale_conflict' if view_scales and scale_review.get('denominators')
            and set(view_scales)!=set(scale_review['denominators']) else 'verified_view_scope_required',
        'scale_application_verified':False,'physical_identity_verified':False,'height_application_verified':False,
        'world_geometry_additions':0,
        'limitations':['Elevation enclosures remain native drawing regions, not horizontal building footprints.',
            'Caption scales cannot be applied until each elevation view has a verified spatial scope.',
            'Material labels do not establish physical wall/roof identity, openings or measured height.',
            'Existing/proposed captions are retained claims, not current as-built verification.',
            'Plan correspondence, vertical datum and terrain registration remain unresolved.']}
