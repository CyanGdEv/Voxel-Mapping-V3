"""Exact wall-side/labelled-region evidence; no physical wall acceptance."""
from collections import Counter
import hashlib
import json
import re
from shapely.geometry import Polygon, shape, mapping
from shapely.strtree import STRtree
import pymupdf
from .drawing_components import split_page
from .drawing_page_tools import native_inverse
from .ordinary_surfaces import label_runs
from .glyph_visibility import screen_architectural_span

VERSION='wall-region-adjacency-v1'
ROOM=re.compile(r'^(?:toilets?|kitchen|office|store(?:room)?|plant room)$',re.I)
OUTDOOR=re.compile(r'^(?:courtyard|grass|tarmac)$',re.I)


def review(page,sha,number,parents,faces,bands,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded adjacency checks required')
    if len(parents)>10000 or len(faces)>20000 or len(bands)>10000:raise ValueError('Bounded source page required')
    records=parents+faces+bands
    if any(r['document_sha256']!=sha or r['page']!=number or r['coordinate_frame']!='pdf_native_points_y_up' for r in records):
        raise ValueError('Same native source page required')
    if len({r['id'] for r in faces})!=len(faces) or len({r['id'] for r in bands})!=len(bands):raise ValueError('Unique source identities required')
    components={r['id']:r for r in split_page(parents)}
    geoms=[shape(r['geometry']) for r in faces]
    if any(g.geom_type!='Polygon' or not g.is_valid or g.is_empty for g in geoms):raise ValueError('Valid source faces required')
    index=STRtree(geoms);checks=0;labels=[];associations={};adjacency=[]
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Bounded source text required')
    inverse=native_inverse(page)
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip()
        role='room_claim' if ROOM.fullmatch(text) else 'outdoor_or_surface_claim' if OUTDOOR.fullmatch(text) else None
        if role is None:continue
        if len(labels)>=500:raise ValueError('Bounded adjacency labels required')
        rect=pymupdf.Rect(run['bbox'])
        points=[pymupdf.Point(x,y)*inverse for x,y in [(rect.x0,rect.y0),(rect.x1,rect.y0),(rect.x1,rect.y1),(rect.x0,rect.y1)]]
        polygon=Polygon([(p.x,p.y) for p in points]);screen=screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)
        row={'text':text,'claim':role,'label_geometry':mapping(polygon),'trace_indices':run['trace_indices'],
             'character_indices':run['character_indices'],'glyph_screen':screen,'status':'caption_visibility_withheld','containing_face_ids':[]}
        labels.append(row)
        for k in index.query(polygon,predicate='intersects'):
            checks+=1
            if checks>max_checks:break
            if geoms[int(k)].contains(polygon):row['containing_face_ids'].append(faces[int(k)]['id'])
        if checks>max_checks:break
        row['containing_face_ids'].sort()
        if screen['status']=='raster_consistent_candidate':
            row['status']='unique_contained_region_claim' if len(row['containing_face_ids'])==1 else 'missing_or_competing_region_claim'
            if len(row['containing_face_ids'])==1:associations.setdefault(row['containing_face_ids'][0],[]).append(len(labels)-1)
    if checks<=max_checks:
        for band in bands:
            polygon=shape(band['geometry']);refs=band['source_line_references']
            if len(refs)!=2:raise ValueError('Two original band sides required')
            sides=[]
            for ref in refs:
                source=components.get(ref['component_id'])
                if source is None or source['extraction_contract']!=ref['component_contract']:raise ValueError('Retained original band-side contract required')
                line=shape(source['geometry']);support=line.intersection(polygon.boundary)
                matches=[]
                for k in index.query(support,predicate='intersects'):
                    checks+=1
                    if checks>max_checks:break
                    k=int(k);face=geoms[k]
                    # A face within the band is wall-strip topology, not an adjacent region.
                    if face.intersection(polygon).area>1e-10:continue
                    shared=face.boundary.intersection(support)
                    if shared.length<=1e-7:continue
                    matches.append({'face_id':faces[k]['id'],'shared_source_geometry':mapping(shared),
                        'shared_length_pdf_points':shared.length,'region_claim_indices':associations.get(faces[k]['id'],[])})
                sides.append({'source_component_id':source['id'],'component_contract':source['extraction_contract'],
                              'original_source_geometry':source['geometry'],'band_side_support':mapping(support),
                              'adjacent_regions':sorted(matches,key=lambda r:r['face_id'])})
                if checks>max_checks:break
            if checks>max_checks:break
            claims=[{labels[i]['claim'] for r in side['adjacent_regions'] for i in r['region_claim_indices']} for side in sides]
            status='region_identity_unresolved'
            blockers=[]
            if any(shape(s['band_side_support']).length<=1e-7 for s in sides):blockers.append('no_continuous_exact_band_side_support')
            if any(not s['adjacent_regions'] for s in sides):blockers.append('missing_adjacent_source_region')
            if any(len(s['adjacent_regions'])>1 for s in sides):blockers.append('multiple_adjacent_source_regions')
            if any(not c for c in claims):blockers.append('missing_visible_region_claim')
            if any(len(c)>1 for c in claims):blockers.append('conflicting_region_claim_roles')
            if all(len(s['adjacent_regions'])==1 for s in sides):
                if all(len(c)==1 for c in claims):
                    roles=[next(iter(c)) for c in claims]
                    if roles==['room_claim','room_claim']:status='room_to_room_side_evidence'
                    elif set(roles)=={'room_claim','outdoor_or_surface_claim'}:status='room_to_outdoor_side_evidence'
                elif any(c=={'room_claim'} for c in claims) and any(not c for c in claims):
                    status='room_to_unlabelled_side_evidence'
            adjacency.append({'wall_band_id':band['id'],'sides':sides,'status':status,'blockers':blockers,'wall_identity_verified':False,
                              'exterior_wall_verified':False,'world_geometry_additions':0})
    exhausted=checks>max_checks
    if exhausted:labels=[];adjacency=[]
    return {'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'source_records_sha256':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),
        'status':'adjacency_budget_withheld' if exhausted else 'wall_side_region_evidence_only',
        'labels':labels,'wall_adjacency':adjacency,'checks':checks,'max_checks':max_checks,
        'counts':dict(Counter(r['status'] for r in adjacency)), 'physical_identity_verified':False,
        'building_footprint_verified':False,'registration_verified':False,'world_geometry_additions':0,
        'limitations':['Whole original source faces and source-supported band sides only; no joining, cropping or exterior hull.',
            'Room and outdoor/material text are claims, not certified occupancy or physical wall identity.',
            'Unlabelled regions, competing associations and partial boundaries cannot establish a building exterior.']}
