"""CPU study training with untouched, explicitly reserved evaluation sites."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
from . import study_component_learning as learner
from .study_intake import reservation
from .generation_cycles import atomic_json


def train(directory,output,*,epochs=150,hidden_units=16,cancelled=lambda:False):
    if type(epochs) is not int or not 1<=epochs<=300 or type(hidden_units) is not int or not 1<=hidden_units<=32:
        raise ValueError('Bounded CPU training settings required')
    output=Path(output)
    if output.exists():raise ValueError('Fresh site evaluation output required')
    manifest,rows,x,pin=learner.read_dataset(directory,cancelled=cancelled,allow_reserved_evaluation=True)
    saved=manifest.get('site_reservation')
    if not isinstance(saved,dict):raise ValueError('Explicit site reservation required')
    actual=reservation(rows,saved['evaluation_sites'],manifest.get('context_assets',[]))
    if actual!=saved:raise ValueError('Site reservation changed or includes ineligible records')
    if actual['status']!='site_reservation_ready':raise ValueError('An independent evaluation site is required before training')
    train_ids=set(saved['training_record_ids']);test_ids=set(saved['evaluation_record_ids'])
    a=[i for i,r in enumerate(rows) if r['id'] in train_ids];b=[i for i,r in enumerate(rows) if r['id'] in test_ids]
    fitting=[rows[i] for i in a];held=[rows[i] for i in b]
    if not 2<=len({r['kind'] for r in fitting})<=16:raise ValueError('Two to sixteen training component classes required')
    if len(a)*epochs*learner.INPUT_SIZE**2*hidden_units>learner.MAX_TRAINING_WORK:raise ValueError('CPU site training work budget exceeded')
    learner._check(cancelled)
    model=learner._make_model(fitting,x[a],epochs,hidden_units,0,manifest['id'],cancelled,lambda p:None)
    learner.validate_model(model)
    probabilities=learner._probabilities(model,x[b]);predicted=[model['classes'][int(np.argmax(p))] for p in probabilities]
    truth=[r['kind'] for r in held];classes=sorted(set(model['classes'])|set(truth))
    majority=min(model['classes'],key=lambda k:(-sum(r['kind']==k for r in fitting),k))
    report={'version':'site-isolated-study-evaluation-v1','dataset_id':manifest['id'],'dataset_manifest_sha256':pin,
        'training_sites':saved['training_sites'],'evaluation_sites':saved['evaluation_sites'],
        'training_records':len(fitting),'evaluation_records':len(held),'training_sources':model['training_sources'],
        'evaluation_sources':sorted({r['source']['document_sha256'] for r in held}),
        'metrics':learner._metrics(truth,predicted,classes),'majority_baseline_metrics':learner._metrics(truth,[majority]*len(held),classes),
        'evaluation_classes_absent_from_training':saved['evaluation_classes_absent_from_training'],
        'predictions':[{'record_id':r['id'],'expected':t,'predicted':p} for r,t,p in zip(held,truth,predicted)],
        'model_sha256':model['artifact_sha256'],'model_weights_updated':True,'training_labels_generated':0,
        'final_checkpoint_fit':'training sites only; evaluation sites excluded from normalization and optimizer',
        'production_eligible':False,'physical_acceptance':False,'geometry_generated':False,
        'scope':learner.SCOPE,'limitations':['Results apply to supplied source crops and declared sites; no autonomous reconstruction accuracy is established.',
        'Keep a new untouched site for later model selection; repeatedly consulting a holdout can overfit it.']}
    learner._check(cancelled);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-site-eval-',dir=output.parent) as temp:
        stage=Path(temp)/'result';stage.mkdir();learner.save_model(model,stage/'model.json');atomic_json(stage/'report.json',report)
        learner._check(cancelled);shutil.move(stage,output)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--output',required=True)
    p.add_argument('--epochs',type=int,default=150);p.add_argument('--hidden-units',type=int,default=16)
    a=p.parse_args(argv);r=train(a.dataset,a.output,epochs=a.epochs,hidden_units=a.hidden_units)
    print(json.dumps({'training_records':r['training_records'],'evaluation_records':r['evaluation_records'],'metrics':r['metrics'],'production_eligible':False}))

if __name__=='__main__':main()
