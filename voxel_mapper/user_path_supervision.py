"""Learn projected path boundaries from user markers using separately pinned clean RGB."""
import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

from . import aerial_semantic_network as net, paving_binary_learning as binary
from . import study_component_learning as safe
from .desktop_memory import digest
from .generation_cycles import atomic_json, file_hash

VERSION = 'user-path-boundary-supervision-v1'
MODEL_VERSION = 'user-projected-path-boundary-model-v1'
WATER_MODEL_VERSION = 'user-projected-water-boundary-model-v1'
BOUNDARY_LABELS = {'non_boundary_offset':0,'projected_boundary':1,'unknown':255}


def extract(rgb, *, fine_markers=False, building_markers=False, exclusion_boxes=()):
    """Extract saturated annotation glyphs, retaining point IDs and glyph sizes."""
    if type(fine_markers) is not bool or type(building_markers) is not bool:raise ValueError('Explicit marker booleans required')
    if not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8 or rgb.shape[0]*rgb.shape[1] > 1048576:
        raise ValueError('Bounded native RGB reference required')
    if not isinstance(exclusion_boxes,(list,tuple)) or len(exclusion_boxes)>32:raise ValueError('Bounded reference exclusion rectangles required')
    rgb=rgb.copy()
    for box in exclusion_boxes:
        if not isinstance(box,(list,tuple)) or len(box)!=4 or any(type(v) is not int for v in box):raise ValueError('Integer reference exclusion rectangles required')
        x0,y0,x1,y1=box
        if not 0<=x0<x1<=rgb.shape[1] or not 0<=y0<y1<=rgb.shape[0]:raise ValueError('Exclusion rectangle outside reference')
        rgb[y0:y1,x0:x1]=0
    r,g,b = rgb.astype(np.int16).transpose(2,0,1)
    selections = {'path_boundary': (r>185)&(g<110)&(b<110)&(r>g*1.8)&(r>b*1.8),
        'tree_location': (g>185)&(r<100)&(b<110)&(g>r*1.8)&(g>b*1.8),
        'water_location': (b>160)&(r<110)&(g<130)&(b>r*1.6)&(b>g*1.5)}
    if fine_markers:
        selections['path_boundary']=(r>140)&(g<120)&(b<115)&(r>g*1.6)&(r>b*1.6)
        selections['water_location']=(b>120)&(r<110)&(g<130)&(b>r*1.6)&(b>g*1.5)
    if building_markers:
        # Purple is opt-in user-confirmed roof/building evidence, never water.
        purple=(r>70)&(b>70)&(g<110)&(r>g*1.5)&(b>g*1.5)&(r<b*2)&(b<r*2)
        selections['building_boundary']=purple
        selections['water_location'] &= ~purple
    points = []; rejected = {}
    for label, mask in selections.items():
        components, count = ndimage.label(mask); accepted = []; refused = 0
        for index, sl in enumerate(ndimage.find_objects(components), 1):
            selected = components[sl] == index; area = int(selected.sum())
            limit = 1800 if label == 'tree_location' else 100
            if not (1 if fine_markers and label!='tree_location' else 3) <= area <= limit: refused += 1; continue
            y,x = np.nonzero(selected); x = x+sl[1].start; y = y+sl[0].start
            if max(np.ptp(x)+1,np.ptp(y)+1) > (52 if label=='tree_location' else 15):
                refused += 1; continue
            accepted.append({'label':label,'reference_xy':[float(x.mean()),float(y.mean())],
                'glyph_pixels':area,'glyph_radius_pixels':float(np.sqrt(area/np.pi))})
        if fine_markers and len(accepted)>1 and label!='tree_location':
            coords=np.array([p['reference_xy'] for p in accepted]);tree=cKDTree(coords)
            retained=[]
            for i,p in enumerate(accepted):
                near=tree.query_ball_point(coords[i],16)
                if p['glyph_pixels']>=3 or any(2<np.linalg.norm(coords[i]-coords[j])<=16 for j in near):retained.append(p)
                else:refused+=1
            accepted=retained
        accepted.sort(key=lambda p:(p['reference_xy'][1],p['reference_xy'][0]))
        for i,p in enumerate(accepted):p['id']=label+'-'+str(i);points.append(p)
        rejected[label] = refused
    return points, rejected


def register(points, registration):
    matrix = np.asarray(registration['reference_to_clean'], np.float64)
    if matrix.shape != (2,3) or not np.isfinite(matrix).all() or not .1 <= abs(np.linalg.det(matrix[:,:2])) <= 10:
        raise ValueError('Finite bounded nonsingular reference registration required')
    if registration['inliers'] < 12 or not 0 <= registration['inlier_error_clean_pixels_p95'] <= 2:
        raise ValueError('At least twelve matches and at most two-pixel p95 registration required')
    width,height = registration['clean_size']; result=[]
    for p in points:
        xy = matrix[:,:2]@p['reference_xy']+matrix[:,2]
        if not 0 <= xy[0] < width or not 0 <= xy[1] < height:
            raise ValueError('Marker maps outside retained clean imagery')
        result.append({**p,'clean_xy':xy.tolist()})
    return result


def sparse_targets(points, shape):
    """Red dots supervise boundary presence; offset negatives are explicitly derived."""
    coords = np.array([p['clean_xy'] for p in points if p['label']=='path_boundary'])
    if not 12 <= len(coords) <= 2000: raise ValueError('Twelve to two thousand boundary points required')
    target = np.full(shape,255,np.uint8); tree=cKDTree(coords)
    yy,xx=np.indices(shape); distances=tree.query(np.column_stack([xx.ravel(),yy.ravel()]))[0].reshape(shape)
    negative=np.zeros(shape,bool)
    for p in coords:
        neighbours=coords[tree.query_ball_point(p,18)]
        if len(neighbours)<3: continue
        # Local tangent from the nearby plotted points; never interpolate a long gap.
        centered=neighbours-neighbours.mean(axis=0);_,vectors=np.linalg.eigh(centered.T@centered)
        tangent=vectors[:,-1];normal=np.array([-tangent[1],tangent[0]])
        for sign in (-1,1):
            for offset in (6.,9.):
                x,y=np.rint(p+sign*offset*normal).astype(int)
                if 1<=x<shape[1]-1 and 1<=y<shape[0]-1:negative[y-1:y+2,x-1:x+2]=True
    target[negative & (distances>4)] = 0
    target[distances<=1.5]=1
    return target


def fill_tree_gaps(footprint, visible_path, canopy, buildings, water, grass_islands=None):
    """Continue established ground paths under canopy, preserving hard exclusions."""
    if not isinstance(footprint,np.ndarray) or footprint.dtype!=bool or footprint.ndim!=2 or footprint.size>1048576:
        raise ValueError('Bounded boolean established path footprint required')
    if grass_islands is None:grass_islands=np.zeros(footprint.shape,bool)
    arrays=(footprint,visible_path,canopy,buildings,water,grass_islands)
    if any(not isinstance(a,np.ndarray) or a.dtype!=bool or a.shape!=footprint.shape for a in arrays):
        raise ValueError('Matching bounded boolean ground/canopy/exclusion masks required')
    allowed=footprint & ~buildings & ~water & ~grass_islands
    observed=visible_path & allowed
    labels,count=ndimage.label(allowed)
    anchored=np.unique(labels[observed]);anchored=anchored[anchored>0]
    inferred=canopy & allowed & ~observed & np.isin(labels,anchored)
    # Trees remain a separate overhead layer. Unconnected nearby trees create no path.
    return observed | inferred, inferred


def validate_model(model):
    tasks={MODEL_VERSION:'projected_path_boundary_not_paving',WATER_MODEL_VERSION:'projected_water_boundary_not_water_surface'}
    if model.get('version') not in tasks or model.get('task')!=tasks[model['version']] or model.get('labels')!=BOUNDARY_LABELS or model.get('marker_colors_used_as_features') is not False:
        raise ValueError('Dedicated source-only path-boundary checkpoint required')
    if model.get('artifact_sha256')!=digest({k:v for k,v in model.items() if k!='artifact_sha256'}):
        raise ValueError('Pinned boundary checkpoint required')
    view={**model,'version':binary.MODEL_VERSION,'labels':binary.masks.LABELS};view['artifact_sha256']=digest({k:v for k,v in view.items() if k!='artifact_sha256'})
    binary.validate_model(view)
    return view


def probabilities(features, model):
    return binary.probabilities(features,validate_model(model))[:,:,1]


def _inputs(reference, clean, metadata, registration_file, water_role='location', fine_markers=False):
    if water_role not in ('location','boundary'):raise ValueError('Explicit water marker role required')
    reference,clean,metadata=map(Path,(reference,clean,metadata))
    registration,_=safe._json(Path(registration_file),2000000);receipt,_=safe._json(metadata,2000000)
    if reference.resolve()==clean.resolve() or file_hash(reference)!=registration['reference_sha256'] or file_hash(clean)!=registration['clean_source_sha256'] or file_hash(metadata)!=registration['metadata_sha256'] or receipt['image_sha256']!=file_hash(clean):
        raise ValueError('Separately pinned annotated reference and clean model input required')
    with Image.open(reference) as image:
        if image.width*image.height>1048576 or list(image.size)!=registration['reference_size']:raise ValueError('Bounded native reference dimensions required')
        points,rejected=extract(np.array(image.convert('RGB')),fine_markers=fine_markers)
    with Image.open(clean) as image:
        if image.width*image.height>1048576 or list(image.size)!=registration['clean_size'] or list(image.size)!=[receipt['width'],receipt['height']]:raise ValueError('Bounded native clean dimensions required')
        rgb=np.array(image.convert('RGB'))
    points=register(points,registration)
    if water_role=='boundary':
        points=[{**p,'label':'water_boundary' if p['label']=='water_location' else p['label']} for p in points]
    target=sparse_targets(points,rgb.shape[:2]);features=binary._features(rgb,receipt,lambda:False)
    pinned={'reference_sha256':file_hash(reference),'clean_source_sha256':file_hash(clean),
        'registration_sha256':file_hash(registration_file),'metadata_sha256':file_hash(metadata)}
    return receipt,points,rejected,rgb,target,features,pinned


def train(reference, clean, metadata, registration_file, output):
    output=Path(output)
    if output.exists():raise ValueError('Fresh boundary-learning output required')
    reference,clean,metadata=map(Path,(reference,clean,metadata))
    receipt,points,rejected,rgb,target,features,pinned=_inputs(reference,clean,metadata,registration_file)
    from .imagery_capture_quality import audit
    sampling=audit(receipt)['approx_export_ground_sampling_m_xy'][0]
    radius=round(12/sampling)
    width=rgb.shape[1];split=3*width//4;guard=max(32,radius+2)
    yy,xx=np.indices(target.shape);known=target!=255
    train_mask=known & (xx<split-guard);held_mask=known & (xx>=split+guard)
    if any(np.count_nonzero(mask & (target==c))<20 for mask in (train_mask,held_mask) for c in (0,1)):
        raise ValueError('Both boundary classes need at least twenty samples on each spatial side')
    settings={**net.DEFAULTS,'hidden':64,'epochs':90};pinned={'reference_sha256':file_hash(reference),
        'clean_source_sha256':file_hash(clean),'registration_sha256':file_hash(registration_file),'metadata_sha256':file_hash(metadata)}
    dataset_id=digest({'pins':pinned,'points':points,'version':VERSION})
    output.mkdir(parents=True)
    atomic_json(output/'design.json',{'version':VERSION,'pins':pinned,'settings':settings,'score_threshold':.5,
        'split_x':split,'guard_each_side_pixels':guard,'feature_max_radius_pixels':radius,
        'held_out_scope':'right-hand area of the same site/image; not a whole-park or independent blind test',
        'negative_labels':'Derived six/nine-pixel local-normal offsets, not user-authored non-boundary truth'})
    def fit(mask):return net.fit(features[mask],target[mask],settings,class_count=2)
    def wrap(fit,role):
        manifest={'id':dataset_id};rows=[{'record':{'id':'user-towers-mutiny','site_id':'alton-towers','source_sha256':file_hash(clean)}}]
        model=binary._model(fit,'rgb_context',manifest,dataset_id,rows)
        model.update(version=MODEL_VERSION,task='projected_path_boundary_not_paving',labels=BOUNDARY_LABELS,marker_colors_used_as_features=False,
            user_marker_reference_sha256=file_hash(reference),role=role,labels_are_projected_user_guides=True)
        model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'});validate_model(model);return model
    held_model=wrap(fit(train_mask),'spatial_holdout_checkpoint');atomic_json(output/'spatial-holdout-model.json',held_model)
    p=probabilities(features,held_model);pred=p>=.5;selected=held_mask
    matrix=np.bincount(target[selected].astype(int)*2+pred[selected],minlength=4).reshape(2,2)
    tn,fp,fn,tp=matrix.ravel();precision=float(tp/max(1,tp+fp));recall=float(tp/max(1,tp+fn))
    score={'confusion':matrix.tolist(),'boundary_precision':precision,'boundary_recall':recall,
        'boundary_f1':2*precision*recall/max(1e-12,precision+recall),'known_samples':int(selected.sum()),
        'scope':'Same-site spatial holdout against sparse user boundary dots and derived offset negatives, not surveyed full boundary geometry'}
    prevalence=float((target[selected]==1).mean())
    score['always_boundary_reference']={'precision':prevalence,'recall':1.,'f1':2*prevalence/(1+prevalence)}
    final=wrap(fit(known),'all_user_guidance_fitted_research_checkpoint');atomic_json(output/'model.json',final)
    values=probabilities(features,final);Image.fromarray(np.rint(values*255).astype(np.uint8)).save(output/'boundary-probability.png')
    Image.fromarray(target).save(output/'sparse-targets.png');split_targets=np.full(target.shape,255,np.uint8);split_targets[held_mask]=target[held_mask];Image.fromarray(split_targets).save(output/'spatial-test-targets.png')
    atomic_json(output/'points.json',{'version':VERSION,'pins':pinned,'points':points,'rejected_components':rejected,
        'tree_glyph_size_is_not_canopy_extent':True,'blue_points_are_water_locations_not_verified_shoreline':True})
    report={'version':VERSION,'counts':{label:sum(p['label']==label for p in points) for label in ['path_boundary','tree_location','water_location']},
        'training_samples':int(train_mask.sum()),'all_guidance_samples':int(known.sum()),'spatial_holdout':score,
        'head_parameters_updated_l2':final['network']['weight_change_l2'],'model_sha256':file_hash(output/'model.json'),
        'production_eligible':False,'human_labels_verified':False,'user_authored_points':True,
        'continuous_edges_independently_verified':False,'general_accuracy_improvement_established':False,
        'replaces_paving_model':False,'tree_rule':'Continue established path footprint beneath overlapping canopy; retain buildings/water/grass-island exclusions.'}
    atomic_json(output/'report.json',report);return report


def train_many(entries, output):
    """Leave whole annotated images out; the final checkpoint fits both user examples."""
    from pyproj import Transformer
    output=Path(output)
    if output.exists() or not isinstance(entries,list) or not 2<=len(entries)<=4:
        raise ValueError('Fresh output and two to four user examples required')
    if any(not isinstance(e,dict) or any(not isinstance(e.get(k),str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',e[k]) for k in ('id','site_id')) for e in entries):
        raise ValueError('Safe bounded example and site IDs required')
    if len({e['id'] for e in entries})!=len(entries):raise ValueError('Distinct example IDs required')
    records=[];pixels=0
    for entry in entries:
        receipt,points,rejected,rgb,target,features,pins=_inputs(entry['reference'],entry['clean'],entry['metadata'],entry['registration'],entry.get('water_role','location'),entry.get('fine_markers',False))
        pixels+=target.size
        if pixels>3000000:raise ValueError('Three-megapixel combined feature budget exceeded')
        indices=np.flatnonzero(target.ravel()!=255)
        if len(indices)>60000:raise ValueError('Bounded sparse supervision required')
        y,x=np.unravel_index(indices,target.shape);ext=receipt['extent_epsg3857'];world=np.column_stack([ext[0]+x/rgb.shape[1]*(ext[2]-ext[0]),ext[3]-y/rgb.shape[0]*(ext[3]-ext[1])])
        # UK projected metres support a 24 m feature-context guard between images.
        xx,yy=Transformer.from_crs(3857,27700,always_xy=True).transform(world[:,0],world[:,1])
        records.append({'entry':entry,'pins':pins,'points':points,'rejected':rejected,'rgb':rgb,
            'features':features,'target':target,'indices':indices,'world':np.column_stack([xx,yy])})
    if len({r['pins']['clean_source_sha256'] for r in records})!=len(records):
        raise ValueError('Same clean image cannot masquerade as different held-out examples')
    settings={**net.DEFAULTS,'hidden':64,'epochs':90}
    dataset_id=digest({'version':'multi-user-boundary-v1','examples':[{**r['pins'],'id':r['entry']['id'],'water_role':r['entry'].get('water_role','location'),'fine_markers':r['entry'].get('fine_markers',False)} for r in records]})
    def samples(rows):
        x=np.concatenate([r['features'].reshape(-1,31)[r['indices']] for r in rows]);y=np.concatenate([r['target'].ravel()[r['indices']] for r in rows])
        if len(y)>100000:raise ValueError('Combined neural sample budget exceeded')
        return x,y
    def wrap(fit,rows,role):
        provenance=[{'record':{'id':r['entry']['id'],'site_id':r['entry']['site_id'],'source_sha256':r['pins']['clean_source_sha256']}} for r in rows]
        model=binary._model(fit,'rgb_context',{'id':dataset_id},dataset_id,provenance)
        model.update(version=MODEL_VERSION,labels=BOUNDARY_LABELS,task='projected_path_boundary_not_paving',
            marker_colors_used_as_features=False,role=role,labels_are_projected_user_guides=True,
            user_marker_reference_sha256=sorted(r['pins']['reference_sha256'] for r in rows))
        model['artifact_sha256']=digest({k:v for k,v in model.items() if k!='artifact_sha256'});validate_model(model);return model
    output.mkdir(parents=True)
    atomic_json(output/'design.json',{'version':'multi-user-boundary-v1','dataset_id':dataset_id,'settings':settings,
        'examples':[{**r['pins'],'id':r['entry']['id'],'water_role':r['entry'].get('water_role','location'),'fine_markers':r['entry'].get('fine_markers',False)} for r in records],
        'threshold':.5,'cross_image_context_guard_m':24.,'evaluation':'leave_whole_image_out_same_park_development'})
    folds=[]
    for held in records:
        fitting=[r for r in records if r is not held];x,y=samples(fitting)
        model=wrap(net.fit(x,y,settings,class_count=2),fitting,'whole_image_held_out')
        folder=output/'folds'/held['entry']['id'];folder.mkdir(parents=True);atomic_json(folder/'model.json',model)
        distances=cKDTree(np.concatenate([r['world'] for r in fitting])).query(held['world'])[0];selected=distances>=24
        if selected.sum()<40:raise ValueError('Insufficient held-out samples after geographic context guard')
        f=held['features'].reshape(-1,31)[held['indices'][selected]]
        # Binary predictor accepts a 2-D feature matrix through the validated view.
        p=binary.probabilities(f,validate_model(model))[:,1];truth=held['target'].ravel()[held['indices'][selected]]
        matrix=np.bincount(truth.astype(int)*2+(p>=.5),minlength=4).reshape(2,2);tn,fp,fn,tp=matrix.ravel()
        precision=float(tp/max(1,tp+fp));recall=float(tp/max(1,tp+fn));prevalence=float((truth==1).mean())
        scores={'held_out_id':held['entry']['id'],'confusion':matrix.tolist(),'boundary_precision':precision,
            'boundary_recall':recall,'boundary_f1':2*precision*recall/max(1e-12,precision+recall),
            'always_boundary_f1':2*prevalence/(1+prevalence),'known_samples':int(selected.sum()),
            'context_guard_excluded_samples':int((~selected).sum()),'minimum_training_distance_m':float(distances[selected].min()),
            'held_out_source_in_fitting':held['pins']['clean_source_sha256'] in model['training_source_sha256']}
        atomic_json(folder/'report.json',scores);folds.append(scores)
    x,y=samples(records);model=wrap(net.fit(x,y,settings,class_count=2),records,'all_user_examples_fitted_research_checkpoint');atomic_json(output/'model.json',model)
    for r in records:
        folder=output/'examples'/r['entry']['id'];folder.mkdir(parents=True)
        values=probabilities(r['features'],model);Image.fromarray(np.rint(values*255).astype(np.uint8)).save(folder/'fitted-boundary-probability.png')
        Image.fromarray(r['target']).save(folder/'sparse-targets.png')
        atomic_json(folder/'points.json',{'points':r['points'],'pins':r['pins'],'rejected_components':r['rejected'],
            'water_role':r['entry'].get('water_role','location'),'continuous_geometry_verified':False})
    water_records=[r for r in records if sum(p['label']=='water_boundary' for p in r['points'])>=12]
    water_report=None
    if water_records:
        xs=[];ys=[];water_targets=[]
        for r in water_records:
            boundary_points=[{**p,'label':'path_boundary'} for p in r['points'] if p['label']=='water_boundary']
            target=sparse_targets(boundary_points,r['target'].shape);selected=target!=255
            xs.append(r['features'][selected]);ys.append(target[selected]);water_targets.append(target)
        wx,wy=np.concatenate(xs),np.concatenate(ys)
        water=wrap(net.fit(wx,wy,settings,class_count=2),water_records,'all_supplied_shoreline_points_fitted')
        water.update(version=WATER_MODEL_VERSION,task='projected_water_boundary_not_water_surface')
        water['artifact_sha256']=digest({k:v for k,v in water.items() if k!='artifact_sha256'});validate_model(water)
        atomic_json(output/'water-boundary-model.json',water)
        for r,target in zip(water_records,water_targets):
            folder=output/'examples'/r['entry']['id'];Image.fromarray(target).save(folder/'water-sparse-targets.png')
            Image.fromarray(np.rint(probabilities(r['features'],water)*255).astype(np.uint8)).save(folder/'fitted-water-boundary-probability.png')
        water_report={'example_ids':[r['entry']['id'] for r in water_records],'training_samples':len(wy),
            'water_boundary_points':sum(sum(p['label']=='water_boundary' for p in r['points']) for r in water_records),
            'location_only_blue_points_used_as_shoreline_truth':False,'validation':'fitted_only_no_independent_water_boundary_test',
            'head_parameters_updated_l2':water['network']['weight_change_l2'],'model_sha256':file_hash(output/'water-boundary-model.json')}
    report={'version':'multi-user-boundary-v1','examples':[{ 'id':r['entry']['id'],'counts':{k:sum(p['label']==k for p in r['points']) for k in ['path_boundary','tree_location','water_location','water_boundary']},'samples':len(r['indices'])} for r in records],
        'folds':folds,'all_training_samples':len(y),'head_parameters_updated_l2':model['network']['weight_change_l2'],
        'model_sha256':file_hash(output/'model.json'),'general_accuracy_improvement_established':False,
        'production_eligible':False,'replaces_paving_model':False,'same_park_examples':len({r['entry']['site_id'] for r in records})==1,
        'tree_overlap_policy_retained':True,'no_water_polygon_invented_from_open_boundary':True,'water_boundary_training':water_report}
    atomic_json(output/'report.json',report);return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','clean','metadata','registration','examples'):parser.add_argument('--'+name)
    parser.add_argument('--output',required=True);args=parser.parse_args(argv)
    if args.examples:
        path=Path(args.examples).resolve();entries,_=safe._json(path,2000000)
        for entry in entries:
            for key in ('reference','clean','metadata','registration'):entry[key]=str(safe._asset(path.parent,entry[key]))
        result=train_many(entries,args.output)
    else:
        if not all((args.reference,args.clean,args.metadata,args.registration)):parser.error('Supply --examples or all four single-example inputs')
        result=train(args.reference,args.clean,args.metadata,args.registration,args.output)
    print(json.dumps(result))


if __name__=='__main__':main()
