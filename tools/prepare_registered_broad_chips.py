"""Build conservative 1m grass/generic-paving targets from reviewed view fits."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from affine import Affine
from rasterio.warp import reproject, Resampling
from scipy.ndimage import binary_erosion
from shapely.geometry import Polygon, box

from voxel_mapper.recover_paving_georef import load_reference_mosaic


def conservative_labels(labels, transform, target_transform, shape, known, *, threshold=.95):
    """Ignore uncertain class edges and unknowns; never generate fine materials."""
    if set(np.unique(labels))-{1,9,255}:
        raise ValueError('Only reviewed broad grass/paving masks are supported')
    if not .5<threshold<=1:
        raise ValueError('A strict majority class threshold is required')
    result = np.full(shape,255,np.uint8)
    for code in (1,9):
        fraction = np.zeros(shape,np.float32)
        reproject((labels==code).astype(np.float32),fraction,src_transform=transform,
                  src_crs='EPSG:27700',dst_transform=target_transform,dst_crs='EPSG:27700',
                  src_nodata=None,dst_nodata=0,resampling=Resampling.average)
        # Full zero-valued unknown source pixels remain in the denominator.
        selected = binary_erosion((fraction>=threshold)&known,structure=np.ones((3,3)),border_value=0)
        result[selected] = code
    return result


def merge_labels(current, incoming, conflict):
    """One cell per location; source disagreements remain ignored permanently."""
    differing = (current!=255)&(incoming!=255)&(current!=incoming)
    conflict |= differing
    selected = (incoming!=255)&~conflict
    current[selected] = incoming[selected]
    current[conflict] = 255


def validation_bounds(xx, yy, shape, margin):
    """Expand by whole inference tiles; refuse a shifted origin at grid edges."""
    if margin < 0 or margin % 64:
        raise ValueError("Validation margin must be a nonnegative multiple of 64 to preserve tile phase")
    x0,y0,x1,y1 = int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)
    if x0 < margin or y0 < margin:
        raise ValueError("Reference boundary would change validation tile phase")
    return x0-margin,y0-margin,min(shape[1],x1+margin),min(shape[0],y1+margin)


def _prepare(dataset, reference, output, holdout_sample, validation_margin=0):
    if output.exists() or output.resolve() in (dataset.resolve(),reference.resolve()):
        raise ValueError('Use a fresh derivative output')
    rgb,known,base = load_reference_mosaic(reference)
    reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    shape = known.shape
    combined = np.full(shape,255,np.uint8)
    conflict = np.zeros(shape,bool)
    groups = np.full(shape,-1,np.int16)
    group_ids = []
    sources = []
    with zipfile.ZipFile(dataset) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        records = [r for r in manifest['samples'] if r.get('georef_provenance',{}).get('method')=='reviewed_direct_affine_image_match_with_spatial_holdouts']
        if any(r['georef_provenance']['reference_archive_sha256']!=reference_hash for r in records):
            raise ValueError('Registration and training RGB reference identities differ')
        selected = next((r for r in records if r['sample_id']==holdout_sample),None)
        if selected is None:
            raise ValueError('Holdout must be a reviewed registered view')
        holdout = selected['split_group']
        for record in records:
            if record['georef']['crs']!='EPSG:27700':
                raise ValueError('Native BNG source-relative fits required')
            image = np.asarray(Image.open(io.BytesIO(archive.read(record['labels']))).convert('L'))
            tf = Affine(*record['georef']['transform'])
            h,w = image.shape
            pixel = [~base*(tf*p) for p in ((0,0),(w,0),(w,h),(0,h))]
            x0,y0 = np.maximum(0,np.floor(np.min(pixel,axis=0))).astype(int)
            x1,y1 = np.minimum([shape[1],shape[0]],np.ceil(np.max(pixel,axis=0))).astype(int)
            proposal = conservative_labels(image,tf,base*Affine.translation(x0,y0),(y1-y0,x1-x0),known[y0:y1,x0:x1])
            group = record['split_group']
            if group not in group_ids:group_ids.append(group)
            index = group_ids.index(group)
            old_groups = groups[y0:y1,x0:x1]
            if np.any((proposal!=255)&(old_groups!=-1)&(old_groups!=index)):
                raise ValueError('Separate geographic groups unexpectedly overlap')
            old_groups[proposal!=255] = index
            merge_labels(combined[y0:y1,x0:x1],proposal,conflict[y0:y1,x0:x1])
            sources.append({'sample_id':record['sample_id'],'group':group,
                            'original_label_observations':int(np.count_nonzero(image!=255)),
                            'conservative_1m_cells':int(np.count_nonzero(proposal!=255))})
    hold_mask = (groups==group_ids.index(holdout))&(combined!=255)
    yy,xx = np.where(hold_mask)
    if not len(xx):raise ValueError('No conservative holdout cells')
    vx0,vy0,vx1,vy1 = validation_bounds(xx,yy,shape,validation_margin)
    validation_box = box(vx0,vy0,vx1,vy1)
    records = []
    train_covered = np.zeros(shape,bool)
    min_separation = float('inf')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        def write(x,y,w,h,group,labels):
            name = f'{group}_{x}_{y}'
            for role,values in (('rgb',rgb[y:y+h,x:x+w]),('labels',labels)):
                stream = io.BytesIO();Image.fromarray(values).save(stream,format='PNG')
                archive.writestr(name+'_'+role+'.png',stream.getvalue())
            transform = base*Affine.translation(x,y)
            records.append({'sample_id':name,'split_group':group,'image':name+'_rgb.png',
                            'labels':name+'_labels.png','georef':{'crs':'EPSG:27700','transform':list(transform)[:6]}})
        validation = np.where(hold_mask[vy0:vy1,vx0:vx1],combined[vy0:vy1,vx0:vx1],255).astype(np.uint8)
        for code in (1,9):
            if np.count_nonzero(validation==code)<20:
                raise ValueError('Holdout lacks sufficient reviewed pixels for both broad classes')
        write(vx0,vy0,vx1-vx0,vy1-vy0,holdout,validation)
        for index,group in enumerate(group_ids):
            if group==holdout:continue
            active = (groups==index)&(combined!=255)
            rows,cols = np.where(active)
            if not len(rows):continue
            for y in range(max(0,int(rows.min())//32*32-32),min(shape[0]-63,int(rows.max())+1),32):
                for x in range(max(0,int(cols.min())//32*32-32),min(shape[1]-63,int(cols.max())+1),32):
                    separation = box(x,y,x+64,y+64).distance(validation_box)
                    if separation<34 or known[y:y+64,x:x+64].mean()<.9:continue
                    mask = np.where(active[y:y+64,x:x+64],combined[y:y+64,x:x+64],255).astype(np.uint8)
                    if np.count_nonzero(mask!=255)<8:continue
                    write(x,y,64,64,group,mask)
                    train_covered[y:y+64,x:x+64] |= mask!=255
                    min_separation = min(min_separation,separation)
        if len(records)<2:raise ValueError('No separated labelled training windows')
        report = {'schema':'reviewed-broad-area-pilot-v1','park_id':manifest['park_id'],
                  'label_map':{'1':'grass_unspecified','9':'paving_unspecified'},'samples':records,
                  'registration_filter_required':True,'source_dataset_sha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),
                  'reference_archive_sha256':reference_hash,
                  'validation_margin_pixels':validation_margin,
                  'holdout_group':holdout,'holdout_sample':holdout_sample,'source_views':sources,
                  'conflicting_1m_cells_ignored':int(conflict.sum()),'unique_conservative_cells':int(np.count_nonzero(combined!=255)),
                  'train_unique_labelled_pixels':int(train_covered.sum()),'validation_unique_labelled_pixels':int(hold_mask.sum()),
                  'train_class_counts':{str(k):int(np.count_nonzero(train_covered&(combined==k))) for k in (1,9)},
                  'validation_class_counts':{str(k):int(np.count_nonzero(validation==k)) for k in (1,9)},
                  'minimum_train_image_to_validation_image_separation_m':min_separation,
                  'policy':'Same reference acquisition; separate geographic areas, not independent source/park test. 95% class coverage and a one-cell boundary erosion. Overlaps deduplicated; conflicts ignored. Broad labels only; no new fine material labels.'}
        archive.writestr('manifest.json',json.dumps(report,indent=2))
    return report


def prepare(dataset, reference, output, holdout_sample, validation_margin=0):
    if output.exists() or output.resolve() in (dataset.resolve(),reference.resolve()):
        raise ValueError('Use a fresh derivative output')
    temporary = output.with_suffix(output.suffix+'.tmp')
    if temporary.exists():
        raise ValueError('Temporary output already exists')
    try:
        report = _prepare(dataset,reference,temporary,holdout_sample,validation_margin)
        temporary.replace(output)
        return report
    finally:
        temporary.unlink(missing_ok=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','reference','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--holdout-sample',required=True)
    parser.add_argument('--validation-margin',type=int,default=0)
    args = parser.parse_args()
    report = prepare(args.dataset,args.reference,args.output,args.holdout_sample,args.validation_margin)
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
