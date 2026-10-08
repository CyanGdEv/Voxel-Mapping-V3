"""Provisional shared-survey registration and material-labelled paving recovery."""
import collections
import gzip
import hashlib
import json
import math
import re
from pathlib import Path
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point,shape,mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from .alton import is_park_application
from .wicker_registration import apply_candidate
from .plan_boundaries import recover_boundaries
from .paving_palette import material_label

ANCHOR='1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d'
GENERIC_PAVING_LABELS={'paving','paved area','plaza','footpath','path','hardstanding','hard landscaping'}


def cached_paving_faces(path,recover):
    """Interrupted extraction caches may be rebuilt from their hashed source PDF."""
    path=Path(path)
    if path.exists():
        try:
            with gzip.open(path,'rt') as stream:return json.load(stream)
        except (EOFError,gzip.BadGzipFile,json.JSONDecodeError):pass
    candidates={'polygons':recover()}
    temporary=path.with_suffix(path.suffix+'.tmp')
    try:
        with gzip.open(temporary,'wt') as stream:json.dump(candidates,stream)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return candidates


def control_labels(labels):
    eligible=[a for a in labels if re.fullmatch(r'(?:[A-Z]{2,3}\d{2,3}|\d{3}\.\d{2})',a['text'].strip())]
    count=collections.Counter(a['text'].strip() for a in eligible)
    return {a['text'].strip():a['origin'] for a in eligible if count[a['text'].strip()]==1}


def scale_bar_regions(labels):
    """Scale-bar strokes are annotations and cannot close a paving boundary."""
    from shapely.geometry import box
    numeric=[]
    for label in labels:
        match=re.fullmatch(r'(\d+)\s*(?:m)?',label['text'].strip())
        if match:numeric.append((float(match[1]),label))
    regions=[]
    for value,zero in numeric:
        if value!=0:continue
        x0,y0=zero['origin']
        height=zero['bbox'][3]-zero['bbox'][1]
        if height<=0:continue
        row=sorted([(v,l) for v,l in numeric if abs(l['origin'][1]-y0)<10
                    and l['origin'][0]>=x0-1
                    and .75*height<=l['bbox'][3]-l['bbox'][1]<=1.25*height],key=lambda pair:pair[1]['origin'][0])
        if len(row)<4 or len({v for v,_ in row})<4:continue
        xs=np.array([l['origin'][0] for _,l in row]);values=np.array([v for v,_ in row])
        if xs[-1]-xs[0]<100 or not np.all(np.diff(values)>0):continue
        slope,offset=np.polyfit(values,xs,1)
        if slope<=0 or max(abs(xs-(slope*values+offset)))>max(3,.025*(xs[-1]-xs[0])):continue
        bounds=[l['bbox'] for _,l in row]
        regions.append(box(min(b[0] for b in bounds)-20,min(b[1] for b in bounds)-25,
                           max(b[2] for b in bounds)+20,max(b[3] for b in bounds)+25))
    return regions


def fit_similarity(a,b):
    a=np.asarray(a,float);b=np.asarray(b,float);ac=a-a.mean(0);bc=b-b.mean(0)
    if (ac*ac).sum()<1e-8:raise ValueError('Degenerate controls')
    u,s,vt=np.linalg.svd(ac.T@bc);r=u@vt
    if np.linalg.det(r)<0:raise ValueError('Reflected alignment')
    scale=s.sum()/(ac*ac).sum();offset=b.mean(0)-scale*a.mean(0)@r
    return scale,r,offset


def align_shared_labels(local,reference):
    common=sorted(set(local)&set(reference))
    if len(common)<8:return None
    # Native text origins are approximate controls; no geographic verification.
    common=common[:300];a=np.array([[local[k][0],-local[k][1]] for k in common]);b=np.array([reference[k] for k in common])
    rng=np.random.default_rng(731);pairs=[tuple(rng.choice(len(a),2,replace=False)) for _ in range(800)]
    best=None; alternatives=[]
    for i,j in pairs:
        if np.linalg.norm(b[i]-b[j])<15:continue
        try:scale,r,offset=fit_similarity(a[[i,j]],b[[i,j]])
        except ValueError:continue
        if not .01<scale<3:continue
        error=np.linalg.norm(scale*a@r+offset-b,axis=1);mask=error<.6
        if mask.sum()<8:continue
        score=int(mask.sum());alternatives.append((score,scale,r,offset))
        if best is None or score>best[0]:best=(score,mask)
    if best is None:return None
    mask=best[1]
    ids=sum(bool(re.fullmatch(r'[A-Z]{2,3}\d{2,3}',common[i])) for i in np.flatnonzero(mask))
    if best[0]/len(common)<.3 or (ids<3 and best[0]<20):return None
    try:scale,r,offset=fit_similarity(a[mask],b[mask])
    except ValueError:return None
    spread=np.linalg.svd(b[mask]-b[mask].mean(0),compute_uv=False)/math.sqrt(mask.sum())
    if spread[-1]<5:return None
    errors=np.linalg.norm(scale*a@r+offset-b,axis=1)
    # Competing orientations/translations with similar consensus are ambiguous.
    for score,s,rot,t in alternatives:
        if score>=best[0]*.9 and np.linalg.norm(s*a[mask]@rot+t-(scale*a[mask]@r+offset),axis=1).mean()>2:return None
    withheld=[]
    for i in np.flatnonzero(mask):
        train=mask.copy();train[i]=False
        ss,rr,tt=fit_similarity(a[train],b[train]);withheld.append(float(np.linalg.norm(ss*a[i]@rr+tt-b[i])))
    if max(withheld)>.75:return None
    candidate={'scale_m_per_pdf_point':float(scale),'rotation':r.tolist(),'translation_epsg27700_m':offset.tolist()}
    return {'status':'shared_native_label_alignment_hypothesis','candidate':candidate,
            'matched_labels':[common[i] for i in np.flatnonzero(mask)],'survey_identifier_count':ids,
            'shared_labels':len(common),'max_withheld_residual_m':max(withheld),
            'registration_verified':False,'as_built_verified':False}


def labels_from_page(page):
    return [{'text':s['text'],'origin':list(s['origin']),'bbox':list(s['bbox'])}
            for b in page.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]


def recover_park_plans(cache,wicker,output,local_crs):
    import pymupdf
    cache,wicker,output=map(Path,(cache,wicker,output));output.mkdir(parents=True,exist_ok=True)
    cat=json.loads((Path(__file__).parent/'data/alton-planning-catalogue.json').read_text())
    pages={};audit=[];seen_documents=set()
    reviewed_exclusions=json.loads((Path(__file__).parent/'data/alton-paving-face-exclusions.json').read_text())['exclusions']
    for entry in cat['entries']:
        if not is_park_application(entry) or entry.get('role') not in ('site-plan','landscape-plan','block-plan','access-plan','location-plan'):continue
        if re.search(r'\bsuperseded\b',entry['title'],re.I):continue
        if not re.search(r'\b(?:plan|drawing|landscape|landscaping|paving|surfacing)\b',entry['title'],re.I):continue
        path=cache/'files'/(entry.get('sha256','')+'.pdf')
        if not path.exists():continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=entry.get('sha256'):raise ValueError('Planning PDF hash mismatch')
        if digest in seen_documents:continue
        seen_documents.add(digest)
        with pymupdf.open(path) as pdf:
            for page_index in range(min(len(pdf),8)):
                labels=labels_from_page(pdf[page_index])
                key=digest if page_index==0 else f'{digest}/page-{page_index+1}'
                pages[key]={'entry':entry,'path':str(path),'document_id':digest,'page_index':page_index,
                            'labels':labels,'controls':control_labels(labels)}
    # Catalogue role names vary; retain explicit plan titles, never report pages.
    if ANCHOR not in pages:raise ValueError('Retained Wicker alignment source PDF required')
    registration=json.loads((wicker/'wicker-man-registration.json').read_text())
    if registration['document_id']!=ANCHOR or registration['status']!='shop_track_alignment_hypothesis':raise ValueError('Wicker alignment mismatch')
    pages[ANCHOR]['alignment']={**registration,'anchor_chain':[ANCHOR]}
    for _ in range(4):
        previous=[key for key,p in pages.items() if 'alignment' in p];added=0
        for key,p in pages.items():
            if 'alignment' in p or len(p['controls'])<8:continue
            candidates=[]
            for ref in previous:
                reference=pages[ref];coords=reference['controls']
                xy=apply_candidate(list(coords.values()),reference['alignment']['candidate'])
                result=align_shared_labels(p['controls'],dict(zip(coords,xy)))
                if result:candidates.append((result,ref))
            if not candidates:continue
            candidates.sort(key=lambda x:(-len(x[0]['matched_labels']),len(pages[x[1]]['alignment']['anchor_chain'])))
            chosen,ref=candidates[0]
            # Multiple parent sheets must agree on the candidate control positions.
            control=list(p['controls'].values())
            if any(np.max(np.linalg.norm(apply_candidate(control,chosen['candidate'])-apply_candidate(control,c['candidate']),axis=1))>2 for c,_ in candidates[1:]):continue
            p['alignment']={**chosen,'parent_document_id':ref,'anchor_chain':pages[ref]['alignment']['anchor_chain']+[key]};added+=1
        if not added:break
    bng_to_local=Transformer.from_crs(27700,local_crs,always_xy=True)
    features=[];identities=set()
    for page_key,p in pages.items():
        digest=p['document_id'];page_number=p['page_index']+1
        e=p['entry'];record={'document_id':digest,'application':e['applicationReference'],'title':e['title'],
                            'source_url':e['url'],'page':page_number,'status':'unregistered','paving_features':0}
        audit.append(record)
        if 'alignment' not in p:continue
        record['alignment']=p['alignment'];record['status']='provisional_alignment'
        with pymupdf.open(p['path']) as pdf:
            page=pdf[p['page_index']];drawings=page.get_drawings(extended=True)
            scale=p['alignment']['candidate']['scale_m_per_pdf_point']
            try:
                cache_name=hashlib.sha256(f'{page_key}/{scale}/grey-solid-noded-curves-v1'.encode()).hexdigest()
                geometry_cache=output/(cache_name+'-paving-faces.json.gz')
                candidates=cached_paving_faces(geometry_cache,lambda:surface_boundaries(drawings,scale))
            except ValueError as error:
                record['extraction_withheld_reason']=str(error)
                continue
        def project(x,y,z=None):
            xy=apply_candidate(list(zip(x,y)),p['alignment']['candidate']);return bng_to_local.transform(xy[:,0],xy[:,1])
        polygons=[shape(c['geometry']) for c in candidates['polygons']]
        polygon_index=STRtree(polygons)
        annotation_regions=scale_bar_regions(p['labels'])
        annotation_faces={i for i,poly in enumerate(polygons)
                          if any(poly.boundary.intersects(region) for region in annotation_regions)}
        reviewed_faces={a['face_index'] for a in reviewed_exclusions
                        if a['document_id']==digest and a['page']==page_number}
        annotation_faces.update(reviewed_faces)
        record['reviewed_annotation_faces_withheld']=len(reviewed_faces)
        record['annotation_faces_withheld']=len(annotation_faces)
        assignments={}
        for label in p['labels']:
            material=material_label(label['text'])
            generic=label['text'].strip().lower() in GENERIC_PAVING_LABELS
            # Bare 'brick', 'stone', 'wood' can be walls/structures, never floor specs.
            if (not material and not generic) or label['text'].strip().lower() in ('brick','stone','wood','sand','gravel','ground','earth','dirt','paved','unpaved'):continue
            x0,y0,x1,y1=label['bbox'];point=Point((x0+x1)/2,(y0+y1)/2)
            choices=[]
            for index in polygon_index.query(point,predicate='within'):
                index=int(index);poly=polygons[index]
                if index not in annotation_faces and poly.boundary.distance(point)*scale>.3:
                    choices.append((poly.area,index))
            if not choices:continue
            _,index=min(choices);assignments.setdefault(index,[]).append((material or 'stone',label))
        for index,labels in assignments.items():
            explicit_materials={material_label(a['text']) for _,a in labels}-{None}
            if len(explicit_materials)>1:continue
            materials=explicit_materials or {'stone'}
            polygon=polygons[index]
            if any(re.fullmatch(r'(?:grass|planting|lawn|pond|lake)',a['text'].strip(),re.I)
                   and polygon.contains(Point(a['origin'])) for a in p['labels']):continue
            # Reject polygons with contained building semantics as floor ambiguity.
            if any(re.fullmatch(r'(?:building|brick building|timber building|container|shed)',a['text'].strip(),re.I)
                   and polygon.contains(Point(a['origin'])) for a in p['labels']):continue
            local=transform(project,polygon)
            if not local.is_valid or not 2<=local.area<=40000:continue
            identity=(local.normalize().wkb,next(iter(materials)))
            if identity in identities:continue
            identities.add(identity)
            props={'kind':'plaza','surface':next(iter(materials)),'document_id':digest,'page':page_number,
                   'application_reference':e['applicationReference'],'source_url':e['url'],
                   'state':e.get('state','unknown'),'material_evidence':[a['text'] for _,a in labels],
                   'material_status':'contained_native_floor_label' if explicit_materials else 'paving_label_unspecified_material','registration_verified':False,
                   'as_built_verified':False,'alignment_method':p['alignment']['status'],
                   'anchor_chain':p['alignment']['anchor_chain']}
            features.append({'type':'Feature','id':f'planning-paving/{digest[:12]}/{index}' if page_number==1 else f'planning-paving/{digest[:12]}/page-{page_number}/{index}','geometry':mapping(local),'properties':props});record['paving_features']+=1
    collection={'type':'FeatureCollection','coordinate_frame':'local x east/z north, metres','features':features}
    report={'status':'provisional_planning_paving','documents':audit,'aligned_documents':len({p['document_id'] for p in pages.values() if 'alignment' in p}),
            'aligned_pages':sum('alignment' in p for p in pages.values()),
            'inspected_pages':len(pages),'inspected_documents':len(seen_documents),'paving_polygons':len(features),
            'page_budget_per_document':8,
            'limitations':['At most eight pages per eligible document are inspected; explicitly superseded sheets are withheld',
                           'Absolute alignment inherits the provisional Wicker Man shop/track fit',
                           'Shared text origins check relative sheet consistency, not independent geographic survey controls',
                           'Proposed and historical geometry may differ from the present park; retained as draft evidence']}
    (output/'park-planning-paving.geojson').write_text(json.dumps(collection))
    (output/'park-planning-paving-audit.json').write_text(json.dumps(report,indent=2))
    return collection,report


def surface_boundaries(drawings,scale,min_area=2,max_area=40000):
    """Node visible solid survey strokes, including flattened boundary curves.

    Closed faces are only candidates; a contained floor label is still required.
    No gap snapping, convex hulls or inferred connecting edges are introduced.
    """
    if not 0<min_area<=max_area<=40000:raise ValueError('Invalid plan face area budget')
    from shapely.geometry import LineString,Polygon
    from shapely.ops import polygonize,unary_union
    from .wicker_patterns import flatten_cubic
    from .wicker_surfaces import painted_polygon
    lines=[];scopes=[]
    for path in drawings:
        level=path.get('level',0);scopes=[s for s in scopes if s[0]<level]
        if path['type'] in ('clip','group'):
            if path['type']=='clip':scopes.append((level,painted_polygon(path)))
            elif path.get('opacity',1)!=1 or path.get('layer') or path.get('blendmode','Normal')!='Normal':scopes.append((level,None))
            continue
        if path['type'] not in ('s','fs') or path.get('layer') or path.get('stroke_opacity',0)!=1 or path.get('dashes','[] 0')!='[] 0':continue
        if any(s[1] is None for s in scopes):continue
        colour=path.get('color')
        if not colour or max(colour)>.9 or max(colour)-min(colour)>.03:continue
        for item in path['items']:
            if item[0]=='l':coords=[tuple(item[1]),tuple(item[2])]
            elif item[0]=='re':
                x0,y0,x1,y1=item[1];coords=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
            elif item[0]=='qu':
                q=item[1];coords=[tuple(q.ul),tuple(q.ur),tuple(q.lr),tuple(q.ll),tuple(q.ul)]
            elif item[0]=='c':
                a,b,c,d=(np.array(p,float) for p in item[1:]);coords=[a.tolist()]+flatten_cubic(a,b,c,d,tolerance=min(.2,.05/scale))
            else:continue
            line=LineString(coords)
            for _,clip in scopes:line=line.intersection(clip)
            if not line.is_empty:lines.append(line)
            if len(lines)>300000:raise ValueError('Paving stroke network budget exceeded')
    faces=list(polygonize(unary_union(lines)))
    return [{'geometry':mapping(p)} for p in faces if p.is_valid and min_area<=p.area*scale**2<=max_area]


def main():
    import argparse,copy
    from pyproj import CRS
    from .survey import activate_retained_grid
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--planning-cache',required=True);parser.add_argument('--wicker-output',required=True)
    parser.add_argument('--park-output',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--datum-grid',required=True)
    a=parser.parse_args();park=Path(a.park_output)
    config=json.loads((park/'resolved-config.json').read_text());quality=json.loads((park/'quality-report.json').read_text())
    datum=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'))
    datum['coordinate_transform']['grid']['file']=a.datum_grid;activate_retained_grid(datum)
    _,report=recover_park_plans(a.planning_cache,a.wicker_output,a.output,CRS.from_wkt(quality['crs']))
    print(json.dumps({k:report[k] for k in ('inspected_documents','aligned_documents','paving_polygons')},indent=2),flush=True)


if __name__=='__main__':main()
