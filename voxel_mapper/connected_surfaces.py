"""Conservative user-point edge graphs and source-assisted four-surface masks."""
import argparse
import json
import re
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, LineString, Point, mapping
from shapely.affinity import affine_transform

from . import study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json,file_hash

LABELS={'paving':0,'building_structure':1,'grass_island':2,'water':3,'unknown':255}
VERSION='connected-surface-dataset-v1'


def connect(points, max_gap=12., *, boundary_label='path_boundary'):
    """Mutual local-tangent neighbours; ambiguous branches and long gaps stay open."""
    if boundary_label not in ('path_boundary','building_boundary','water_boundary'):raise ValueError('Explicit supported boundary type required')
    points=[p for p in points if p['label']==boundary_label]
    if not 3<=len(points)<=3000 or not 2<=max_gap<=20:raise ValueError('Bounded path points and edge gap required')
    xy=np.array([p['reference_xy'] for p in points]);tree=cKDTree(xy);choices={};flags=[]
    for i,p in enumerate(xy):
        near=tree.query_ball_point(p,max_gap*1.5)
        near=[j for j in near if np.linalg.norm(xy[j]-p)>.8]
        if len(near)<2:flags.append({'point_id':points[i]['id'],'reason':'open_or_sparse'});continue
        local=xy[near]-p;_,v=np.linalg.eigh(local.T@local);tangent=v[:,-1]
        for sign in (-1,1):
            candidates=[]
            for j in near:
                delta=xy[j]-p;gap=float(np.linalg.norm(delta));alignment=float(delta@tangent*sign/gap)
                if gap<=max_gap and alignment>=.82:candidates.append((gap*(1+3*(1-alignment)),j))
            candidates.sort()
            if len(candidates)>1 and candidates[1][0]<candidates[0][0]*1.12:
                flags.append({'point_id':points[i]['id'],'reason':'ambiguous_join','candidate_ids':[points[j]['id'] for _,j in candidates[:2]]})
            elif candidates:choices.setdefault(i,set()).add(candidates[0][1])
    edges=[];adj={i:[] for i in range(len(points))}
    for i,targets in choices.items():
        for j in targets:
            if i<j and i in choices.get(j,set()):
                edges.append({'a':points[i]['id'],'b':points[j]['id'],'reference_xy':[xy[i].tolist(),xy[j].tolist()],
                    'gap_pixels':float(np.linalg.norm(xy[i]-xy[j])),'status':'candidate_not_verified_boundary'})
                adj[i].append(j);adj[j].append(i)
    chains=[];visited=set()
    for i in range(len(points)):
        if len(adj[i])==2:continue
        for j in adj[i]:
            if tuple(sorted((i,j))) in visited:continue
            chain=[i];previous,current=i,j
            while True:
                visited.add(tuple(sorted((previous,current))));chain.append(current)
                if len(adj[current])!=2:break
                nxt=next(x for x in adj[current] if x!=previous)
                if tuple(sorted((current,nxt))) in visited:break
                previous,current=current,nxt
            chains.append({'point_ids':[points[x]['id'] for x in chain],'closed':False,'surface':'unclassified'})
    for i,j in [(i,j) for i,neighbours in adj.items() for j in neighbours if i<j]:
        if (i,j) in visited:continue
        chain=[i];previous,current=i,j
        while tuple(sorted((previous,current))) not in visited:
            visited.add(tuple(sorted((previous,current))));chain.append(current)
            nxt=[x for x in adj[current] if x!=previous]
            if not nxt:break
            previous,current=current,nxt[0]
        chains.append({'point_ids':[points[x]['id'] for x in chain],'closed':chain[0]==chain[-1],'surface':'unclassified'})
    return {'edges':edges,'chains':chains,'review_flags':flags,'isolated_points':sum(not a for a in adj.values()),
        'closed_chain_is_paving_automatically':False,'max_gap_reference_pixels':max_gap}


def geometry(region,size):
    allowed={'id','label','outer','holes','line','half_width','reason','origin'}
    if not isinstance(region,dict) or set(region)-allowed or region.get('label') not in LABELS:
        raise ValueError('Explicit surface region and semantic class required')
    def ring(points,minimum):
        if not isinstance(points,list) or not minimum<=len(points)<=256 or any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=size[i] for i,v in enumerate(p)) for p in points):raise ValueError('Bounded in-reference coordinates required')
        return points
    if 'line' in region:
        width=region.get('half_width')
        if type(width) not in (int,float) or not 1<=width<=20:raise ValueError('Bounded corridor width required')
        g=LineString(ring(region['line'],2)).buffer(width,cap_style=2,join_style=2)
    else:g=Polygon(ring(region['outer'],3),[ring(h,3) for h in region.get('holes',[])])
    if not g.is_valid or g.is_empty or g.area<=0:raise ValueError('Valid positive-area surface region required')
    return g


def raster(g,size):
    im=Image.new('L',size);d=ImageDraw.Draw(im)
    for p in (list(g.geoms) if hasattr(g,'geoms') else [g]):
        if p.geom_type!='Polygon':continue
        d.polygon(list(p.exterior.coords),fill=1)
        for h in p.interiors:d.polygon(list(h.coords),fill=0)
    return np.array(im,dtype=bool)


def masks(regions,reference_size,clean_size,matrix,canopy_points):
    M=np.asarray(matrix,float)
    if M.shape!=(2,3) or not np.isfinite(M).all():raise ValueError('Finite affine registration required')
    tf=[M[0,0],M[0,1],M[1,0],M[1,1],M[0,2],M[1,2]]
    shape=(clean_size[1],clean_size[0]);raw=[np.zeros(shape,bool) for _ in range(4)];unknown=np.zeros(shape,bool);caps=unknown.copy();vectors=[]
    if np.prod(shape)>1048576:raise ValueError('One-megapixel mask budget exceeded')
    for region in regions:
        g=geometry(region,reference_size);mapped=affine_transform(g,tf);m=raster(mapped,clean_size);label=LABELS[region['label']]
        if label==255:unknown|=m
        else:raw[label]|=m
        if 'line' in region:
            for pt in (region['line'][0],region['line'][-1]):caps|=raster(affine_transform(Point(*pt).buffer(region['half_width']*1.15),tf),clean_size)
        vectors.append({'type':'Feature','geometry':mapping(mapped),'properties':{k:v for k,v in region.items() if k not in ('outer','holes','line')},'coordinate_space':'clean_image_pixels'})
    # Ref-image fallback glyph-independent canopy radius; this is an inference layer.
    canopy=np.zeros(shape,bool)
    for point in canopy_points:
        if point['label']=='tree_location':canopy|=raster(affine_transform(Point(*point['reference_xy']).buffer(10),tf),clean_size)
    conflict=np.stack(raw).sum(axis=0)>1;edges=np.zeros(shape,bool)
    target=np.full(shape,255,np.uint8)
    for c,m in enumerate(raw):
        inner=ndimage.binary_erosion(m,iterations=1);edges|=m & ~inner;target[inner]=c
    inferred=raw[0]&canopy&~(raw[1]|raw[2]|raw[3])
    target[unknown|conflict|edges|caps|canopy]=255
    return target,inferred,{'conflict_pixels':int(conflict.sum()),'cap_unknown_pixels':int(caps.sum()),
        'inferred_path_under_canopy_pixels':int(inferred.sum()),'counts':{k:int((target==v).sum()) for k,v in LABELS.items()}},vectors


def build(examples_file,recipe_file,output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh connected-surface output required')
    examples_file=Path(examples_file).resolve();entries,_=safe._json(examples_file,2000000);recipe,_=safe._json(Path(recipe_file),2000000)
    if recipe.get('version')!='source-assisted-surfaces-v1':raise ValueError('Explicit source-assisted semantic recipe required')
    if not isinstance(entries,list) or not 2<=len(entries)<=4 or len({e['id'] for e in entries})!=len(entries):raise ValueError('Two to four distinct surface examples required')
    prepared=[]
    for entry in entries:
        identifier=safe._identifier(entry['id'],'example',80)
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',identifier):raise ValueError('Safe example ID required')
        clean=safe._asset(examples_file.parent,entry['clean']);registration,_=safe._json(safe._asset(examples_file.parent,entry['registration']),2000000)
        reference=safe._asset(examples_file.parent,entry['reference']);meta=safe._asset(examples_file.parent,entry['metadata'])
        if file_hash(clean)!=registration['clean_source_sha256'] or file_hash(reference)!=registration['reference_sha256'] or file_hash(meta)!=registration['metadata_sha256']:raise ValueError('Source pins changed')
        from .user_path_supervision import extract,register
        with Image.open(reference) as im:
            if im.width*im.height>1048576 or list(im.size)!=registration['reference_size']:raise ValueError('Pinned bounded reference dimensions required')
            points,_=extract(np.array(im.convert('RGB')),fine_markers=entry.get('fine_markers',False),building_markers=entry.get('building_markers',False),exclusion_boxes=entry.get('reference_exclusion_boxes',()));rs=list(im.size)
        with Image.open(clean) as im:
            cs=list(im.size)
            if im.width*im.height>1048576 or cs!=registration['clean_size']:raise ValueError('Pinned bounded clean dimensions required')
        receipt,_=safe._json(meta,2000000)
        if receipt['image_sha256']!=file_hash(clean) or cs!=[receipt['width'],receipt['height']]:raise ValueError('Receipt must describe the exact clean raster')
        water_role=entry.get('water_role','location')
        if water_role not in ('location','boundary','none'):raise ValueError('Explicit water marker role required')
        if water_role=='none':points=[p for p in points if p['label']!='water_location']
        elif water_role=='boundary':points=[{**p,'label':'water_boundary' if p['label']=='water_location' else p['label']} for p in points]
        points=register(points,registration);graph=connect(points)
        if not 1<=len(recipe['examples'][identifier])<=128:raise ValueError('Bounded semantic region count required')
        target,inferred,stats,vectors=masks(recipe['examples'][identifier],rs,cs,registration['reference_to_clean'],points)
        prepared.append((entry,clean,meta,registration,points,graph,target,inferred,stats,vectors))
    output.mkdir(parents=True);records=[]
    for entry,clean,meta,registration,points,graph,target,inferred,stats,vectors in prepared:
        folder=output/entry['id'];folder.mkdir();shutil.copy2(clean,folder/'clean.bin');shutil.copy2(meta,folder/'receipt.json')
        Image.fromarray(target).save(folder/'surface-mask.png');Image.fromarray(inferred.astype(np.uint8)*255).save(folder/'inferred-path.png')
        atomic_json(folder/'edges.json',graph);atomic_json(folder/'regions.geojson',{'type':'FeatureCollection','coordinate_space':'clean_image_pixels','not_geographic':True,'features':vectors})
        atomic_json(folder/'points.json',{'points':points})
        building_points=[p for p in points if p['label']=='building_boundary']
        if len(building_points)>=3:atomic_json(folder/'building-edges.json',connect(points,boundary_label='building_boundary'))
        components,n=ndimage.label(target==0);probes=[]
        for label in sorted(range(1,n+1),key=lambda i:np.count_nonzero(components==i),reverse=True)[:3]:
            y,x=np.nonzero(components==label)
            if len(x)<80:continue
            low=int(np.argmin(x+y));high=int(np.argmax(x+y))
            probes.append({'id':'component-'+str(label),'a_xy':[int(x[low]),int(y[low])],'b_xy':[int(x[high]),int(y[high])]})
        atomic_json(folder/'connection-probes.json',probes)
        records.append({'id':entry['id'],'site_id':entry['site_id'],'image_file':entry['id']+'/clean.bin','image_sha256':file_hash(clean),
            'metadata_file':entry['id']+'/receipt.json','metadata_sha256':file_hash(meta),'mask_file':entry['id']+'/surface-mask.png','mask_sha256':file_hash(folder/'surface-mask.png'),
            'points_file':entry['id']+'/points.json','points_sha256':file_hash(folder/'points.json'),
            'probes_file':entry['id']+'/connection-probes.json','probes_sha256':file_hash(folder/'connection-probes.json'),
            'stats':stats,'candidate_edges':len(graph['edges']),'chains':len(graph['chains']),'closed_chains':sum(c['closed'] for c in graph['chains']),
            'review_flags':len(graph['review_flags']),'source_only_assistant_regions':True})
    result={'version':VERSION,'labels':LABELS,'recipe_sha256':file_hash(recipe_file),'examples_sha256':file_hash(examples_file),'records':records,
        'production_eligible':False,'human_surface_labels_verified':False,'inferred_pixels_are_training_truth':False}
    result['id']=digest(result);atomic_json(output/'dataset.json',result);shutil.copy2(recipe_file,output/'recipe.json');return result


def validate(root):
    root=Path(root).resolve();m,_=safe._json(root/'dataset.json',2000000)
    if m.get('version')!=VERSION or m.get('labels')!=LABELS or m.get('id')!=digest({k:v for k,v in m.items() if k!='id'}):raise ValueError('Pinned connected-surface dataset required')
    if m.get('production_eligible') is not False or m.get('human_surface_labels_verified') is not False or m.get('inferred_pixels_are_training_truth') is not False:raise ValueError('Provisional surface policy required')
    if not 2<=len(m['records'])<=4 or len({r['id'] for r in m['records']})!=len(m['records']):raise ValueError('Two to four distinct surface examples required')
    if file_hash(root/'recipe.json')!=m['recipe_sha256']:raise ValueError('Surface recipe changed')
    for r in m['records']:
        for k in ('image','metadata','mask','points','probes'):
            p=safe._asset(root,r[k+'_file'])
            if file_hash(p)!=r[k+'_sha256']:raise ValueError('Surface '+k+' changed')
        with Image.open(root/r['image_file']) as im:
            if im.width*im.height>1048576:raise ValueError('Bounded native RGB required')
            size=im.size
        receipt,_=safe._json(root/r['metadata_file'],2000000)
        if receipt['image_sha256']!=r['image_sha256'] or [receipt['width'],receipt['height']]!=list(size):raise ValueError('Surface receipt differs from clean source')
        with Image.open(root/r['mask_file']) as im:
            values=np.array(im)
            if im.size!=size or im.mode!='L' or not set(np.unique(values))<=set(LABELS.values()):raise ValueError('Native four-class/unknown mask required')
            if r['stats']['counts']!={k:int((values==v).sum()) for k,v in LABELS.items()}:raise ValueError('Surface counts changed')
    return m


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('examples','recipe','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(build(a.examples,a.recipe,a.output)))


if __name__=='__main__':main()
