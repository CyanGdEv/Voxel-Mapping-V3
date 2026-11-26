"""Score held-out candidate rasters; never accept them as world evidence."""
import argparse
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import rasterio
from affine import Affine
from voxel_mapper.predict_ground_model import predict


def score(target, predicted, confidence, classes=10, bins=15):
    valid=target!=255
    t,p,c=target[valid].astype(int),predicted[valid].astype(int),confidence[valid]
    if not len(t) or np.any((p<0)|(p>=classes)) or not np.isfinite(c).all() or np.any((c<0)|(c>1)):
        raise ValueError('Invalid candidate scores or empty reviewed targets')
    cm=np.bincount(t*classes+p,minlength=classes*classes).reshape(classes,classes)
    correct=t==p
    ece=0.
    reliability=[]
    for index in range(bins):
        selected=np.minimum((c*bins).astype(int),bins-1)==index
        n=int(selected.sum())
        accuracy=float(correct[selected].mean()) if n else None
        certainty=float(c[selected].mean()) if n else None
        if n:ece+=n/len(t)*abs(accuracy-certainty)
        reliability.append({'count':n,'accuracy':accuracy,'mean_confidence':certainty})
    per_class={}
    for k in np.flatnonzero(cm.sum(1)):
        tp=int(cm[k,k]);fp=int(cm[:,k].sum()-tp);fn=int(cm[k,:].sum()-tp)
        negatives=int(cm.sum()-cm[k,:].sum())
        per_class[str(k)]={'iou':tp/(tp+fp+fn),'precision':tp/(tp+fp) if tp+fp else None,
                          'recall':tp/(tp+fn),'false_positive_rate':fp/negatives if negatives else None}
    return {'reviewed_pixels':len(t),'confusion_matrix':cm.tolist(),'per_class':per_class,
            'mean_iou':float(np.mean([v['iou'] for v in per_class.values()])),
            'pixel_accuracy':float(correct.mean()),'top_label_ece_15_bins':ece,'reliability_bins':reliability,
            'boundary_accuracy':None,'missing_geometry_rate':None,
            'limitations':'Eroded interior labels cannot validate true material boundaries. Pixel classification does not measure reconstructed geometry. Top-label ECE is descriptive on validation-selected checkpoints, not independent calibration.'}


def evaluate(checkpoint,dataset,group,output):
    output.mkdir(parents=True,exist_ok=False)
    selected=output/'heldout.zip'
    with zipfile.ZipFile(dataset) as source,zipfile.ZipFile(selected,'w',zipfile.ZIP_DEFLATED) as dest:
        manifest=json.loads(source.read('manifest.json'))
        manifest['samples']=[r for r in manifest['samples'] if r['split_group']==group]
        if not manifest['samples']:raise ValueError('No held-out samples')
        members={r[key] for r in manifest['samples'] for key in ('image','labels','context') if r.get(key)}
        for name in sorted(members):dest.writestr(name,source.read(name))
        dest.writestr('manifest.json',json.dumps(manifest))
    result=predict(checkpoint,selected,output/'predictions')
    targets=[];predictions=[];confidences=[]
    with zipfile.ZipFile(selected) as source:
        for record,row in zip(manifest['samples'],result['samples']):
            target=np.asarray(Image.open(io.BytesIO(source.read(record['labels']))))
            arrays=[]
            for role in ('classes','uncalibrated_confidence'):
                with rasterio.open(output/'predictions'/row['files'][role]['path']) as src:
                    if src.shape!=target.shape or src.crs.to_string()!=record['georef']['crs'] or not src.transform.almost_equals(Affine(*record['georef']['transform'])):
                        raise ValueError('Prediction and reviewed target grids differ')
                    arrays.append(src.read(1))
            targets.append(target.ravel());predictions.append(arrays[0].ravel());confidences.append(arrays[1].ravel())
    report=score(np.concatenate(targets),np.concatenate(predictions),np.concatenate(confidences))
    report['candidate_provenance']=result
    (output/'evaluation.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint','dataset','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--group',required=True)
    args=parser.parse_args()
    evaluate(args.checkpoint,args.dataset,args.group,args.output)
