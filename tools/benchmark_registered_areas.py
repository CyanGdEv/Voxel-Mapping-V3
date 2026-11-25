"""Run predeclared, geographically held-out contextual source ablations.

Inputs must already have reviewed labels and buffered geographic splits. This
runner does not accept predictions for world placement or create new labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from voxel_mapper.train_ground_model import train, _read_samples, _split
from voxel_mapper.multisource_chips import GROUPS

MODES = {
    'rgb': {},
    'zero28': {'context_baseline':True},
    'vectors': {'context_group':[name for name,_ in GROUPS[:6]]},
    'landcover': {'context_group':['landcover']},
    'height': {'context_group':['height']},
    'intensity': {'context_group':['intensity']},
    'full': {},
    'full_scaled': {'context_normalization':'train_p95'},
}


def coverage(samples):
    result = {}
    offset = 0
    for name,size in GROUPS:
        arrays = [s.context[s.labels!=255,offset:offset+size] for s in samples if s.context is not None]
        values = np.concatenate(arrays) if arrays else np.empty((0,size))
        known = values[:,-1]==1
        observed = values[known,:-1]
        result[name] = {'labelled_input_observations':len(values), 'known_observations':int(known.sum()),
                        'known_fraction':float(known.mean()) if len(known) else None,
                        'observed_value_percentiles':np.percentile(observed,[0,50,95,100],axis=0).tolist() if len(observed) else None}
        offset += size
    return result


def metrics(report):
    cm = np.asarray(report['validation_confusion_matrix'])
    union = cm.sum(0)+cm.sum(1)-cm.diagonal()
    # Retain trainer metric; additionally expose fixed reviewed class denominator.
    supported = cm.sum(1)>0
    return {'mean_iou':report['training']['best_validation_mean_iou'],
            'reviewed_class_mean_iou':float(np.mean(cm.diagonal()[supported]/union[supported])),
            'pixel_accuracy':float(cm.trace()/cm.sum()),
            'predicted_unsupported_class_pixels':int(cm[:,~supported].sum()),
            'per_class':report['per_class'] if 'per_class' in report else report.get('validation_per_class')}


def run(datasets, output, seeds, epochs):
    output.mkdir(parents=True,exist_ok=False)
    config={'schema':'registered-area-ablation-v1','seeds':seeds,'epochs':epochs,'modes':MODES,
            'datasets':{k:{'path':str(v),'sha256':hashlib.sha256(v.read_bytes()).hexdigest()} for k,v in datasets.items()},
            'policy':'Checkpoint selection uses validation; no independent test or model promotion. Overlapping training observations are not independent. Broad grass/paving only.'}
    (output/'configuration.json').write_text(json.dumps(config,indent=2))
    results=[]
    for area,dataset in datasets.items():
        with zipfile.ZipFile(dataset) as z: manifest=json.loads(z.read('manifest.json'))
        samples,_,_=_read_samples(dataset,use_context=True,require_georeference=True)
        tr,va,_=_split(samples,.2,seeds[0],None,[manifest['holdout_group']])
        (output/f'{area}-coverage.json').write_text(json.dumps({'train':coverage(tr),'validation':coverage(va),
           'train_unique_labelled_pixels':manifest['train_unique_labelled_pixels'],
           'validation_unique_labelled_pixels':manifest['validation_unique_labelled_pixels'],
           'separation_m':manifest['minimum_train_image_to_validation_image_separation_m']},indent=2))
        for seed in seeds:
            for mode,options in MODES.items():
                args=argparse.Namespace(dataset=[dataset],output=output/area/str(seed)/mode,
                   validation_group=[manifest['holdout_group']],require_georeference=True,
                   holdout_park=None,validation_fraction=.2,num_classes=10,epochs=epochs,
                   batch_size=4,patch_size=64,learning_rate=.001,seed=seed,threads=2,cpu=True,
                   multisource=mode!='rgb',context_dropout=.2,**options)
                report=train(args)
                row={'area':area,'seed':seed,'mode':mode,**metrics(report)}
                results.append(row)
                (output/'results.json').write_text(json.dumps(results,indent=2))
                print(json.dumps({k:v for k,v in row.items() if k!='per_class'}),flush=True)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',action='append',required=True,help='AREA=PATH; repeat per held-out area')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,action='append')
    parser.add_argument('--epochs',type=int,default=20)
    args=parser.parse_args()
    datasets={}
    for entry in args.dataset:
        name,path=entry.split('=',1)
        if not name.isalnum() or name in datasets:parser.error('Unique alphanumeric area names required')
        datasets[name]=Path(path)
    run(datasets,args.output,args.seed or [41,42,43],args.epochs)


if __name__=='__main__':main()
