"""Visible printed role labels contained by retained source outlines.

These are source-text associations, never physical identity, independently
reviewed labels, per-component footprints or accepted world geometry.
"""
from collections import Counter
from concurrent.futures import CancelledError
import json
import math
import re

import fontTools
import pymupdf
import shapely
from shapely.geometry import Polygon, shape, mapping
from shapely.strtree import STRtree

from . import glyph_visibility, ordinary_surfaces
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION='planning-outline-label-associations-v1'
FRAME='pdf_native_points_y_up'
LIMITS={'max_outlines':500,'max_points':200000,'max_labels':128,
        'max_checks':64000,'max_output_bytes':4000000}
BACKENDS={'pymupdf':pymupdf.VersionBind,'shapely':shapely.__version__,
          'fonttools':fontTools.__version__}


def claim(text):
    """Only standalone role nouns; prose, dimensions and captions are excluded."""
    if not isinstance(text,str) or not 1<=len(text)<=100:return None
    match=re.fullmatch(r'(?:(existing|proposed|new)\s+)?(.+)',text.strip(),re.I)
    if match is None:return None
    noun=re.sub(r'\s+',' ',match[2]).casefold()
    groups={'container':('building','component'), 'shipping container':('building','component'),
        'building':('building','enclosure'), 'facilities building':('building','enclosure'),
        'restaurant':('building','enclosure'), 'shop':('building','enclosure'),
        'kiosk':('building','enclosure'), 'toilets':('building','enclosure'),
        'ride station':('building','enclosure'),
        'path':('path','enclosure'),'footpath':('path','enclosure'),
        'access path':('path','enclosure'),'walkway':('path','enclosure'),
        'plaza':('plaza','enclosure'),'courtyard':('plaza','enclosure'),
        'paving':('surface','enclosure'),'paved area':('surface','enclosure'),
        'tree':('vegetation','enclosure'),'tree canopy':('vegetation','enclosure'),
        'legend':('annotation','context'),'key':('annotation','context')}
    value=groups.get(noun)
    if value is None:return None
    return {'role':value[0],'scope':value[1],'noun':noun,
            'printed_state':(match[1] or 'unspecified').lower()}


def _limits(options):
    if options is None:options={}
    if not isinstance(options,dict) or set(options)-set(LIMITS):raise ValueError('Known semantic limits required')
    limits={**LIMITS,**options}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):
        raise ValueError('Lower-only bounded semantic limits required')
    if limits['max_output_bytes']<16384:raise ValueError('Semantic metadata needs at least 16384 bytes')
    return limits


def page_candidates(page,sha,number,inventory,*,options=None,cancelled=lambda:False):
    limits=_limits(options)
    if (not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
            or type(number) is not int or page.number+1!=number):
        raise ValueError('Same pinned original page required')
    if (not isinstance(inventory,dict) or inventory.get('version')!=ordinary_surfaces.OUTLINE_VERSION
            or inventory.get('status')!='complete_source_outline_inventory'
            or inventory.get('inventory_complete') is not True):
        raise ValueError('Complete current source outline inventory required')
    records=inventory.get('records')
    if not isinstance(records,list) or len(records)>500:raise ValueError('Bounded source outline records required')
    def check():
        if cancelled():raise CancelledError('Planning label association cancelled')
    check();geometries=[];by_id={};points=0
    for record in records:
        if not isinstance(record,dict) or not isinstance(record.get('candidate'),dict):
            raise ValueError('Source outline records required')
        candidate=record['candidate'];identifier=record['candidate_id']
        if (not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{64}',identifier)
                or identifier in by_id or candidate.get('id')!=identifier
                or record.get('source_record_sha256')!=digest(candidate)
                or any(v.get('document_sha256')!=sha or v.get('page')!=number or
                       v.get('coordinate_frame')!=FRAME for v in (record,candidate))):
            raise ValueError('Same unique source-bound outline records required')
        geometry=shape(candidate['geometry'])
        if (geometry.geom_type!='Polygon' or geometry.is_empty or not geometry.is_valid
                or not all(math.isfinite(v) for v in geometry.bounds)):
            raise ValueError('Complete finite closed source polygons required')
        points+=len(geometry.exterior.coords)+sum(len(r.coords) for r in geometry.interiors)
        geometries.append(geometry);by_id[identifier]=record
    result={'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':FRAME,
        'source_inventory_sha256':digest(inventory),'backends':BACKENDS,'limits':limits,
        'status':'source_label_enclosure_hints_only','labels':[],'outlines':[],
        'inventory_complete':True,'physical_identity_verified':False,
        'view_scope_verified':False,'registration_verified':False,'scale_application_verified':False,
        'world_placement_eligible':False,'training_labels_generated':0,'model_weights_updated':False,
        'world_geometry_additions':0,'geometric_accuracy':None,
        'limitations':['Literal printed roles and whole-label containment are source-text associations only.',
            'Several component labels in one enclosure do not establish separate component footprints.',
            'Legend samples, context and sheet scope still require interpretation; no physical feature is accepted.',
            'Unbound or ambiguous labels are never assigned to the nearest or smallest polygon.']}
    def finish(reason=None):
        if reason:
            result.update(status='source_label_associations_withheld',inventory_complete=False,reason=reason,outlines=[])
        statuses=Counter(r['status'] for r in result['labels'])
        roles=Counter(r['source_role_hint'] for r in result['outlines'] if r['status'] in (
            'visible_label_enclosure_hint','shared_component_label_enclosure_hint'))
        result['summary']={'role_labels':sum(r['claim']['role']!='annotation' for r in result['labels']),
            'visible_labels':sum(r.get('glyph_screen',{}).get('status')=='raster_consistent_candidate' for r in result['labels']),
            'associated_outline_hints':sum(r['status'] in ('visible_label_enclosure_hint','shared_component_label_enclosure_hint') for r in result['outlines']),
            'shared_component_enclosures':sum(r['status']=='shared_component_label_enclosure_hint' for r in result['outlines']),
            'conflicting_outline_roles':sum(r['status']=='conflicting_source_roles_withheld' for r in result['outlines']),
            'labels_with_unique_enclosure':statuses['unique_visible_source_enclosure'],
            'outline_role_hints':dict(roles),
            'label_statuses':dict(statuses)}
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:
            result.update(status='source_label_associations_withheld',inventory_complete=False,
                          reason='semantic_output_budget_exceeded',labels=[],outlines=[],
                          summary={'role_labels':0,'visible_labels':0,'associated_outline_hints':0,
                            'shared_component_enclosures':0,'conflicting_outline_roles':0,
                            'labels_with_unique_enclosure':0,'label_statuses':{},'outline_role_hints':{}})
        check();return result
    if len(records)>limits['max_outlines'] or points>limits['max_points']:
        return finish('semantic_outline_or_point_budget_exceeded')
    raw=page.get_texttrace()
    if len(raw)>10000 or sum(len(r['chars']) for r in raw)>500000:
        return finish('semantic_text_budget_exceeded')
    runs=ordinary_surfaces.label_runs(raw);selected=[]
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip();printed=claim(text)
        if printed:
            selected.append((run,text,printed))
            if len(selected)>limits['max_labels']:return finish('semantic_label_budget_exceeded')
    index=STRtree(geometries);matrix=native_inverse(page);bound={};competing={};checks=0
    for run,text,printed in selected:
        check();rect=pymupdf.Rect(run['bbox'])
        geometry=Polygon([tuple(p*matrix) for p in (rect.tl,rect.tr,rect.br,rect.bl)])
        screen=glyph_visibility.screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)
        row={'id':digest([VERSION,sha,number,run['trace_indices'],run['character_indices']]),
            'text':text,'claim':printed,'trace_indices':run['trace_indices'],
            'character_indices':run['character_indices'],'geometry_pdf_native':mapping(geometry),
            'glyph_screen':screen,'candidate_ids':[],'status':'glyph_visibility_withheld'}
        result['labels'].append(row)
        if screen['status']!='raster_consistent_candidate':continue
        matches=[]
        for position in index.query(geometry,predicate='intersects'):
            check();checks+=1
            if checks>limits['max_checks']:return finish('semantic_association_work_budget_exceeded')
            if geometries[int(position)].contains(geometry):matches.append(records[int(position)]['candidate_id'])
        row['candidate_ids']=sorted(matches)
        row['status']='ambiguous_source_enclosures_withheld' if len(matches)>1 else 'no_supported_source_enclosure'
        if len(matches)>1:
            for identifier in matches:competing.setdefault(identifier,[]).append(row['id'])
        if len(matches)==1:
            row['status']='unique_visible_source_enclosure';bound.setdefault(matches[0],[]).append(row)
    for identifier,labels in sorted(bound.items()):
        roles={r['claim']['role'] for r in labels};primary=roles-{'surface'}
        states={r['claim']['printed_state'] for r in labels}-{'unspecified'}
        status=('annotation_context_withheld' if 'annotation' in roles else
                'competing_label_context_withheld' if identifier in competing else
                'conflicting_source_roles_withheld' if len(primary)>1 else
                'mixed_printed_states_withheld' if 'existing' in states and states&{'proposed','new'} else
                'shared_component_label_enclosure_hint' if sum(r['claim']['scope']=='component' for r in labels)>1 else
                'visible_label_enclosure_hint')
        result['outlines'].append({'candidate_id':identifier,
            'source_record_sha256':by_id[identifier]['source_record_sha256'],
            'status':status,'source_role_hint':next(iter(primary)) if len(primary)==1 else 'surface' if not primary else None,
            'printed_roles':sorted(roles),'label_ids':[r['id'] for r in labels],
            'label_texts':[r['text'] for r in labels],
            'printed_states':sorted({r['claim']['printed_state'] for r in labels}),
            'component_label_count':sum(r['claim']['scope']=='component' for r in labels),
            'competing_label_ids':competing.get(identifier,[]),
            'component_footprints_resolved':False,'physical_identity_verified':False,
            'view_scope_verified':False,'world_placement_eligible':False,'geometric_accuracy':None})
    result['association_checks']=checks
    return finish()
