"""User-default rock boundaries around non-paved gaps, separate from source truth."""
from concurrent.futures import CancelledError
from html import escape
import hashlib
import json
import math
import re
from pathlib import Path

import pymupdf
from shapely.geometry import Polygon,LineString,shape,mapping
from shapely.ops import unary_union

from .building_spec import digest
from . import planning_hatch_regions

VERSION='planning-gap-boundaries-v1'
POLICY_PATH=Path(__file__).with_name('data')/'planning-gap-boundary-policy.json'
LIMITS={'max_segment_checks':100000,'max_union_work':8000000,'max_paving_regions':512,'max_input_points':100000,'max_gaps':512,
        'max_gap_points':100000,'max_claim_checks':10000,'max_output_bytes':8000000}
KINDS={'rock','wall','fence','water_edge','building','opening','unknown'}


def policy():
    value=json.loads(POLICY_PATH.read_text())
    expected={'version':'planning-gap-boundary-policy-v1','policy_origin':'user_instruction',
        'default_gap_boundary_material':'rock','default_gap_is_boundary':True,
        'explicit_claims_override_default':True,'fill_gap_interior':False,
        'infer_boundary_height_or_width':False,'use_assumptions_as_training_truth':False}
    if value!=expected:raise ValueError('Supported explicit gap-boundary policy required')
    return value


def _polygon(value):
    g=shape(value)
    if g.geom_type not in ('Polygon','MultiPolygon') or g.is_empty or not g.is_valid or g.has_z or not all(math.isfinite(v) for v in g.bounds):
        raise ValueError('Finite valid original gap/paving polygons required')
    return g


def _points(g):
    return sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
        for p in (list(g.geoms) if g.geom_type=='MultiPolygon' else [g]))



def _partition_boundary(line,supports,work,limit):
    """Partition each original edge parametrically; do not snap the gap contour."""
    from shapely.geometry import MultiLineString
    from shapely.ops import linemerge
    rock_parts=[];explicit_parts=[];identifiers=set()
    coordinates=list(line.coords)
    for a,b in zip(coordinates,coordinates[1:]):
        dx=b[0]-a[0];dy=b[1]-a[1];denominator=dx*dx+dy*dy
        if denominator==0:continue
        edge=LineString([a,b]);intervals=[]
        for ids,support in supports:
            work['checks']+=1
            if work['checks']>limit:raise ValueError('Gap boundary segment check budget exceeded')
            if not edge.envelope.intersects(support.envelope):continue
            cut=edge.intersection(support)
            parts=list(cut.geoms) if cut.geom_type in ('MultiLineString','GeometryCollection') else [cut]
            for part in parts:
                if part.geom_type not in ('LineString','LinearRing') or part.length==0:continue
                ts=[max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/denominator)) for p in part.coords]
                low,high=min(ts),max(ts)
                if high>low:intervals.append((low,high));identifiers.update(ids)
        intervals.sort();merged=[]
        for low,high in intervals:
            if merged and low<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],high))
            else:merged.append((low,high))
        def point(t):return a if t==0 else b if t==1 else (a[0]+t*dx,a[1]+t*dy)
        cursor=0.
        for low,high in merged:
            if low>cursor:rock_parts.append([point(cursor),point(low)])
            explicit_parts.append([point(low),point(high)]);cursor=high
        if cursor<1:rock_parts.append([point(cursor),b])
    def joined(parts):return linemerge(MultiLineString(parts)) if parts else LineString()
    explicit=joined(explicit_parts);overrides=[]
    if not explicit.is_empty:
        overrides=[{'source_claim_ids':sorted(identifiers),'geometry_pdf_native':json.loads(json.dumps(mapping(explicit))),
            'scope':'suppress rock assumption near explicit building boundaries',
            'source_association_margin_pdf_points':.5}]
    return joined(rock_parts),overrides

def review(paving,layout=None,*,source_claims=None,overrides=None,options=None,cancelled=lambda:False):
    """Enclosed gaps inherit rock edging unless an explicit claim overrides it.

    Islands keep their interiors. Geometry comes from original paving holes;
    the material is a user assumption and never a generated training label.
    """
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):raise ValueError('Known gap-boundary limits required')
    limits={**LIMITS,**options}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):raise ValueError('Lower-only gap-boundary limits required')
    if not isinstance(paving,dict) or paving.get('version')!=planning_hatch_regions.VERSION:
        raise ValueError('Current same-page source paving review required')
    sha=paving.get('document_sha256');number=paving.get('page')
    if paving.get('coordinate_frame')!='pdf_native_points_y_up' or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or type(number) is not int or number<1:
        raise ValueError('Pinned native source paving frame required')
    source_claims=[] if source_claims is None else source_claims
    if not isinstance(source_claims,list) or len(source_claims)>128:raise ValueError('Bounded explicit source claims required')
    for claim in source_claims:
        if (not isinstance(claim,dict) or claim.get('document_sha256')!=sha or claim.get('page')!=number
                or claim.get('role')!='building' or claim.get('glyph_screen',{}).get('status')!='raster_consistent_candidate'):
            raise ValueError('Visible same-page source building claims required')
        _polygon(claim['label_geometry_pdf_native'])
    setting=policy();overrides={} if overrides is None else overrides
    if not isinstance(overrides,dict) or len(overrides)>limits['max_gaps']:raise ValueError('Bounded explicit boundary overrides required')
    for identifier,claim in overrides.items():
        if not isinstance(identifier,str) or not isinstance(claim,dict) or set(claim)!={'kind','evidence'} or claim['kind'] not in KINDS or not isinstance(claim['evidence'],str) or not 1<=len(claim['evidence'])<=1024:
            raise ValueError('Explicit boundary kind and evidence required')
    result={'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'source_building_claims_sha256':digest(source_claims),'source_paving_review_sha256':digest(paving),'source_layout_sha256':digest(layout) if layout is not None else None,'policy':setting,'policy_sha256':digest(setting),'limits':limits,
        'analysis_complete':True,'status':'user_assumed_gap_boundary_review','records':[],'source_building_claims':source_claims,
        'gap_scope':'enclosed source paving holes; open corridors are not closed or bridged',
        'physical_identity_verified':False,'world_placement_eligible':False,'world_geometry_additions':0,
        'training_labels_generated':0,'model_weights_updated':False}
    def check():
        if cancelled():raise CancelledError('Gap boundary review cancelled')
    def fail(reason):
        result.update(analysis_complete=False,status='gap_boundary_review_withheld',reason=str(reason)[:512],records=[],source_building_claims=[])
        result.pop('summary',None);return result
    check()
    if not paving.get('analysis_complete'):return fail('Complete source paving review required')
    try:
        rows=[r for r in paving.get('records',[]) if r.get('legend_claim')]
        if len(rows)>limits['max_paving_regions']:return fail('Gap paving input budget exceeded')
        geometries=[];points=0
        for row in rows:
            check();g=_polygon(row['geometry']);points+=_points(g)
            if points>limits['max_input_points']:return fail('Gap input point budget exceeded')
            geometries.append(g)
        buildings=[]
        if layout is not None:
            if (layout.get('document_sha256')!=sha or layout.get('page')!=number
                    or layout.get('version')!='planning-area-layout-v1'):
                raise ValueError('Same native page layout claims required')
            if len(layout.get('candidates',[]))>128:return fail('Gap source layout claim budget exceeded')
            if layout.get('analysis_complete'):
                for candidate in layout.get('candidates',[]):
                    if candidate.get('role')=='building':
                        g=_polygon(candidate['geometry_pdf_native']);points+=_points(g)
                        if points>limits['max_input_points']:return fail('Gap input point budget exceeded')
                        buildings.append((candidate['id'],g))
        whites=[r for r in paving.get('records',[]) if r.get('paint_kind')=='solid'
            and r.get('fill_opacity')==1 and r.get('solid_colour_space') in ('/DeviceRGB','/DeviceGray')
            and all(v==1 for v in r.get('solid_colour_components',[])) and r.get('solid_colour_components')]
        for claim in source_claims:
            label=_polygon(claim['label_geometry_pdf_native'])
            for white in whites:
                check();g=_polygon(white['geometry']);points+=_points(g)
                if points>limits['max_input_points']:return fail('Gap source claim point budget exceeded')
                if g.covers(label):buildings.append(('label:'+claim['id']+':paint:'+str(white['paint_operation_index']),g))
        union_work=0
        for i,a in enumerate(geometries):
            for b in geometries[i+1:]:
                check()
                if a.envelope.intersects(b.envelope):union_work+=_points(a)*_points(b)
                if union_work>limits['max_union_work']:return fail('Gap paving union work budget exceeded')
        united=unary_union(geometries);parts=list(united.geoms) if united.geom_type=='MultiPolygon' else [united]
        grouped={};dedup_checks=0
        for identifier,g in buildings:
            bucket=grouped.setdefault(tuple(g.bounds),[]);match=None
            for ids,other in bucket:
                dedup_checks+=1
                if dedup_checks>limits['max_claim_checks']:return fail('Gap source claim grouping budget exceeded')
                if g.equals(other):match=ids;break
            if match is None:bucket.append(([identifier],g.normalize()))
            else:match.append(identifier)
        building_supports=[(ids,g,g.buffer(.5,join_style=2)) for bucket in grouped.values() for ids,g in bucket]
        gaps=[];gap_points=0;checks=dedup_checks;segment_work={'checks':0}
        for part in parts:
            check()
            if part.geom_type!='Polygon':continue
            for ring in part.interiors:
                check();g=Polygon(ring);gap_points+=len(ring.coords)
                if gap_points>limits['max_gap_points']:return fail('Gap boundary point budget exceeded')
                if len(gaps)>=limits['max_gaps']:return fail('Gap candidate budget exceeded')
                identifier=digest([VERSION,sha,number,g.normalize().wkb_hex]);explicit=overrides.get(identifier)
                sources=[];segment_supports=[];line=LineString(ring.coords)
                for building_ids,building,support in building_supports:
                    check();checks+=1
                    if checks>limits['max_claim_checks']:return fail('Gap explicit-claim check budget exceeded')
                    coverage=g.intersection(building).area/g.area
                    if coverage>=.9:sources.extend(building_ids)
                    edge=line.intersection(support)
                    if edge.length>0:segment_supports.append((building_ids,support))
                kind=explicit['kind'] if explicit else 'building' if sources else 'rock'
                basis='explicit_override' if explicit else 'source_building_claim' if sources else 'user_default_assumption'
                assumed_line=line;segments=[]
                if basis=='user_default_assumption' and segment_supports:
                    assumed_line,segments=_partition_boundary(line,segment_supports,segment_work,limits['max_segment_checks'])
                    if assumed_line.is_empty:kind='building';basis='source_boundary_claim'
                gaps.append({'id':identifier,'gap_geometry_pdf_native':json.loads(json.dumps(mapping(g))),
                    'boundary_geometry_pdf_native':json.loads(json.dumps(mapping(LineString(ring.coords)))),
                    'assumed_rock_geometry_pdf_native':json.loads(json.dumps(mapping(assumed_line))) if basis=='user_default_assumption' else None,
                    'source_boundary_overrides':segments,'boundary_kind':kind,'material':'rock' if kind=='rock' else None,
                    'is_boundary':kind!='opening','classification_basis':basis,
                    'assumed':basis=='user_default_assumption','explicit_override':explicit,
                    'source_building_claim_ids':sources,'source_building_override_minimum_gap_area_fraction':.9,'interior_filled_with_rock':False,
                    'height_m':None,'width_m':None,'physical_identity_verified':False,
                    'navigation_policy':'source_opening_claim' if kind=='opening' else 'avoid_crossing_boundary',
                    'world_placement_eligible':False,'training_label_eligible':False})
        gaps.sort(key=lambda r:r['id'])
        if set(overrides)-{r['id'] for r in gaps}:raise ValueError('Explicit override must name a current source gap')
        result.update(records=gaps,summary={'enclosed_gaps':len(gaps),
            'assumed_rock_boundaries':sum(r['assumed'] and r['boundary_kind']=='rock' for r in gaps),
            'explicit_boundary_claims':sum(not r['assumed'] for r in gaps),
            'gaps_with_explicit_boundary_segments':sum(bool(r['source_boundary_overrides']) for r in gaps)},work={'input_points':points,'gap_points':gap_points,'claim_checks':checks,'union_work':union_work,'segment_checks':segment_work['checks']})
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:return fail('Gap boundary output budget exceeded')
        check();return result
    except (ValueError,RuntimeError,OverflowError) as error:return fail(error)



def page_building_claims(page,paving,*,cancelled=lambda:False):
    """Visible literal building labels, for suppressing the rock default only."""
    from . import ordinary_surfaces,glyph_visibility,planning_outline_semantics
    from .drawing_page_tools import native_inverse
    if (paving.get('version')!=planning_hatch_regions.VERSION or paving.get('page')!=page.number+1
            or paving.get('coordinate_frame')!='pdf_native_points_y_up'):
        raise ValueError('Same original page for gap source labels required')
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(t['chars']) for t in traces)>200000:
        raise ValueError('Gap source-label text budget exceeded')
    runs=ordinary_surfaces.label_runs(traces);inverse=native_inverse(page)
    def check():
        if cancelled():raise CancelledError('Gap source-label review cancelled')
    contexts=planning_outline_semantics.AnnotationContexts(page,runs,planning_outline_semantics.LIMITS,check)
    claims=[]
    for run in runs:
        check();text=''.join(chr(c[0]) for c in run['chars']).strip()
        noun=re.sub(r'^(existing|new|proposed)\s+','',text.casefold())
        if noun not in {'building','shop','station','maintenance','maintenance building','toilets','restaurant','kiosk'}:continue
        if contexts.review(run):continue
        screen=glyph_visibility.screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)
        if screen['status']!='raster_consistent_candidate':continue
        if len(claims)>=128:raise ValueError('Gap source-label count budget exceeded')
        claims.append({'id':digest([VERSION,paving['document_sha256'],paving['page'],run['trace_indices'],run['character_indices']]),
            'document_sha256':paving['document_sha256'],'page':paving['page'],'role':'building',
            'text':text,'label_geometry_pdf_native':mapping(Polygon([tuple(p*inverse) for p in (
                pymupdf.Rect(run['bbox']).tl,pymupdf.Rect(run['bbox']).tr,pymupdf.Rect(run['bbox']).br,pymupdf.Rect(run['bbox']).bl)])),
            'glyph_screen':screen,'scope':'source label/fill correspondence suppresses default only',
            'physical_identity_verified':False})
    return claims

def write_overlay(result,paving,preview,destination):
    if not result or not result['analysis_complete'] or not result['records']:return None
    base=planning_hatch_regions.write_overlay(paving,preview,destination)
    if not base:return None
    matrix=pymupdf.Matrix(preview['pdf_native_to_pixels']);paths=[]
    def draw(geometry,colour,label):
        g=shape(geometry)
        if g.is_empty:return
        parts=list(g.geoms) if g.geom_type in ('MultiLineString','GeometryCollection') else [g]
        for line in parts:
            if line.geom_type not in ('LineString','LinearRing'):continue
            points=[pymupdf.Point(*p)*matrix for p in line.coords]
            commands='M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)
            paths.append(f'<path d="{commands}" fill="none" stroke="{colour}" stroke-width="2" vector-effect="non-scaling-stroke"><title>{escape(label)}</title></path>')
    for record in result['records']:
        if not record['is_boundary']:continue
        if record['assumed']:
            draw(record['assumed_rock_geometry_pdf_native'],'#ad5b16','Assumed rock boundary; '+record['id'])
            for segment in record['source_boundary_overrides']:
                draw(segment['geometry_pdf_native'],'#555555','Explicit source building boundary; '+record['id'])
        else:draw(record['boundary_geometry_pdf_native'],'#555555',record['boundary_kind']+'; '+record['id'])
    path=Path(destination);data=path.read_text().replace('</svg>',''.join(paths)+'</svg>').encode()
    if len(data)>16000000:raise ValueError('Gap boundary overlay byte budget exceeded')
    path.write_bytes(data)
    return {'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),**result['summary']}
