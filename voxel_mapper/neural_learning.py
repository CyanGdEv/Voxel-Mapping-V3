"""Portable supervised neural candidate ranking; predictions never become evidence.

A small NumPy MLP learns six source/geometry diagnostic features from reviewed
outcomes. Checkpoints are open JSON data, not executable code. The model ranks
interpretations; it does not read drawings or generate physical geometry.
"""
from concurrent.futures import CancelledError
import copy
import math
import re

import numpy as np

from .building_learning import FEATURES, GATES, MAX_RECORDS, _features, _records
from .building_spec import digest

VERSION = 'building-neural-candidate-ranker-v1'
MAX_NEURAL_RECORDS = 10000
MAX_ROW_EPOCHS = 10_000_000
MAX_WEIGHTED_ROW_EPOCHS = 80_000_000
MIN_BUILDINGS_PER_SPLIT = 5


def _seal(model):
    model['artifact_sha256'] = digest({k:v for k,v in model.items() if k!='artifact_sha256'})
    return model


def _seed(value):
    if type(value) is not int or not 0<=value<2**32:
        raise ValueError('A bounded integer neural random seed is required')
    return value


def baseline(seed=0, hidden_units=12):
    """A neutral .5 checkpoint with a seeded, trainable hidden representation."""
    _seed(seed)
    if type(hidden_units) is not int or not 4<=hidden_units<=64:
        raise ValueError('Neural hidden width must be an integer between 4 and 64')
    rng=np.random.default_rng(seed)
    return _seal({'version':VERSION,'features':list(FEATURES),
        'architecture':{'input_units':len(FEATURES),'hidden_units':hidden_units,
                        'output_units':1,'hidden_activation':'tanh','output_activation':'sigmoid'},
        'parameters':{'hidden_weights':(rng.standard_normal((len(FEATURES),hidden_units))/math.sqrt(len(FEATURES))).tolist(),
                      'hidden_bias':[0.0]*hidden_units,'output_weights':[0.0]*hidden_units,'output_bias':0.0},
        'seed':seed,'iteration':0,'training_buildings':[],'training_sources':[],
        'evaluation_buildings':[],'evaluation_sources':[],
        'status':'untrained_baseline','production_eligible':False,
        'prediction_scope':'candidate priority only; not physical correctness, acceptance or park placement'})


def _identifiers(values,name,hashed=False):
    if not isinstance(values,list) or len(values)>MAX_RECORDS:
        raise ValueError('Bounded neural '+name+' required')
    if any(not isinstance(v,str) or not v or len(v)>512 or
           (hashed and not re.fullmatch('[0-9a-f]{64}',v)) for v in values):
        raise ValueError('Valid neural '+name+' required')
    if len(set(values))!=len(values):raise ValueError('Unique neural '+name+' required')
    return set(values)


def validate_model(model):
    """Validate bounded arrays and lineage, then the complete JSON integrity hash."""
    if not isinstance(model,dict) or model.get('version')!=VERSION or model.get('features')!=list(FEATURES):
        raise ValueError('Neural checkpoint version/feature schema mismatch')
    a=model.get('architecture')
    if (not isinstance(a,dict) or set(a)!={'input_units','hidden_units','output_units','hidden_activation','output_activation'}
            or a.get('input_units')!=len(FEATURES) or a.get('output_units')!=1
            or type(a.get('hidden_units')) is not int or not 4<=a['hidden_units']<=64
            or a.get('hidden_activation')!='tanh' or a.get('output_activation')!='sigmoid'):
        raise ValueError('Supported bounded neural architecture required')
    p=model.get('parameters');h=a['hidden_units']
    if not isinstance(p,dict) or set(p)!={'hidden_weights','hidden_bias','output_weights','output_bias'}:
        raise ValueError('Exact neural parameter schema required')
    expected={'hidden_weights':(len(FEATURES),h),'hidden_bias':(h,),'output_weights':(h,),'output_bias':()}
    for name,shape in expected.items():
        value=p[name]
        if shape==():
            if type(value) not in (int,float):raise ValueError('JSON scalar neural parameter required')
        elif shape==(len(FEATURES),h):
            if (not isinstance(value,list) or len(value)!=len(FEATURES)
                    or any(not isinstance(row,list) or len(row)!=h for row in value)
                    or any(type(v) not in (int,float) for row in value for v in row)):
                raise ValueError('Bounded JSON hidden-weight matrix required')
        elif not isinstance(value,list) or len(value)!=h or any(type(v) not in (int,float) for v in value):
            raise ValueError('Bounded JSON neural vector required')
    for name,shape in expected.items():
        try:array=np.asarray(p[name])
        except (TypeError,ValueError) as error:raise ValueError('Invalid neural parameter arrays') from error
        if (array.shape!=shape or array.dtype.kind not in 'fi' or not np.isfinite(array).all()
                or bool(np.any(np.abs(array)>100))):
            raise ValueError('Bounded finite neural parameter arrays required')
    _seed(model.get('seed'))
    if type(model.get('iteration')) is not int or model['iteration']<0 or type(model.get('production_eligible')) is not bool:
        raise ValueError('Valid neural iteration and eligibility metadata required')
    training=_identifiers(model.get('training_buildings'),'training buildings')
    evaluation=_identifiers(model.get('evaluation_buildings'),'evaluation buildings')
    train_sources=_identifiers(model.get('training_sources'),'training sources',True)
    eval_sources=_identifiers(model.get('evaluation_sources'),'evaluation sources',True)
    if training & evaluation or train_sources & eval_sources:
        raise ValueError('Neural checkpoint split/source leakage')
    if model.get('status') not in ('untrained_baseline','candidate_withheld','promotion_eligible'):
        raise ValueError('Valid neural model status required')
    if model['iteration']==0:
        if (model['status']!='untrained_baseline' or model['production_eligible'] or training or evaluation
                or train_sources or eval_sources):raise ValueError('Invalid untrained neural metadata')
    else:
        ev=model.get('evaluation')
        if (not isinstance(ev,dict) or not isinstance(ev.get('reasons'),list)
                or model['production_eligible']!=(model['status']=='promotion_eligible')
                or model['production_eligible']!=(not ev['reasons'])):
            raise ValueError('Neural promotion status and evaluation disagree')
        for name in ('parent_sha256','dataset_sha256'):
            if not isinstance(model.get(name),str) or not re.fullmatch('[0-9a-f]{64}',model[name]):
                raise ValueError('Neural checkpoint lineage digests required')
    try:expected_hash=digest({k:v for k,v in model.items() if k!='artifact_sha256'})
    except (TypeError,ValueError,OverflowError) as error:raise ValueError('JSON neural checkpoint required') from error
    if model.get('artifact_sha256')!=expected_hash:raise ValueError('Neural checkpoint changed')
    return model


def _arrays(model):
    p=model['parameters']
    return [np.asarray(p[name],dtype=np.float64).copy() for name in
            ('hidden_weights','hidden_bias','output_weights','output_bias')]


def _forward(parameters,x):
    w1,b1,w2,b2=parameters
    hidden=np.tanh(x@w1+b1)
    logits=hidden@w2+b2
    return hidden,1/(1+np.exp(-np.clip(logits,-60,60)))


def score(model,values):
    """Return an uncalibrated candidate ranking score, never a correctness fact."""
    validate_model(model)
    return float(_forward(_arrays(model),np.asarray([_features(values)],dtype=np.float64))[1][0])


def predict(model,values):
    """Compatibility alias for one six-feature diagnostic vector."""
    return score(model,values)


def rank(candidates,model=None):
    """Evidence gates remain mandatory regardless of neural scores."""
    model=model if model is not None else baseline();validate_model(model)
    if not isinstance(candidates,list) or not 1<=len(candidates)<=10000:
        raise ValueError('Bounded neural candidate batch required')
    ids=set();rows=[];parameters=_arrays(model)
    for candidate in candidates:
        identifier=candidate.get('id')
        if not isinstance(identifier,str) or not identifier or len(identifier)>512 or identifier in ids:
            raise ValueError('Unique bounded candidate IDs required')
        ids.add(identifier);failures=[g for g in GATES if candidate.get('gates',{}).get(g) is not True]
        value=float(_forward(parameters,np.asarray([_features(candidate['features'])],dtype=np.float64))[1][0])
        rows.append({'id':identifier,'score':value,'eligible_local_candidate':not failures,'failed_gates':failures})
    rows.sort(key=lambda r:(-r['score'],r['id']));eligible=[r for r in rows if r['eligible_local_candidate']]
    return {'version':VERSION,'model_sha256':model['artifact_sha256'],'ranking':rows,
            'selected_id':eligible[0]['id'] if eligible else None,'model_production_eligible':model['production_eligible'],
            'selection_scope':'local candidate priority only; not physical acceptance or park placement'}


def _snapshot(records):
    if not isinstance(records,list) or not 1<=len(records)<=MAX_NEURAL_RECORDS:
        raise ValueError('Reviewed neural training datasets are limited to 10,000 records')
    for row in records:
        if not isinstance(row,dict):raise ValueError('Reviewed feedback records must be objects')
        if any(not isinstance(row.get(k),str) or not row[k] or len(row[k])>512 for k in ('id','building_id')):
            raise ValueError('Bounded reviewed feedback identifiers required')
        if not isinstance(row.get('source_sha256'),list) or not 1<=len(row['source_sha256'])<=256:
            raise ValueError('Bounded complete feedback source sets required')
    _records(records)
    # Ignore unknown producer metadata, retaining the complete required review
    # identity, source set and outcomes. Predictions are rejected by _records.
    return [{k:copy.deepcopy(r[k]) for k in ('id','building_id','candidate_sha256','source_sha256','features','outcome','review_basis')}
            for r in records]


def _metrics(parameters,rows):
    x=np.asarray([_features(r['features']) for r in rows],dtype=np.float64)
    truth=np.asarray([r['outcome']=='accepted' for r in rows],dtype=np.float64)
    scores=_forward(parameters,x)[1];selected=scores>=.8
    return {'count':len(rows),'brier':float(np.mean((scores-truth)**2)),
            'accept_precision':float(np.mean(truth[selected])) if bool(np.any(selected)) else None,
            'high_confidence_count':int(np.count_nonzero(selected))}


def train(records,training_buildings,evaluation_buildings,parent=None,*,epochs=300,learning_rate=.02,
          batch_size=64,seed=0,min_training_records=100,min_evaluation_records=20,cancelled=None,progress=None):
    """Train a candidate MLP and measure it on isolated reviewed buildings.

    Cancellation raises CancelledError and returns no partial checkpoint. The
    caller persists candidates and activates only promotion-eligible models.
    Evaluation labels never enter gradient updates. No feedback is generated.
    """
    if cancelled is not None and not callable(cancelled):raise ValueError('Cancellation callback required')
    if progress is not None and not callable(progress):raise ValueError('Progress callback required')
    def check_cancelled():
        if cancelled is not None and cancelled():raise CancelledError('Neural training cancelled')
    check_cancelled();_seed(seed);records=_snapshot(records)
    parent=copy.deepcopy(parent) if parent is not None else baseline(seed);validate_model(parent)
    train_ids=_identifiers(training_buildings,'training buildings');eval_ids=_identifiers(evaluation_buildings,'evaluation buildings')
    if not train_ids or not eval_ids or train_ids & eval_ids:
        raise ValueError('Independent nonempty neural building splits required')
    prior_train=set(parent['training_buildings']);prior_eval=set(parent['evaluation_buildings'])
    if prior_train & eval_ids or prior_eval & train_ids:
        raise ValueError('Neural warm-start building split leakage')
    if {r['building_id'] for r in records}!=train_ids|eval_ids:
        raise ValueError('Every reviewed building must belong to the explicit neural split')
    training=sorted((r for r in records if r['building_id'] in train_ids),key=lambda r:r['id'])
    evaluation=sorted((r for r in records if r['building_id'] in eval_ids),key=lambda r:r['id'])
    training_sources={s for r in training for s in r['source_sha256']}|set(parent['training_sources'])
    evaluation_sources={s for r in evaluation for s in r['source_sha256']}|set(parent['evaluation_sources'])
    if training_sources & evaluation_sources:raise ValueError('Neural training/evaluation source leakage')
    _identifiers(sorted(training_sources),'training source history',True)
    _identifiers(sorted(evaluation_sources),'evaluation source history',True)
    if any({r['outcome'] for r in rows}!={'accepted','rejected'} for rows in (training,evaluation)):
        raise ValueError('Both reviewed classes required in each neural split')
    hidden=parent['architecture']['hidden_units']
    if (type(epochs) is not int or not 1<=epochs<=1000 or len(training)*epochs>MAX_ROW_EPOCHS
            or len(training)*epochs*hidden>MAX_WEIGHTED_ROW_EPOCHS):
        raise ValueError('Neural training work budget exceeded')
    if type(batch_size) is not int or not 1<=batch_size<=4096:raise ValueError('Bounded integer neural batch size required')
    if type(learning_rate) not in (int,float) or not math.isfinite(learning_rate) or not 1e-5<=learning_rate<=.5:
        raise ValueError('Bounded positive neural learning rate required')
    if any(type(n) is not int or not 1<=n<=MAX_RECORDS for n in (min_training_records,min_evaluation_records)):
        raise ValueError('Bounded positive neural promotion sample limits required')
    check_cancelled();parameters=_arrays(parent);initial_parameters=[p.copy() for p in parameters]
    first=[np.zeros_like(p) for p in parameters];second=[np.zeros_like(p) for p in parameters]
    x=np.asarray([_features(r['features']) for r in training],dtype=np.float64)
    y=np.asarray([r['outcome']=='accepted' for r in training],dtype=np.float64)
    rng=np.random.default_rng(seed);step=0
    for epoch in range(epochs):
        check_cancelled();order=rng.permutation(len(training))
        for start in range(0,len(training),batch_size):
            check_cancelled();indices=order[start:start+batch_size];xb=x[indices];yb=y[indices]
            w1,b1,w2,b2=parameters;hidden_values,prediction=_forward(parameters,xb)
            error=(prediction-yb)/len(indices)
            hidden_error=(error[:,None]*w2[None,:])*(1-hidden_values**2)
            gradients=[xb.T@hidden_error+1e-4*w1,np.sum(hidden_error,axis=0),
                       hidden_values.T@error+1e-4*w2,np.asarray(np.sum(error))]
            step+=1
            for i,g in enumerate(gradients):
                first[i]=.9*first[i]+.1*g;second[i]=.999*second[i]+.001*g*g
                parameters[i]-=learning_rate*(first[i]/(1-.9**step))/(np.sqrt(second[i]/(1-.999**step))+1e-8)
                np.clip(parameters[i],-100,100,out=parameters[i])
        if progress is not None:
            prediction=_forward(parameters,x)[1];eps=np.finfo(float).eps;clipped=np.clip(prediction,eps,1-eps)
            progress({'epoch':epoch+1,'epochs':epochs,'training_records':len(training),
                      'loss':float(-np.mean(y*np.log(clipped)+(1-y)*np.log(1-clipped)))})
    check_cancelled();previous=_metrics(initial_parameters,evaluation);current=_metrics(parameters,evaluation);reasons=[]
    if len(train_ids)<MIN_BUILDINGS_PER_SPLIT or len(eval_ids)<MIN_BUILDINGS_PER_SPLIT:reasons.append('insufficient_independent_buildings')
    if len(training)<min_training_records or len(evaluation)<min_evaluation_records:reasons.append('insufficient_reviewed_samples')
    if current['brier']>=previous['brier']-1e-6:reasons.append('no_held_out_brier_improvement')
    if current['high_confidence_count']<max(5,min_evaluation_records//4):reasons.append('insufficient_high_confidence_predictions')
    if current['accept_precision'] is None or current['accept_precision']<max(.95,previous['accept_precision'] or 0):reasons.append('held_out_accept_precision_below_policy')
    model=copy.deepcopy(parent);model.pop('artifact_sha256')
    model.update(parameters={'hidden_weights':parameters[0].tolist(),'hidden_bias':parameters[1].tolist(),
                              'output_weights':parameters[2].tolist(),'output_bias':float(parameters[3])},
        seed=seed,iteration=parent['iteration']+1,parent_sha256=parent['artifact_sha256'],
        dataset_sha256=digest(sorted(records,key=lambda r:r['id'])),
        training_buildings=sorted(train_ids|prior_train),training_sources=sorted(training_sources),
        evaluation_buildings=sorted(eval_ids|prior_eval),evaluation_sources=sorted(evaluation_sources),
        status='candidate_withheld' if reasons else 'promotion_eligible',production_eligible=not reasons,
        training={'epochs':epochs,'learning_rate':learning_rate,'batch_size':batch_size,'seed':seed,
                  'training_records':len(training),'evaluation_records':len(evaluation),
                  'optimizer':'Adam','numpy_version':np.__version__},
        evaluation={'previous':previous,'candidate':current,'reasons':reasons,
            'min_training_records':min_training_records,'min_evaluation_records':min_evaluation_records,
            'min_buildings_per_split':MIN_BUILDINGS_PER_SPLIT,'high_confidence_threshold':.8,
            'policy':'held-out Brier improves; accept precision >=95% and no regression; sufficient reviewed samples/buildings'})
    check_cancelled();_seal(model);validate_model(model);return model
