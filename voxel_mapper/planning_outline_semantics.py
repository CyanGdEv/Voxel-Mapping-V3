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
from shapely.geometry import Polygon, shape, mapping, box
from shapely.strtree import STRtree

from . import glyph_visibility, ordinary_surfaces
from .building_spec import digest
from .drawing_page_tools import native_inverse

VERSION='planning-outline-label-associations-v1'
FRAME='pdf_native_points_y_up'
ANNOTATION_LIMITS={'max_annotation_runs':20000,'max_annotation_checks':64000,
    'max_annotation_parts':32,'max_annotation_characters':512}
ANNOTATION_VERSION='planning-native-annotation-context-v1'
ANNOTATION_WITHHELD='annotation_fragment_withheld'
LIMITS={'max_outlines':500,'max_points':200000,'max_labels':128,
        'max_checks':64000,'max_output_bytes':4000000,
        'max_name_context_checks':64000,'max_name_context_suffixes':128,**ANNOTATION_LIMITS}
NAME_CONTEXT_VERSION='planning-name-context-v1'
NAME_SUFFIXES={'TAVERN','INN','PUB','HOTEL','CAFE','CAFÉ','LODGE'}
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


def _name_suffix(run, suffix):
    """Conservative original-text typography; never choose a nearest label."""
    text=''.join(chr(c[0]) for c in run['chars']).strip()
    if text!=text.upper() or run.get('dir')!=(1.0,0.0) or suffix.get('dir')!=(1.0,0.0):
        return False
    if (run.get('wmode')!=0 or suffix.get('wmode')!=0
            or run.get('font')!=suffix.get('font')
            or run.get('color')!=suffix.get('color')
            or run.get('colorspace')!=suffix.get('colorspace')):
        return False
    if not all(math.isfinite(v) and v>0 for v in (run['size'],suffix['size'])):return False
    size=max(run['size'],suffix['size'])
    if not .85<=run['size']/suffix['size']<=1/.85:return False
    a,b,c,d=run['bbox'];e,f,g,h=suffix['bbox']
    below=(0<=f-d<=.75*size and .8*size<=f-b<=1.8*size
           and (abs(a-e)<=.5*size or abs((a+c-e-g)/2)<=.5*size))
    inline=(0<=e-c<=.75*size and abs((b+d-f-h)/2)<=.2*size)
    return below or inline


class AnnotationContexts:
    """Bounded same-baseline native text context, used only to withhold roles.

    No word is selected by distance and no compound label supplies geometry,
    material or state. Every connected run is retained, or the analysis stops.
    """
    def __init__(self,page,runs,limits,check):
        self.page=page;self.runs=runs;self.limits=limits;self.check=check
        self.checks=0;self.edges={};self.components={};self.proofs={}
        if len(runs)>limits['max_annotation_runs']:
            raise ValueError('annotation_run_budget_exceeded')
        self.positions={self.key(r):i for i,r in enumerate(runs)}
        if len(self.positions)!=len(runs):raise ValueError('ambiguous_annotation_source_identity')
        if any(not all(math.isfinite(v) for v in r['bbox']) for r in runs):
            raise ValueError('finite_annotation_bounds_required')
        self.index=STRtree([box(*r['bbox']) for r in runs])
        self.inverse=native_inverse(page)

    @staticmethod
    def key(run):return (tuple(run['trace_indices']),tuple(run['character_indices']))

    @staticmethod
    def compatible(a,b):
        if any(r.get('dir')!=(1.0,0.0) or r.get('wmode')!=0 for r in (a,b)):return False
        if any(a.get(k)!=b.get(k) for k in ('font','color','colorspace','opacity','type')):return False
        if not all(math.isfinite(r['size']) and r['size']>0 for r in (a,b)):return False
        if not .85<=a['size']/b['size']<=1/.85:return False
        size=max(a['size'],b['size'])
        if abs(a['chars'][0][2][1]-b['chars'][0][2][1])>.15*size:return False
        left,right=(a,b) if a['bbox'][0]<=b['bbox'][0] else (b,a)
        gap=right['bbox'][0]-left['bbox'][2]
        return -.12*size<=gap<=.75*size

    def neighbours(self,i):
        if i in self.edges:return self.edges[i]
        r=self.runs[i];size=r['size'];a,b,c,d=r['bbox']
        if not math.isfinite(size) or size<=0:return ()
        neighbours=[]
        for position in self.index.query(box(a-.9*size,b-.5*size,c+.9*size,d+.5*size)):
            self.check();j=int(position)
            if j==i:continue
            self.checks+=1
            if self.checks>self.limits['max_annotation_checks']:
                raise ValueError('annotation_comparison_budget_exceeded')
            if self.compatible(r,self.runs[j]):neighbours.append(j)
        self.edges[i]=tuple(sorted(neighbours));return self.edges[i]

    def review(self,run,*,allow_names=False):
        start=self.positions[self.key(run)]
        if start in self.components:component=self.components[start]
        else:
            found=set();pending=[start];characters=0
            while pending:
                self.check();i=pending.pop()
                if i in found:continue
                found.add(i);characters+=len(self.runs[i]['chars'])
                if len(found)>self.limits['max_annotation_parts']:
                    raise ValueError('annotation_part_budget_exceeded')
                if characters>self.limits['max_annotation_characters']:
                    raise ValueError('annotation_character_budget_exceeded')
                pending.extend(j for j in self.neighbours(i) if j not in found)
            component=tuple(sorted(found,key=lambda i:(self.runs[i]['bbox'][0],self.key(self.runs[i]))))
            for i in component:self.components[i]=component
        if len(component)==1:return None
        strings=[''.join(chr(c[0]) for c in self.runs[i]['chars']) for i in component]
        # Existing name qualification still needs its own glyph and exact
        # same-enclosure proof. This adapter cannot replace that decision.
        if (allow_names and len(component)==2 and start==component[0]
                and strings[0].strip()==strings[0].strip().upper()
                and strings[1].strip() in NAME_SUFFIXES):return None
        parts=[]
        for i,text in zip(component,strings):
            self.check();r=self.runs[i]
            if i not in self.proofs:
                self.proofs[i]=glyph_visibility.screen_architectural_span(
                    self.page,r,zoom=24 if r['size']<4 else 6)
            rect=pymupdf.Rect(r['bbox']);geometry=Polygon([tuple(p*self.inverse)
                for p in (rect.tl,rect.tr,rect.br,rect.bl)])
            parts.append({'text':text,'trace_indices':r['trace_indices'],
                'character_indices':r['character_indices'],'geometry_pdf_native':mapping(geometry),
                'glyph_screen':self.proofs[i]})
        ambiguous=False
        for i in component:
            neighbours=self.neighbours(i);x=self.runs[i]['bbox'][0]
            left=sum(self.runs[j]['bbox'][0]<x for j in neighbours)
            if left>1 or len(neighbours)-left>1:ambiguous=True
        return {'version':ANNOTATION_VERSION,'status':'literal_fragment_in_native_text_context',
            'text':' '.join(s.strip() for s in strings),'parts':parts,
            'ambiguous_adjacency':ambiguous,
            'all_parts_visible':all(p['glyph_screen']['status']=='raster_consistent_candidate' for p in parts),
            'positive_role_material_or_state_inferred':False}


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
        'name_context_version':NAME_CONTEXT_VERSION,'name_context_checks':0,
        'annotation_context_version':ANNOTATION_VERSION,'annotation_context_checks':0,
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
            'qualified_name_labels':statuses['qualified_building_name_withheld'],
            'annotation_fragments_withheld':statuses[ANNOTATION_WITHHELD],
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
    runs=ordinary_surfaces.label_runs(raw);selected=[];suffixes=[]
    for run in runs:
        text=''.join(chr(c[0]) for c in run['chars']).strip();printed=claim(text)
        if text in NAME_SUFFIXES:
            suffixes.append((run,text))
            if len(suffixes)>limits['max_name_context_suffixes']:
                return finish('name_context_suffix_budget_exceeded')
        if printed:
            selected.append((run,text,printed))
            if len(selected)>limits['max_labels']:return finish('semantic_label_budget_exceeded')
    index=STRtree(geometries);matrix=native_inverse(page);bound={};competing={};checks=0
    try:annotations=AnnotationContexts(page,runs,limits,check)
    except ValueError as error:return finish(str(error))
    excluded={};suffix_proofs={};annotation_boundaries={}
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
        try:context=annotations.review(run,allow_names=printed['role'] in ('path','plaza','surface'))
        except ValueError as error:return finish(str(error))
        result['annotation_context_checks']=annotations.checks
        matches=[]
        for position in index.query(geometry,predicate='intersects'):
            check();checks+=1
            if checks>limits['max_checks']:return finish('semantic_association_work_budget_exceeded')
            if geometries[int(position)].contains(geometry):matches.append(records[int(position)]['candidate_id'])
        row['candidate_ids']=sorted(matches)
        if context:
            row.update(status=ANNOTATION_WITHHELD,annotation_context=context)
            for identifier in matches:annotation_boundaries.setdefault(identifier,[]).append(row)
            continue
        row['status']='ambiguous_source_enclosures_withheld' if len(matches)>1 else 'no_supported_source_enclosure'
        if len(matches)>1:
            for identifier in matches:competing.setdefault(identifier,[]).append(row['id'])
        if len(matches)==1:
            row['status']='unique_visible_source_enclosure'
            if printed['role'] in ('path','plaza','surface'):
                contexts=[]
                for suffix,text_suffix in suffixes:
                    check();result['name_context_checks']+=1
                    if result['name_context_checks']>limits['max_name_context_checks']:
                        return finish('name_context_work_budget_exceeded')
                    if _name_suffix(run,suffix):contexts.append((suffix,text_suffix))
                if len(contexts)==1:
                    suffix,text_suffix=contexts[0]
                    rect_suffix=pymupdf.Rect(suffix['bbox'])
                    geometry_suffix=Polygon([tuple(p*matrix) for p in
                        (rect_suffix.tl,rect_suffix.tr,rect_suffix.br,rect_suffix.bl)])
                    suffix_matches=[]
                    for position in index.query(geometry_suffix,predicate='intersects'):
                        check();checks+=1
                        if checks>limits['max_checks']:
                            return finish('semantic_association_work_budget_exceeded')
                        if geometries[int(position)].contains(geometry_suffix):
                            suffix_matches.append(records[int(position)]['candidate_id'])
                    if suffix_matches==matches:
                        key=(tuple(suffix['trace_indices']),tuple(suffix['character_indices']))
                        if key not in suffix_proofs:
                            suffix_proofs[key]=glyph_visibility.screen_architectural_span(
                                page,suffix,zoom=24 if suffix['size']<4 else 6)
                        proof=suffix_proofs[key]
                        if proof['status']=='raster_consistent_candidate':
                            row['status']='qualified_building_name_withheld'
                            row['name_context']={'version':NAME_CONTEXT_VERSION,
                                'status':'surface_noun_in_building_name',
                                'name_text':row['text']+' '+text_suffix,
                                'candidate_id':matches[0],
                                'suffix':{'text':text_suffix,
                                    'trace_indices':suffix['trace_indices'],
                                    'character_indices':suffix['character_indices'],
                                    'geometry_pdf_native':mapping(geometry_suffix),
                                    'glyph_screen':proof},
                                'physical_building_identity_verified':False}
                            excluded.setdefault(matches[0],[]).append(row['id'])
                            continue
            bound.setdefault(matches[0],[]).append(row)
    excluded_rows={r['id']:r for r in result['labels'] if r['status']=='qualified_building_name_withheld'}
    for identifier,labels in sorted(bound.items()):
        roles={r['claim']['role'] for r in labels};primary=roles-{'surface'}
        state_labels=labels+[excluded_rows[i] for i in excluded.get(identifier,[])]
        states={r['claim']['printed_state'] for r in state_labels}-{'unspecified'}
        status=('annotation_fragment_context_withheld' if identifier in annotation_boundaries else
                'annotation_context_withheld' if 'annotation' in roles else
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
            'printed_states':sorted({r['claim']['printed_state'] for r in state_labels}),
            'component_label_count':sum(r['claim']['scope']=='component' for r in labels),
            'competing_label_ids':competing.get(identifier,[]),
            'excluded_name_label_ids':excluded.get(identifier,[]),
            'excluded_name_contexts':[excluded_rows[i] for i in excluded.get(identifier,[])],
            'withheld_annotation_fragments':annotation_boundaries.get(identifier,[]),
            'component_footprints_resolved':False,'physical_identity_verified':False,
            'view_scope_verified':False,'world_placement_eligible':False,'geometric_accuracy':None})
    result['association_checks']=checks
    return finish()
