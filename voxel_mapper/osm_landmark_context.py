"""Automatic visible-name associations and exact-endpoint network diagnostics."""
from collections import Counter
import math
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import pymupdf
from shapely.geometry import Point,Polygon,shape,LineString
from shapely.strtree import STRtree
from .footprint_matching import name_key
from .ordinary_surfaces import label_runs
from .drawing_page_tools import native_inverse
from .glyph_visibility import screen_span,VERSION as GLYPH_VERSION
from .mapped_sheet_placement import placed

VERSION='osm-landmark-context-v4'


def raster_name_agreement(page,run,text):
    """OCR checks the existing native string; it supplies no new coordinates."""
    engine=shutil.which('tesseract');color=run.get('color',())
    failure={'status':'withheld','physical_identity_verified':False}
    if (not engine or run.get('type')!=0 or run.get('opacity')!=1 or run.get('layer')
            or len(color) not in (1,3) or any(not math.isfinite(v) for v in color) or max(color)>.8):
        return {**failure,'reason':'Unsupported native style or OCR engine unavailable'}
    clip=pymupdf.Rect(run['bbox'])+(-1,-1,1,1)
    if clip.width*clip.height*24*24>1000000:return {**failure,'reason':'Name crop pixel budget'}
    angle=page.rotation
    try:
        page.set_rotation(0)
        pixmap=page.get_pixmap(matrix=pymupdf.Matrix(24,24),clip=clip,colorspace=pymupdf.csGRAY,alpha=False)
        with tempfile.TemporaryDirectory(prefix='native-name-') as directory:
            path=Path(directory);pixmap.save(path/'name.png')
            result=subprocess.run([engine,str(path/'name.png'),str(path/'name'),'-l','eng','--psm','7','tsv'],
                timeout=5,env={**os.environ,'OMP_THREAD_LIMIT':'1'},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if result.returncode:return {**failure,'reason':'Name OCR failed'}
            output=path/'name.tsv'
            if output.stat().st_size>100000:return {**failure,'reason':'Name OCR output budget'}
            words=[r for r in csv.DictReader(io.StringIO(output.read_text()),delimiter='\t',quoting=csv.QUOTE_NONE)
                if r.get('level')=='5' and r.get('text','').strip()]
            recognized=' '.join(r['text'] for r in words)
            confidence=min((float(r['conf']) for r in words),default=0)
            agreed=math.isfinite(confidence) and confidence>=85 and name_key(recognized)==name_key(text)
            return {'status':'native_raster_name_agreement_hint' if agreed else 'withheld',
                'recognized_text':recognized,'minimum_word_confidence':confidence,'clip_page_points':list(clip),
                'source_coordinates':'original_native_glyph_bounds; no OCR coordinate substitution',
                'physical_identity_verified':False,'registration_verified':False}
    except (OSError,ValueError,subprocess.SubprocessError) as error:return {**failure,'reason':str(error)[:200]}
    finally:page.set_rotation(angle)


def bind_labels(page,objects,parents,refs,*,max_ocr_labels=8):
    if type(max_ocr_labels) is not int or not 0<=max_ocr_labels<=8:raise ValueError('Name OCR budget must be 0..8')
    if len(objects)>20000 or len(parents)>10000 or len(refs)>5000:raise ValueError('Landmark association budget exceeded')
    names={}
    for ref in refs:
        for name in [ref.get('name','')]+[r['name'] for r in ref.get('name_hints',[])]:
            if name:names.setdefault(name_key(name),set()).add(ref['id'])
    names={k:sorted(v) for k,v in names.items()}
    traces=page.get_texttrace()
    if len(traces)>10000 or sum(len(r['chars']) for r in traces)>500000:raise ValueError('Landmark glyph budget exceeded')
    groups={}
    for run in label_runs(traces):
        text=''.join(chr(c[0]) for c in run['chars']).strip();key=name_key(text)
        if key not in names:continue
        position=(key,tuple(round(v,3) for v in run['bbox']))
        groups.setdefault(position,[]).append(run)
        if len(groups)>64:raise ValueError('Named landmark label budget exceeded')
    ids=[o['candidate_id'] for o in objects];geometries=[o['geometry'] for o in objects];index=STRtree(geometries)
    lines=[]
    for parent in parents:
        if (parent['geometry']['type']!='LineString' or parent.get('paint_reference_truncated')
                or parent.get('curve_approximation',{}).get('cubic_segments')):continue
        g=shape(parent['geometry'])
        if len(g.coords)==2 and parent.get('paint_references') and all(p['stroke_style'].get('dashes_pdf') in ('[] 0','',None) for p in parent['paint_references']):lines.append(g)
    endpoints=STRtree([Point(p) for g in lines for p in g.coords])
    inverse=native_inverse(page);records=[];priority=[];pairs=[];occurrences=Counter(key for key,_ in groups);ocr_attempts=0
    for (key,_),runs in sorted(groups.items()):
        run=runs[0];rect=pymupdf.Rect(run['bbox']);label=Polygon([(p.x,p.y) for p in (pymupdf.Point(p)*inverse for p in (rect.tl,rect.tr,rect.br,rect.bl))])
        screens=[screen_span(page,r,zoom=24 if r['size']<4 else 6) for r in runs if r.get('type')==0]
        visible=any(s['status']=='raster_consistent_candidate' for s in screens)
        text=''.join(chr(c[0]) for c in run['chars']).strip();ocr=None
        if not visible and occurrences[key]==1 and len(names[key])==1 and ocr_attempts<max_ocr_labels:
            ocr_attempts+=1;ocr=raster_name_agreement(page,run,text)
            visible=ocr['status']=='native_raster_name_agreement_hint'
        record={'text':''.join(chr(c[0]) for c in run['chars']).strip(),'name_key':key,'reference_ids':sorted(names[key]),
            'native_label_bounds':list(label.bounds),'glyph_screens':screens,'raster_name_agreement':ocr,'status':'withheld_visibility',
            'candidate_ids':[],'physical_identity_verified':False}
        if visible:
            hits=[int(i) for i in index.query(label,predicate='intersects') if geometries[int(i)].covers(label)]
            if hits:record['status']='unique_containment_hint' if len(hits)==1 else 'ambiguous_containment'
            else:
                targets=set()
                for endpoint in endpoints.query(label.buffer(1),predicate='intersects'):
                    i=int(endpoint);g=lines[i//2];end=Point(list(g.coords)[1-i%2])
                    targets.update(int(j) for j in index.query(end,predicate='intersects') if geometries[int(j)].contains(end))
                hits=sorted(targets);record['status']='unique_leader_hint' if len(hits)==1 else 'ambiguous_or_unbound_leader'
            record['candidate_ids']=[ids[i] for i in hits]
            if occurrences[key]>1:record['status']='repeated_source_name'
            elif len(names[key])!=1:record['status']='ambiguous_named_reference'
            elif len(hits)==1:
                if ids[hits[0]] not in priority and len(priority)<16:priority.append(ids[hits[0]])
                pairs.append([ids[hits[0]],names[key][0]])
        records.append(record)
    return {'version':VERSION,'glyph_version':GLYPH_VERSION,'labels':records,'priority_seed_ids':priority,
        'named_pairs':sorted({tuple(p) for p in pairs}),'association_statuses':dict(Counter(r['status'] for r in records)),
        'ocr_attempts':ocr_attempts,
        'physical_identity_verified':False,'registration_verified':False,'world_geometry_additions':0}


def junctions(lines,max_vertices=30000):
    """Exact shared source vertices only; no snapping, crossings or gap repair."""
    edges={};positions={};count=0
    for item in lines:
        line=item['geometry'] if isinstance(item,dict) else item
        if line.geom_type!='LineString' or line.is_empty or not line.is_valid:continue
        coords=list(line.coords);count+=len(coords)
        if count>max_vertices:raise ValueError('Network vertex budget exceeded')
        ids=item.get('node_ids') if isinstance(item,dict) else None
        if ids is not None and len(ids)!=len(coords):raise ValueError('OSM node/geometry inventory mismatch')
        layer=item.get('layer','0') if isinstance(item,dict) else 'native'
        keys=[('osm_node',node) for node in ids] if ids is not None else [('coordinate',layer,*p) for p in coords]
        for i,(a,b) in enumerate(zip(coords,coords[1:])):
            if a==b:continue
            if any(not math.isfinite(v) for p in (a,b) for v in p):raise ValueError('Finite network vertices required')
            ka,kb=keys[i:i+2]
            for key,p in ((ka,a),(kb,b)):
                if key in positions and positions[key]!=p:raise ValueError('Conflicting shared OSM node coordinates')
                positions[key]=p
            edges.setdefault(ka,set()).add(kb);edges.setdefault(kb,set()).add(ka)
    return [{'point':list(positions[key]),'degree':len(neighbors)} for key,neighbors in sorted(edges.items()) if len(neighbors)>=3]


def topology_checks(parents,map_lines,hypotheses):
    raw=[shape(c['geometry']) for c in parents if c['geometry']['type']=='LineString' and not c.get('paint_reference_truncated')
         and not c.get('curve_approximation',{}).get('cubic_segments')]
    if not hypotheses:return {'status':'awaiting_map_pose','source_line_candidates':len(raw),'osm_path_lines':len(map_lines),
        'registration_verified':False,'physical_identity_verified':False}
    try:local=junctions(raw);mapped=junctions(map_lines)
    except ValueError as error:return {'status':'network_budget_withheld','reason':str(error),'registration_verified':False}
    if len(local)>2000 or len(mapped)>2000:return {'status':'junction_budget_withheld','registration_verified':False}
    reference_index=STRtree([Point(r['point']) for r in mapped]);reviews=[]
    for hypothesis in hypotheses:
        associations=[];counts=Counter()
        for node in local:
            point=placed(Point(node['point']),hypothesis)
            hits=[int(i) for i in reference_index.query(point,predicate='dwithin',distance=2) if mapped[int(i)]['degree']==node['degree']]
            if len(hits)==1:
                counts[hits[0]]+=1;associations.append({'source_point':node['point'],'reference_junction':hits[0],
                    'degree':node['degree'],'distance_m':point.distance(Point(mapped[hits[0]]['point']))})
        distinct=[a for a in associations if counts[a['reference_junction']]==1]
        reviews.append({'unique_junction_matches':distinct,'ambiguous_reference_reuse':len(associations)-len(distinct)})
    return {'status':'unclassified_source_network_diagnostics','source_junctions':len(local),'osm_path_junctions':len(mapped),
        'hypotheses':reviews,'registration_verified':False,'physical_identity_verified':False,
        'limitations':['CAD lines may be walls, fences or contours; network agreement does not verify path identity.',
                       'Open path crossings without an explicit shared vertex do not create junctions.']}
