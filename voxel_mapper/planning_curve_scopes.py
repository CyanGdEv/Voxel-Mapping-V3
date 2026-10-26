"""Whole source scopes for open curved strokes crossing label search windows.

Paint style groups are provenance, never physical path/material classes. This
planner adds a separate review scope; existing surface/world inputs stay intact.
"""
from collections import Counter
from concurrent.futures import CancelledError
import hashlib
import json
import math
import re

import pymupdf
from shapely.geometry import LineString,box

from . import drawing_geometry,ordinary_surfaces,planning_curved_boundaries,planning_surface_footprints
from .building_spec import digest
from .drawing_footprints import fill_geometry
from .drawing_page_tools import native_inverse

VERSION='planning-complete-curve-scopes-v1'
MARGIN_POINTS=.5
LIMITS={'max_regions':32,'max_anchors':256,'max_source_operators':20000,
        'max_flattened_points':200000,'max_scope_checks':100000,'max_output_bytes':8000000}


def page_plan(page,sha,number,surfaces,*,options=None,cancelled=lambda:False,_cache=None):
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):raise ValueError('Known complete-curve scope limits required')
    limits={**LIMITS,**options}
    if (any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items())
            or limits['max_output_bytes']<16384):raise ValueError('Lower-only complete-curve scope limits required')
    if (not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
            or type(number) is not int or number<1 or page.number+1!=number
            or not isinstance(surfaces,dict) or surfaces.get('document_sha256')!=sha
            or surfaces.get('page')!=number or surfaces.get('version')!=planning_surface_footprints.VERSION
            or surfaces.get('coordinate_frame')!='pdf_native_points_y_up'):
        raise ValueError('Same original page and surface scope analysis required')
    result={'version':VERSION,'document_sha256':sha,'page':number,
        'coordinate_frame':'pdf_native_points_y_up','source_surface_analysis_sha256':digest(surfaces),
        'limits':limits,'status':'complete_original_curve_scope_plan','analysis_complete':True,
        'regions':[],'region_stroke_styles':[],'anchors':[],
        'source_scope_margin_pdf_points':MARGIN_POINTS,'source_geometry_clipped':False,
        'physical_role_inferred_from_style':False,'physical_identity_verified':False,
        'world_placement_eligible':False,'world_geometry_additions':0,'training_labels_generated':0}
    def check():
        if cancelled():raise CancelledError('Complete curve source scope planning cancelled')
    def fail(reason):
        result.update(status='complete_curve_scope_plan_withheld',analysis_complete=False,
                      reason=reason,regions=[],region_stroke_styles=[],anchors=[])
        return result
    check()
    if not surfaces.get('analysis_complete'):return fail('complete_original_surface_scopes_required')
    seeds=surfaces.get('extraction',{}).get('regions',[])
    if not isinstance(seeds,list) or len(seeds)>32:raise ValueError('Bounded original source seed scopes required')
    if not seeds:return result
    windows=[r['region_native_points'] for r in seeds]
    drawing_geometry.validated_options({'region_native_windows':windows})
    inverse=native_inverse(page);angle=page.rotation
    try:
        page.set_rotation(0);frame=pymupdf.Rect(page.rect)*inverse
    finally:page.set_rotation(angle)
    if any(not frame.contains(pymupdf.Rect(w)) for w in windows):raise ValueError('Original page source scopes required')
    counts=Counter();families={};groups=[];clips=[];operators=points=checks=0
    def work(count):
        nonlocal operators
        operators+=count
        if operators>limits['max_source_operators']:raise ValueError('complete_curve_scope_operator_budget_exceeded')
    def flatten(path):
        nonlocal points
        work(len(path['items']))
        parts,approx=drawing_geometry.subpaths(path,inverse,{'curve_tolerance_points':.05,
            'max_points':10000,'open_stroked_primitives_only':True})
        points+=sum(len(p) for p in parts)
        if points>limits['max_flattened_points']:raise ValueError('complete_curve_scope_point_budget_exceeded')
        return parts,approx
    try:
        cache=ordinary_surfaces._source_page_cache(page) if _cache is None else _cache
        if cache.get('page') is not page or cache.get('source_content_sha256')!=hashlib.sha256(page.read_contents()).hexdigest():
            raise ValueError('Same unchanged original curve scope page cache required')
        check()
        result.update(source_content_sha256=cache['source_content_sha256'],
                      source_seed_scopes=[list(w) for w in windows],raw_source_paths=len(cache['compact']))
        for ordinal,path in enumerate(cache['compact']):
            check();level=path.get('level',0)
            groups=[g for g in groups if g<level];clips=[c for c in clips if c[0]<level]
            if path['type']=='group':groups.append(level);continue
            if path['type']=='clip':
                try:
                    parts,_=flatten(path)
                    rings=[p+[p[0]] if p[0]!=p[-1] else p for p in parts]
                    clip=fill_geometry(rings,path.get('even_odd',False),True)
                    if clip.is_empty or not clip.is_valid or not clip.equals(box(*clip.bounds)):clip=None
                except ValueError as error:
                    if 'budget' in str(error).lower():raise
                    clip=None
                except (KeyError,TypeError):clip=None
                clips.append((level,clip,ordinal));continue
            if path['type']!='s' or not any(i[0]=='c' for i in path.get('items',[])):continue
            counts['raw_curved_stroke_groups']+=1
            if groups or any(c[1] is None for c in clips):counts['unsupported_clip_or_group']+=1;continue
            if path.get('layer') or path.get('stroke_opacity',1)!=1 or path.get('fill_opacity',1)!=1:
                counts['nonopaque_or_optional_layer']+=1;continue
            style=drawing_geometry.stroke_signature(path)
            if style is None or not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',style['dashes_pdf']):
                counts['unsupported_or_nonsolid_style']+=1;continue
            bounds=pymupdf.Rect(path['rect'])*inverse
            if (not all(math.isfinite(v) for v in bounds) or bounds.is_empty
                    or min(bounds.x0-frame.x0,bounds.y0-frame.y0,frame.x1-bounds.x1,frame.y1-bounds.y1)<MARGIN_POINTS):
                counts['complete_stroke_outside_original_frame']+=1;continue
            if any(not c[1].covers(box(*bounds).buffer(.05)) for c in clips):
                counts['complete_stroke_crosses_clip']+=1;continue
            hits=[];fits=False
            for index,w in enumerate(windows):
                check();checks+=1
                if checks>limits['max_scope_checks']:raise ValueError('complete_curve_scope_comparison_budget_exceeded')
                if min(bounds.x0-w[0],bounds.y0-w[1],w[2]-bounds.x1,w[3]-bounds.y1)>=.25:fits=True
                if not(bounds.x1<w[0] or bounds.y1<w[1] or bounds.x0>w[2] or bounds.y0>w[3]):hits.append(index)
            if fits:counts['already_inside_original_scope']+=1;continue
            if not hits:counts['outside_original_seed_scopes']+=1;continue
            parts,approx=flatten(path)
            eligible=[i for i,(part,a) in enumerate(zip(parts,approx['subpath_approximations']))
                if a['cubic_segments'] and len(part)>=2 and part[0]!=part[-1]
                and LineString(part).is_simple and LineString(part).length>=.25]
            if not eligible:counts['no_supported_original_open_curve']+=1;continue
            if len(result['anchors'])>=limits['max_anchors']:raise ValueError('complete_curve_anchor_budget_exceeded')
            witness={'ordinal':ordinal,'native_bounds_pdf_points':list(bounds),'stroke_style':style,
                'intersecting_seed_scope_indices':hits,'eligible_original_subpaths':eligible,
                'clip_scope_ordinals':[c[2] for c in clips],
                'source_operators_pdf_native':planning_curved_boundaries._operators(cache['paths'][ordinal],inverse)}
            witness['source_witness_sha256']=digest(witness)
            result['anchors'].append(witness)
            key=digest(style)
            if key not in families:
                if len(families)>=limits['max_regions']:raise ValueError('complete_curve_style_region_budget_exceeded')
                families[key]={'style':style,'bounds':list(bounds),'anchors':[],'seed_scopes':set()}
            family=families[key];family['bounds']=[min(family['bounds'][0],bounds.x0),min(family['bounds'][1],bounds.y0),
                max(family['bounds'][2],bounds.x1),max(family['bounds'][3],bounds.y1)]
            family['anchors'].append(ordinal)
            for index in hits:
                w=windows[index];family['seed_scopes'].add(index)
                family['bounds']=[min(family['bounds'][0],w[0]),min(family['bounds'][1],w[1]),
                    max(family['bounds'][2],w[2]),max(family['bounds'][3],w[3])]
        for key,family in sorted(families.items()):
            b=family['bounds'];window=[max(frame.x0,b[0]-MARGIN_POINTS),max(frame.y0,b[1]-MARGIN_POINTS),
                min(frame.x1,b[2]+MARGIN_POINTS),min(frame.y1,b[3]+MARGIN_POINTS)]
            result['regions'].append({'region_native_points':window,'source_style_id':key,
                'anchor_ordinals':family['anchors'],'seed_scope_indices':sorted(family['seed_scopes']),
                'source_bounds_complete':True})
            result['region_stroke_styles'].append(family['style'])
        check()
        if hashlib.sha256(page.read_contents()).hexdigest()!=cache['source_content_sha256']:
            raise ValueError('Original curve source changed during scope planning')
        result.update(counts=dict(counts),source_operator_work=operators,flattened_point_work=points,
                      scope_checks=checks,anchor_count=len(result['anchors']))
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            raise ValueError('complete_curve_scope_output_budget_exceeded')
        return result
    except (ValueError,RuntimeError,OverflowError) as error:return fail(str(error)[:512])


def plan_and_review(page,sha,number,surfaces,*,options=None,network_options=None,cancelled=lambda:False):
    """Share immutable original paint data across planning and native recovery."""
    from . import planning_curve_networks
    if cancelled():raise CancelledError('Complete curve scope review cancelled')
    cache=(ordinary_surfaces._source_page_cache(page) if isinstance(surfaces,dict)
        and surfaces.get('analysis_complete') and surfaces.get('extraction',{}).get('regions') else None)
    plan=page_plan(page,sha,number,surfaces,options=options,cancelled=cancelled,_cache=cache)
    review=planning_curve_networks.page_review(page,sha,number,surfaces,options=network_options,
        cancelled=cancelled,source_scope_plan=plan,_source_cache=cache)
    return plan,review
