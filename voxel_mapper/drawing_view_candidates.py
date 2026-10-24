"""Automatic caption/gap layout candidates; source geometry is never clipped.

These packs remove hand-entered review rectangles, not physical acceptance.
"""
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import Polygon,shape,mapping
from shapely.strtree import STRtree

from .architectural_graph import build
from .architectural_view_layout import review as caption_review,VERSION as CAPTION_VERSION
from . import architectural_view_layout,caption_fragments,numbered_elevation_captions
from .building_raster_views import placements,render,VERSION as RASTER_VERSION
from .drawing_geometry import native_inverse
from .generation_cycles import atomic_json,file_hash
from .glyph_visibility import VERSION as GLYPH_VERSION,INK_VERSION
from .reconstruction_evidence_queue import digest

VERSION='automatic-drawing-view-candidates-v1'
DEFAULTS={'max_pages':16,'max_checks':100000,'render_width':800}
MAX_PACK_BYTES=128000000


def options(settings=None):
    settings={} if settings is None else settings
    if not isinstance(settings,dict) or set(settings)-set(DEFAULTS):raise ValueError('Known drawing-view settings required')
    result={**DEFAULTS,**settings}
    for key,limit in [('max_pages',128),('max_checks',100000),('render_width',1600)]:
        if type(result[key]) is not int or not 1<=result[key]<=limit:raise ValueError('Bounded drawing-view settings required')
    if result['render_width']<200:raise ValueError('Drawing-view render width must be at least 200')
    return result


def _extent(geometry,axis):
    points=list(geometry.envelope.exterior.coords) if geometry.envelope.geom_type=='Polygon' else list(geometry.envelope.coords)
    values=[x*axis[0]+y*axis[1] for x,y in points]
    return min(values),max(values)


def _raster(page,u):
    """Bounded composited page, aligned with this caption reading direction."""
    original=page.rotation;rotation={(1,0):0,(0,1):90,(-1,0):180,(0,-1):270}[u]
    try:
        page.set_rotation(rotation);scale=1800/max(page.rect.width,page.rect.height)
        pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csGRAY,alpha=False)
        if pix.width*pix.height>3244000:raise ValueError('Page layout raster budget exceeded')
        matrix=pymupdf.Matrix(1,0,0,1,pix.x,pix.y)*pymupdf.Matrix(1/scale,1/scale)*page.derotation_matrix*native_inverse(page)
        gray=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width)
        import hashlib
        proof={'gray_sha256':hashlib.sha256(gray.tobytes()).hexdigest(),'size_pixels':[pix.width,pix.height],
            'pixel_edge_to_pdf_native_matrix':list(matrix),'rotation_degrees':rotation,
            'white_threshold':250,'ignored_outer_border_pixels':3,'physical_separator_verified':False}
        return gray,matrix,proof
    finally:page.set_rotation(original)


def staggered_rows(rows, gray, pixel_native, axis, charge):
    """Merge disjoint caption columns only without a separating white row run.

The composited raster supplies a layout hint, never physical view boundaries.
Original caption rows and every tested pixel window remain in the receipts.
"""
    normal = (-axis[1], axis[0]); inverse = ~pixel_native
    merged = []; receipts = []
    for row in rows:
        charge()
        if not merged:
            merged.append(row); continue
        previous = merged[-1]
        old_intervals = [_extent(shape(c['label_geometry']), axis) for c in previous['captions']]
        new_intervals = [_extent(shape(c['label_geometry']), axis) for c in row['captions']]
        if any(min(a[1], b[1]) > max(a[0], b[0]) for a in old_intervals for b in new_intervals):
            merged.append(row); continue
        # A caption normally has a small blank margin above it. That margin
        # cannot separate its own artwork from another column's staggered title.
        margin = 2 * max(_extent(shape(c['label_geometry']), normal)[1]
            - _extent(shape(c['label_geometry']), normal)[0] for c in previous['captions'])
        low = min(previous['high'] + margin, row['low']); high = row['low']
        start = min(a[0] for a in old_intervals + new_intervals)
        end = max(a[1] for a in old_intervals + new_intervals)
        points = [pymupdf.Point(a * axis[0] + b * normal[0], a * axis[1] + b * normal[1]) * inverse
            for a in (start, end) for b in (low, high)]
        x0 = max(0, int(math.floor(min(p.x for p in points))))
        x1 = min(gray.shape[1], int(math.ceil(max(p.x for p in points))))
        y0 = max(0, int(math.floor(min(p.y for p in points))))
        y1 = min(gray.shape[0], int(math.ceil(max(p.y for p in points))))
        if x1 <= x0:
            merged.append(row); continue
        white = np.all(gray[y0:y1, x0:x1] >= 250, axis=1) if y1 > y0 else np.array([], dtype=bool)
        changes = np.diff(np.r_[False, white, False].astype(np.int8))
        runs = list(zip(np.flatnonzero(changes == 1).tolist(), np.flatnonzero(changes == -1).tolist()))
        step = math.hypot(pixel_native.c, pixel_native.d)
        separator = any((b - a) * step >= 8 for a, b in runs)
        receipts.append({'lower_caption_ids': [c['id'] for c in previous['captions']],
            'upper_caption_ids': [c['id'] for c in row['captions']],
            'original_caption_normal_intervals': [[previous['low'], previous['high']], [row['low'], row['high']]],
            'source_raster_window_pixels': [x0, y0, x1, y1],
            'white_row_runs_relative_pixels': [[a, b] for a, b in runs],
            'minimum_separator_pdf_points': 8, 'pdf_points_per_source_row': step,
            'lower_caption_margin_excluded_pdf_points': margin,
            'status': 'separate_caption_rows_with_white_corridor' if separator else 'staggered_disjoint_caption_row_hypothesis',
            'physical_separator_verified': False})
        if separator:
            merged.append(row)
        else:
            merged[-1] = {'low': previous['low'], 'high': row['high'],
                'captions': previous['captions'] + row['captions'], 'staggered': True}
    return merged, receipts


def candidates(page,sha,number,layout,sources,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded view work required')
    if (layout['version']!=CAPTION_VERSION or layout['document_sha256']!=sha or layout['page']!=number
            or layout.get('coordinate_frame')!='pdf_native_points_y_up'):
        raise ValueError('Same current source caption layout required')
    if len(sources)>20000 or len({s['id'] for s in sources})!=len(sources):raise ValueError('Unique bounded source objects required')
    if any(s['document_sha256']!=sha or s['page']!=number for s in sources):raise ValueError('Same source page objects required')
    geometries=[shape(s['geometry']) for s in sources]
    if any(g.is_empty or not g.is_valid for g in geometries):raise ValueError('Valid complete source objects required')
    if sum(len(g.wkb) for g in geometries)>16000000:raise ValueError('Bounded view geometry required')
    inverse=native_inverse(page);rotation=page.rotation
    try:
        page.set_rotation(0);r=page.rect
        frame=Polygon([tuple(pymupdf.Point(p)*inverse) for p in (r.tl,r.tr,r.br,r.bl)])
    finally:page.set_rotation(rotation)
    visible=[v for v in layout['view_captions'] if v['glyph_screen']['status']=='raster_consistent_candidate']
    families={};withheld=[];views=[];checks=0;raster_proofs=[];row_reviews=[]
    for caption in visible:
        u=caption['reading_direction_pdf_native']
        if abs(math.hypot(*u)-1)>1e-6 or any(abs(v)>1e-6 and abs(abs(v)-1)>1e-6 for v in u):
            withheld.append({'caption_id':caption['id'],'status':'unsupported_oblique_reading_direction'});continue
        families.setdefault(tuple(round(v) for v in u),[]).append(caption)
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise OverflowError('View assignment budget exhausted')
    try:
        for u,captions in sorted(families.items()):
            n=(-u[1],u[0]);amin,amax=_extent(frame,u);_,bmax=_extent(frame,n)
            gray,pixel_native,raster_proof=_raster(page,u);raster_proofs.append(raster_proof)
            native_pixel=~pixel_native
            rows=[]
            for caption in sorted(captions,key=lambda c:_extent(shape(c['label_geometry']),n)):
                low,high=_extent(shape(caption['label_geometry']),n)
                if rows and low<rows[-1]['high']:
                    rows[-1]['high']=max(high,rows[-1]['high']);rows[-1]['captions'].append(caption)
                else:rows.append({'low':low,'high':high,'captions':[caption]})
            rows, receipts = staggered_rows(rows, gray, pixel_native, u, charge)
            row_reviews.extend(receipts)
            upper=bmax
            for row in reversed(rows):
                height=(max(_extent(shape(c['label_geometry']),n)[1]-_extent(shape(c['label_geometry']),n)[0]
                    for c in row['captions']) if row.get('staggered') else row['high']-row['low'])
                lower=row['low']-2*height
                labels=sorted(row['captions'],key=lambda c:_extent(shape(c['label_geometry']),u))
                if upper<=lower:
                    withheld.extend({'caption_id':c['id'],'status':'overlapping_caption_row_bands'} for c in labels)
                    continue
                charge()
                points=[pymupdf.Point(a*u[0]+b*n[0],a*u[1]+b*n[1])*native_pixel for a in (amin,amax) for b in (lower,upper)]
                y0=max(3,int(math.floor(min(p.y for p in points))));y1=min(gray.shape[0]-3,int(math.ceil(max(p.y for p in points))))
                white=np.all(gray[y0:y1]>=250,axis=0) if y1>y0 else np.zeros(gray.shape[1],dtype=bool)
                white[:3]=False;white[-3:]=False
                edges=np.diff(np.r_[False,white,False].astype(np.int8));starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
                gaps=[]
                for start,end in zip(starts,ends):
                    left=pymupdf.Point(int(start),y0)*pixel_native;right=pymupdf.Point(int(end),y0)*pixel_native
                    a,b=sorted([left.x*u[0]+left.y*u[1],right.x*u[0]+right.y*u[1]])
                    if b-a>=8:gaps.append((a,b))
                cuts=[];proofs=[];failed=False
                for left,right in zip(labels,labels[1:]):
                    charge();end=_extent(shape(left['label_geometry']),u)[1];start=_extent(shape(right['label_geometry']),u)[0]
                    # Caption positions can be staggered relative to their
                    # artwork. A genuine white corridor may extend beyond a
                    # caption's horizontal start/end; only its intersection
                    # with the interval between the captions is relevant.
                    # This intersects layout evidence, never source geometry.
                    eligible=[(max(end,a),min(start,b)) for a,b in gaps
                              if min(start,b)-max(end,a)>=8]
                    if not eligible:failed=True;break
                    widest=max(b-a for a,b in eligible);best=[g for g in eligible if abs(g[1]-g[0]-widest)<1e-7]
                    if len(best)!=1:failed=True;break
                    cuts.append(sum(best[0])/2);proofs.append({'gap_candidates_pdf_points':eligible,'chosen_gap_pdf_points':best[0],
                        'original_white_corridors_pdf_points':[g for g in gaps if min(start,g[1])-max(end,g[0])>=8],
                        'between_caption_interval_pdf_points':[end,start],
                        'basis':'unique_widest_composited_white_corridor_intersection_layout_heuristic','physical_separator_verified':False})
                if failed:
                    withheld.extend({'caption_id':c['id'],'status':'column_gap_absent_or_competing'} for c in labels)
                    upper=lower;continue
                # Uncaptioned side panels (legends/title blocks) can be left
                # beyond an outer visible corridor. This remains a crop hint.
                first_start=_extent(shape(labels[0]['label_geometry']),u)[0]
                last_end=_extent(shape(labels[-1]['label_geometry']),u)[1]
                left_gaps=[g for g in gaps if g[1]<=first_start]
                right_gaps=[g for g in gaps if g[0]>=last_end]
                outer_left=max(left_gaps,key=lambda g:g[1]) if left_gaps else None
                outer_right=min(right_gaps,key=lambda g:g[0]) if right_gaps else None
                for role,gap in [('outer_left',outer_left),('outer_right',outer_right)]:
                    if gap is not None:proofs.append({'role':role,'chosen_gap_pdf_points':gap,
                        'basis':'adjacent_outer_composited_corridor_crop_hint','physical_separator_verified':False})
                boundaries=[sum(outer_left)/2 if outer_left else amin,*cuts,sum(outer_right)/2 if outer_right else amax]
                for i,caption in enumerate(labels):
                    a0,a1=boundaries[i:i+2]
                    def point(a,b):return (a*u[0]+b*n[0],a*u[1]+b*n[1])
                    region=Polygon([point(a0,lower),point(a1,lower),point(a1,upper),point(a0,upper)]).intersection(frame)
                    if region.is_empty or region.geom_type!='Polygon' or not region.covers(shape(caption['label_geometry'])):continue
                    inline=caption['printed_claim'].get('printed_scale_denominator');adjacent=caption.get('adjacent_scale_candidates',[])
                    scales=[inline] if inline is not None else [s['printed_denominator'] for s in adjacent]
                    conflict=inline is not None and any(s['printed_denominator']!=inline for s in adjacent)
                    usable=len(scales)==1 and not conflict
                    factor=scales[0]*.0254/72 if usable else None
                    transform=[u[0]*factor,u[1]*factor,n[0]*factor,n[1]*factor,-a0*factor,-lower*factor] if usable else None
                    views.append({'id':digest([VERSION,sha,number,caption['id'],mapping(region)]),'caption_id':caption['id'],
                        'caption_text':caption['text'],'printed_claim':caption['printed_claim'],'caption_evidence':caption,
                        'geometry':mapping(region),'coordinate_frame':'pdf_native_points_y_up',
                        'scope_basis':'caption_rows_and_composited_white_corridors_hypothesis','separator_evidence':proofs,
                        'nominal_scale_status':'unique_view_scale_claim' if usable else 'missing_ambiguous_or_conflicting_view_scale',
                        'nominal_metres_per_pdf_point':factor,'native_to_nominal_local_affine':transform,
                        'local_origin_basis':'candidate_cell_lower_left_display_origin_not_physical_datum',
                        'view_scope_verified':False,'scale_application_verified':False,'world_placement_eligible':False})
                upper=lower
        index=STRtree([shape(v['geometry']) for v in views]);membership=[]
        for source,g in zip(sources,geometries):
            contained=[];crossing=[]
            for k in index.query(g,predicate='intersects'):
                charge();k=int(k);region=shape(views[k]['geometry'])
                (contained if region.covers(g) else crossing).append(views[k]['id'])
            membership.append({'source_id':source['id'],'source_record_sha256':digest(source),
                'source_kind':source['kind'],'contained_candidate_ids':sorted(contained),'crossing_candidate_ids':sorted(crossing),
                'status':'one_whole_source_candidate' if len(contained)==1 and not crossing else
                    'crossing_or_competing_candidates' if contained or crossing else 'outside_candidates'})
        by_source={s['id']:s for s in sources}
        for view in views:
            view['whole_sources']=[{'id':m['source_id'],'kind':m['source_kind'],'record_sha256':m['source_record_sha256'],
                'geometry_pdf_native':by_source[m['source_id']]['geometry'],
                'geometry_nominal_local':mapping(affine_transform(shape(by_source[m['source_id']]['geometry']),view['native_to_nominal_local_affine']))
                    if view['native_to_nominal_local_affine'] is not None else None}
                for m in membership if m['status']=='one_whole_source_candidate' and m['contained_candidate_ids']==[view['id']]]
    except OverflowError:
        views=[];membership=[];withheld=[];row_reviews=[]
    return {'version':VERSION,'document_sha256':sha,'page':number,'source_layout_sha256':digest(layout),
        'source_objects_sha256':digest(sources),'status':'view_budget_withheld' if checks>max_checks else 'automatic_view_candidates_only',
        'views':views,'source_membership':membership,'withheld_captions':withheld,'checks':checks,
        'source_sheet_titles':layout['sheet_titles'],
        'layout_raster_evidence':raster_proofs,
        'caption_row_grouping_evidence':row_reviews,
        'counts':{'visible_captions':len(visible),'view_candidates':len(views),'withheld_captions':len(withheld),
                  'visible_sheet_title_claims':sum(t['glyph_screen']['status']=='raster_consistent_candidate' for t in layout['sheet_titles']),
                  **dict(Counter(m['status'] for m in membership))},
        'world_geometry_additions':0,'accepted_physical_components':0,'training_labels_generated':0,
        'limitations':['Layout gaps and caption bands are inferred review regions, not verified physical view boundaries.',
            'Whole source objects retain their original geometry; crossing or competing objects are never clipped into a view.',
            'Source objects can include context buildings, legends and annotations. Local coordinates are nominal drawing claims only.']}


def run(corpus,drawing_directory,output,*,settings=None):
    config=options(settings);drawing_directory=Path(drawing_directory);output=Path(output)
    extraction=json.loads((drawing_directory/'geometry-report.json').read_text());feed=drawing_directory/'geometry-candidates.jsonl'
    if file_hash(feed)!=extraction['file_sha256']['geometry']:raise ValueError('Source drawing feed changed')
    inventory=sorted(sha for (sha,) in corpus.db.execute("SELECT DISTINCT sha FROM downloads WHERE status='downloaded'"))
    for sha in inventory:
        if file_hash(corpus.root/'files'/(sha+'.pdf'))!=sha:raise ValueError('Original drawing changed')
    contract={'version':VERSION,'caption_version':CAPTION_VERSION,'raster_version':RASTER_VERSION,
        'glyph_version':GLYPH_VERSION,'glyph_ink_version':INK_VERSION,'pymupdf_version':pymupdf.VersionBind,
        'implementation_sha256':file_hash(Path(__file__)),
        'caption_implementation_sha256':file_hash(Path(architectural_view_layout.__file__)),
        'numbered_caption_implementation_sha256':file_hash(Path(numbered_elevation_captions.__file__)),
        'fragment_implementation_sha256':file_hash(Path(caption_fragments.__file__)),
        'options':config,'source_sha256':inventory,'drawing_feed_sha256':file_hash(feed),'drawing_contract':extraction['contract']}
    root=output/digest(contract)
    if root.exists():
        report=json.loads((root/'view-report.json').read_text())
        if report['contract']!=contract:raise ValueError('View input contract changed')
        for name,pin in report['output_sha256'].items():
            if file_hash(root/name)!=pin:raise ValueError('Drawing-view output changed')
        return {**report,'run_pages':0,'reused_pages':report['pages'],'directory':str(root)}
    source_pages={}
    with feed.open() as stream:
        for line in stream:
            source=json.loads(line);key=(source['document_sha256'],source['page'])
            source_pages.setdefault(key,[]).append({'id':source['id'],'document_sha256':key[0],'page':key[1],
                'kind':'native_vector','geometry':source['geometry'],'parent_record_sha256':digest(source)})
    root.mkdir(parents=True);reports=[];rendered=[];deferred=False;written_bytes=0
    for sha in inventory:
        path=corpus.root/'files'/(sha+'.pdf')
        with pymupdf.open(path) as document:
            for page in document:
                if len(reports)>=config['max_pages']:deferred=True;break
                number=page.number+1;graph=build([]);graph.update(document_sha256=sha,page=number)
                layout=caption_review(page,sha,number,graph)
                images=placements(page,sha,number)
                if images['status']!='source_image_placements_only':raise ValueError('Complete source image inventory required')
                sources=source_pages.get((sha,number),[])+[{**r,'kind':'raster_placement'} for r in images['placements']]
                result=candidates(page,sha,number,layout,sources,max_checks=config['max_checks'])
                page_bytes=len(json.dumps(result,allow_nan=False).encode())
                if page_bytes>32000000:raise ValueError('View page output budget exceeded')
                written_bytes+=page_bytes
                if written_bytes>MAX_PACK_BYTES:raise ValueError('View pack output budget exceeded')
                for view in result['views']:
                    name='views/'+view['id'];receipt=render({'version':RASTER_VERSION,'path':str(path),'sha256':sha,
                        'page':number,'bounds_pdf_native':list(shape(view['geometry']).bounds),
                        'width_pixels':config['render_width']},lambda p:p,root/name)
                    view['render']={'png':name+'/view.png','receipt':name+'/receipt.json','png_sha256':receipt['png_sha256']}
                    rendered.extend([name+'/view.png',name+'/receipt.json'])
                    written_bytes+=sum((root/p).stat().st_size for p in [name+'/view.png',name+'/receipt.json'])
                    if written_bytes>MAX_PACK_BYTES:raise ValueError('View pack output budget exceeded')
                if file_hash(path)!=sha:raise ValueError('Original drawing changed during view discovery')
                reports.append(result)
        if deferred:break
    atomic_json(root/'view-candidates.json',{'contract':contract,'pages':reports})
    if (root/'view-candidates.json').stat().st_size+sum((root/name).stat().st_size for name in rendered)>MAX_PACK_BYTES:
        raise ValueError('View pack output budget exceeded')
    if file_hash(feed)!=contract['drawing_feed_sha256']:raise ValueError('Drawing feed changed during view discovery')
    for sha in inventory:
        if file_hash(corpus.root/'files'/(sha+'.pdf'))!=sha:raise ValueError('Original drawing changed during view discovery')
    report={'contract':contract,'status':'partial_view_inventory' if deferred else 'automatic_view_candidates_only',
        'pages':len(reports),'views':sum(len(p['views']) for p in reports),
        'withheld_captions':sum(len(p['withheld_captions']) for p in reports),
        'nominal_scaled_views':sum(v['native_to_nominal_local_affine'] is not None for p in reports for v in p['views']),
        'sheet_title_claims':sum(p['counts']['visible_sheet_title_claims'] for p in reports),
        'output_sha256':{name:file_hash(root/name) for name in ['view-candidates.json',*rendered]},
        'world_geometry_additions':0,'accepted_physical_components':0,'training_labels_generated':0}
    atomic_json(root/'view-report.json',report)
    return {**report,'run_pages':len(reports),'reused_pages':0,'directory':str(root)}
