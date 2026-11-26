"""Evaluate frozen RGB plus bounded context correction on existing area folds."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
from voxel_mapper.train_ground_model import train
from voxel_mapper.benchmark_multisource import compare
from tools.evaluate_ground_candidates import evaluate


def run(baselines, output, rgb_only=False):
    config=json.loads((baselines/'configuration.json').read_text())
    if config['seeds'] != [41,42,43] or config['epochs'] != 20:
        raise ValueError('Expected recorded three-seed, 20-epoch area benchmark')
    output.mkdir(parents=True,exist_ok=False)
    settings={'architecture':'rgb_residual_control_v1' if rgb_only else 'rgb_residual_v1','residual_rgb_only':rgb_only,'residual_bound':1.,'residual_penalty':.05,
              'epochs':20,'batch_size':4,'patch_size':64,'learning_rate':.001,'context_dropout':.2,
              'context_normalization':'train_p95','threads':2,'cpu':True}
    (output/'configuration.json').write_text(json.dumps({'baseline_configuration':config,'settings':settings,
         'policy':'Frozen validation-selected RGB warm starts plus 20 adapter epochs; not compute-matched from-scratch training. Epoch-zero fallback is selected on validation. No independent final test or world acceptance.'},indent=2))
    rows=[]
    for area,source in config['datasets'].items():
        dataset=Path(source['path'])
        if hashlib.sha256(dataset.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('Dataset identity changed')
        with zipfile.ZipFile(dataset) as z:group=json.loads(z.read('manifest.json'))['holdout_group']
        for seed in config['seeds']:
            teacher=baselines/area/str(seed)/'rgb'
            args=argparse.Namespace(dataset=[dataset],output=output/area/str(seed),rgb_checkpoint=teacher/'model.pt',
                holdout_park=None,validation_group=[group],validation_fraction=.2,require_georeference=True,
                seed=seed,num_classes=10,multisource=True,**{k:v for k,v in settings.items() if k!='architecture'})
            result=train(args)
            baseline=json.loads((teacher/'training-report.json').read_text())
            if abs(result['epoch_zero_mean_iou']-baseline['training']['best_validation_mean_iou'])>1e-12:
                raise ValueError('Epoch-zero candidate differs from paired RGB baseline')
            comparison=compare(baseline,result)
            e=evaluate(args.output/'model.pt',dataset,group,args.output/'evaluation')
            np.testing.assert_array_equal(e['confusion_matrix'],result['validation_confusion_matrix'])
            changed=0;baseline_correct_harmed=0;baseline_errors_fixed=0
            # Confusion matrices alone cannot establish which individual cells changed.
            import rasterio
            base_eval=baselines/'heldout-evaluation'/area/str(seed)/'rgb'
            predicted=e['candidate_provenance']['samples']
            base_pred=json.loads((base_eval/'evaluation.json').read_text())['candidate_provenance']['samples']
            for row,base in zip(predicted,base_pred):
                with rasterio.open(args.output/'evaluation/predictions'/row['files']['classes']['path']) as src:a=src.read(1)
                with rasterio.open(base_eval/'predictions'/base['files']['classes']['path']) as src:b=src.read(1)
                with zipfile.ZipFile(args.output/'evaluation/heldout.zip') as z:
                    import io
                    from PIL import Image
                    manifest=json.loads(z.read('manifest.json'))
                    record=next(r for r in manifest['samples'] if r['sample_id']==row['sample_id'])
                    target=np.asarray(Image.open(io.BytesIO(z.read(record['labels']))))
                valid=target!=255
                changed+=int(np.count_nonzero(valid&(a!=b)))
                baseline_correct_harmed+=int(np.count_nonzero(valid&(b==target)&(a!=target)))
                baseline_errors_fixed+=int(np.count_nonzero(valid&(b!=target)&(a==target)))
            row={'area':area,'seed':seed,**comparison,'changed_reviewed_pixels':changed,
                 'baseline_correct_pixels_harmed':baseline_correct_harmed,'baseline_errors_fixed':baseline_errors_fixed,
                 'top_label_ece_15_bins':e['top_label_ece_15_bins']}
            rows.append(row)
            (output/'results.json').write_text(json.dumps(rows,indent=2))
            print(json.dumps({k:v for k,v in row.items() if k not in ('per_class','split','policy')}),flush=True)
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baselines',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument("--rgb-only-control",action="store_true")
    args=parser.parse_args()
    run(args.baselines,args.output,args.rgb_only_control)
