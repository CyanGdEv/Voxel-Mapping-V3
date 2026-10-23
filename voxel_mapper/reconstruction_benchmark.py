"""Bounded geometric comparison against pinned, externally reviewed references.

This measures supplied geometry. It does not discover evidence, authenticate
reviews, create learning labels, promote a model or accept physical placement.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from shapely import hausdorff_distance
from shapely.geometry import Polygon

from .building_spec import digest
from .generation_cycles import atomic_json

VERSION = 'reconstruction-benchmark-v1'
MAX_CASES = 128
MAX_VERTICES = 100000
MAX_JSON_BYTES = 16000000
LINEAGE_KEYS = ('training_buildings', 'evaluation_buildings',
                'training_sources', 'evaluation_sources')
GEOMETRY_KEYS = {'footprint_m', 'height_m', 'position_m', 'openings_m'}
DEFAULT_THRESHOLDS = {
    'footprint_iou_min': .95,
    'boundary_hausdorff_m_max': .25,
    'height_error_m_max': .25,
    'position_error_m_max': .5,
    'opening_iou_min': .5,
    'opening_precision_min': .95,
    'opening_recall_min': .95,
}


def _text(value, name, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value)>maximum:
        raise ValueError('Bounded nonempty '+name+' required')
    return value


def _number(value, name, low=-100000000., high=100000000.):
    if type(value) not in (int, float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('Finite bounded '+name+' required')
    return float(value)


def _hashes(values, name='source hashes', allow_empty=False):
    if (not isinstance(values, list) or len(values)>10000 or
            (not allow_empty and not values) or
            any(not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v) for v in values) or
            len(set(values))!=len(values)):
        raise ValueError('Unique bounded SHA256 '+name+' required')
    return set(values)


def _ring(value, budget):
    if not isinstance(value, list) or not 3<=len(value)<=1024:
        raise ValueError('A bounded polygon ring is required')
    budget[0]+=len(value)
    if budget[0]>MAX_VERTICES:raise ValueError('Benchmark vertex budget exceeded')
    points=[]
    for point in value:
        if not isinstance(point, list) or len(point)!=2:
            raise ValueError('Two-dimensional metre polygon coordinates required')
        points.append(tuple(_number(v, 'polygon coordinate') for v in point))
    if len(set(points))<3:raise ValueError('Polygon requires three distinct points')
    return points


def _polygon(value, budget):
    if isinstance(value, dict):
        if set(value)-{'exterior', 'holes'} or 'exterior' not in value:
            raise ValueError('Polygon exterior and optional holes required')
        holes=value.get('holes', [])
        if not isinstance(holes, list) or len(holes)>32:
            raise ValueError('Polygon hole budget exceeded')
        polygon=Polygon(_ring(value['exterior'], budget), [_ring(h, budget) for h in holes])
    else:
        polygon=Polygon(_ring(value, budget))
    if polygon.is_empty or not polygon.is_valid or not 1e-9<polygon.area<=1000000000:
        raise ValueError('Valid nonempty polygon topology and bounded area required')
    if max(polygon.bounds[2]-polygon.bounds[0], polygon.bounds[3]-polygon.bounds[1])>10000:
        raise ValueError('Local polygon span exceeds the benchmark budget')
    return polygon


def _geometry(value, budget, *, reference=False):
    if not isinstance(value, dict) or set(value)-GEOMETRY_KEYS:
        raise ValueError('Supported geometry fields required')
    required={'footprint_m', 'height_m', 'position_m'}
    if reference and not required<=set(value):
        raise ValueError('Complete reference footprint, height and position required')
    result={}
    if 'footprint_m' in value:result['footprint']=_polygon(value['footprint_m'], budget)
    if 'height_m' in value:result['height']=_number(value['height_m'], 'height', 0, 500)
    if 'position_m' in value:
        position=value['position_m']
        if not isinstance(position, list) or len(position)!=3:
            raise ValueError('XYZ metre position required')
        result['position']=tuple(_number(v, 'position coordinate') for v in position)
    if 'openings_m' in value:
        openings=value['openings_m']
        if not isinstance(openings, list) or len(openings)>32:
            raise ValueError('At most 32 opening polygons per case required')
        result['openings']=[_polygon(p, budget) for p in openings]
        for i, shape in enumerate(result['openings']):
            if any(shape.intersection(other).area>1e-9 for other in result['openings'][:i]):
                raise ValueError('Overlapping opening polygons are ambiguous')
    return result


def reference_digest(config):
    """Pin reference identities, evidence and metric frame, excluding predictions.

    This checksum detects edits after a reference contract is frozen. It does
    not prove that its reviewer or reference geometry is independent or correct.
    """
    if not isinstance(config, dict) or not isinstance(config.get('cases'), list):
        raise ValueError('Versioned benchmark cases required')
    try:
        contract={key:config[key] for key in ('version', 'dataset_kind', 'coordinate_frame', 'units')}
        contract['cases']=[{key:case[key] for key in
                           ('id', 'building_id', 'source_sha256', 'reference')} for case in config['cases']]
        return digest(contract)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('Complete JSON reference contract required') from error


def _lineage(value):
    if not isinstance(value, dict) or set(value)!=set(LINEAGE_KEYS):
        raise ValueError('Complete explicit training/evaluation source and building lineage required')
    result={}
    for key in LINEAGE_KEYS:
        values=value[key]
        if key.endswith('sources'):
            result[key]=_hashes(values, key, allow_empty=True)
        else:
            if (not isinstance(values, list) or len(values)>10000 or
                    any(not isinstance(v,str) or not v.strip() or len(v)>512 for v in values) or
                    len(set(values))!=len(values)):
                raise ValueError('Unique bounded lineage building identifiers required')
            result[key]=set(values)
    if (result['training_buildings'] & result['evaluation_buildings'] or
            result['training_sources'] & result['evaluation_sources']):
        raise ValueError('Training/evaluation lineage leakage')
    return result


def _check_lineage(config, model, buildings, sources):
    explicit=_lineage(config['lineage']) if 'lineage' in config else None
    combined={key:set() for key in LINEAGE_KEYS}
    model_hash=None
    if model is not None:
        if not isinstance(model, dict):raise ValueError('Recognized ranker model checkpoint required')
        from . import building_learning, neural_learning
        if model.get('version')==neural_learning.VERSION:
            neural_learning.validate_model(model)
        elif model.get('version')==building_learning.VERSION:
            building_learning.validate_model(model)
        else:raise ValueError('Recognized ranker model checkpoint required')
        if type(model.get('iteration')) is not int or model['iteration']<0:
            raise ValueError('Nonnegative model iteration metadata required')
        # Historical logistic checkpoints did not retain evaluation source
        # sets. Do not silently certify unseen sources from incomplete lineage.
        if model.get('iteration', 0)>0 and any(key not in model for key in LINEAGE_KEYS) and explicit is None:
            raise ValueError('Checkpoint lacks complete evaluation source lineage; supply explicit lineage')
        declared={key:model.get(key, []) for key in LINEAGE_KEYS}
        combined=_lineage(declared)
        model_hash=model['artifact_sha256']
    if explicit:
        for key in LINEAGE_KEYS:combined[key]|=explicit[key]
    if (combined['training_buildings'] & combined['evaluation_buildings'] or
            combined['training_sources'] & combined['evaluation_sources']):
        raise ValueError('Merged training/evaluation lineage leakage')
    overlap_buildings=buildings & (combined['training_buildings']|combined['evaluation_buildings'])
    overlap_sources=sources & (combined['training_sources']|combined['evaluation_sources'])
    if overlap_buildings or overlap_sources:
        raise ValueError('Benchmark leakage: reference buildings or sources overlap training/evaluation lineage')
    assessed=model is not None or explicit is not None
    return {'status':'no_declared_overlap' if assessed else 'not_assessed',
            'lineage_provenance':'checkpoint and/or supplied declarations; prior unseen exposure is not authenticated',
            'model_sha256':model_hash,
            'counts':{key:len(value) for key, value in combined.items()},
            'untouched_independence_proven':False}


def _thresholds(value):
    if not isinstance(value, dict) or set(value)-set(DEFAULT_THRESHOLDS):
        raise ValueError('Supported benchmark thresholds required')
    result={**DEFAULT_THRESHOLDS, **value}
    for key, number in result.items():
        _number(number, key, 0, 1 if key.endswith('_min') else 100)
    if result['opening_iou_min']<=0:raise ValueError('Positive opening matching IoU required')
    return result


def _iou(a, b):
    return float(a.intersection(b).area/a.union(b).area)


def _openings(reference, prediction, minimum):
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    overlaps=np.array([[_iou(a,b) for b in prediction] for a in reference], dtype=float)
    matched=[]
    if reference and prediction:
        # Maximize eligible match count first, then total IoU. A single high
        # overlap may not displace two qualifying one-to-one matches.
        reward=(overlaps>=minimum).astype(float)+overlaps/(max(len(reference),len(prediction))+1)
        rows, columns=linear_sum_assignment(-reward)
        matched=[{'reference_index':int(i), 'prediction_index':int(j), 'iou':float(overlaps[i,j])}
                 for i,j in zip(rows,columns) if overlaps[i,j]>=minimum]
    count=len(matched)
    return {'reference_count':len(reference), 'prediction_count':len(prediction),
            'matched_count':count, 'false_positive_count':len(prediction)-count,
            'false_negative_count':len(reference)-count,
            'precision':count/len(prediction) if prediction else 1.,
            'recall':count/len(reference) if reference else 1.,
            'matches':matched}


def _compare(case, reference, prediction, thresholds):
    metrics={'footprint_iou':None, 'boundary_hausdorff_m':None,
             'height_error_m':None, 'position_error_m':None, 'openings':None}
    missing=[]
    if prediction is None:
        missing=['prediction']
    else:
        if 'footprint' in prediction:
            metrics['footprint_iou']=_iou(reference['footprint'], prediction['footprint'])
            metrics['boundary_hausdorff_m']=float(hausdorff_distance(
                reference['footprint'].boundary,prediction['footprint'].boundary,densify=.25))
        else:missing.append('footprint_m')
        if 'height' in prediction:metrics['height_error_m']=abs(reference['height']-prediction['height'])
        else:missing.append('height_m')
        if 'position' in prediction:metrics['position_error_m']=math.dist(reference['position'],prediction['position'])
        else:missing.append('position_m')
        if 'openings' in reference:
            if 'openings' in prediction:
                metrics['openings']=_openings(reference['openings'],prediction['openings'],thresholds['opening_iou_min'])
            else:missing.append('openings_m')
    failures=list(missing)
    checks=(('footprint_iou', 'footprint_iou_min', lambda v,t:v>=t),
            ('boundary_hausdorff_m','boundary_hausdorff_m_max',lambda v,t:v<=t),
            ('height_error_m','height_error_m_max',lambda v,t:v<=t),
            ('position_error_m','position_error_m_max',lambda v,t:v<=t))
    for metric, threshold, comparison in checks:
        if metrics[metric] is not None and not comparison(metrics[metric],thresholds[threshold]):failures.append(metric)
    if metrics['openings']:
        for name in ('precision', 'recall'):
            if metrics['openings'][name]<thresholds['opening_'+name+'_min']:failures.append('opening_'+name)
    status='missing_prediction' if prediction is None else 'incomplete_prediction' if missing else 'measured'
    return {'id':case['id'], 'building_id':case['building_id'], 'status':status,
            'metrics':metrics, 'within_thresholds':not failures, 'failed_checks':failures,
            'opening_reference_supplied':'openings' in reference}


def evaluate(config, model=None):
    """Evaluate bounded JSON geometry without writing results or training data."""
    if not isinstance(config,dict) or config.get('version')!=VERSION:
        raise ValueError('Versioned reconstruction benchmark required')
    config=copy.deepcopy(config)
    if config.get('dataset_kind') not in ('synthetic','reviewed_real'):
        raise ValueError('Explicit synthetic or reviewed_real dataset kind required')
    _text(config.get('coordinate_frame'), 'metric coordinate frame')
    if config.get('units')!='metres':raise ValueError('Explicit metre units required; no coordinate conversion is implicit')
    cases=config.get('cases')
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError('One to 128 benchmark cases required')
    thresholds=_thresholds(config.get('thresholds',{}))
    if config.get('reference_sha256')!=reference_digest(config):
        raise ValueError('Frozen benchmark reference checksum changed or missing')
    ids=set();buildings=set();sources=set();prepared=[];budget=[0]
    for case in cases:
        if not isinstance(case,dict):raise ValueError('Benchmark case object required')
        identifier=_text(case.get('id'), 'case identity')
        if identifier in ids:raise ValueError('Unique benchmark case identities required')
        ids.add(identifier);buildings.add(_text(case.get('building_id'),'building identity'))
        sources|=_hashes(case.get('source_sha256'))
        ref=case.get('reference')
        if not isinstance(ref,dict):raise ValueError('Externally reviewed reference required')
        _text(ref.get('review_reference'),'external reference review',4000)
        if ref.get('review_basis') not in ('independent_review','source_verified'):
            raise ValueError('Independent review/source verification basis required')
        reference=_geometry(ref.get('geometry'),budget,reference=True)
        prediction=case.get('prediction')
        if prediction is not None:prediction=_geometry(prediction,budget)
        prepared.append((case,reference,prediction))
    lineage=_check_lineage(config,model,buildings,sources)
    results=[_compare(case,reference,prediction,thresholds) for case,reference,prediction in prepared]
    metrics={}
    for key in ('footprint_iou','boundary_hausdorff_m','height_error_m','position_error_m'):
        measured=[case['metrics'][key] for case in results if case['metrics'][key] is not None]
        metrics[key]={'measured_cases':len(measured), 'unassessed_cases':len(cases)-len(measured),
                      'mean':sum(measured)/len(measured) if measured else None,
                      'minimum':min(measured) if measured else None,
                      'maximum':max(measured) if measured else None}
    return {'version':VERSION, 'status':'benchmark_completed',
            'dataset_kind':config['dataset_kind'], 'coordinate_frame':config['coordinate_frame'], 'units':'metres',
            'config_sha256':digest(config), 'reference_sha256':config['reference_sha256'],
            'reference_provenance':'declared external review/source verification; not authenticated physical ground truth',
            'real_world_accuracy_established':False,
            'lineage_check':lineage, 'thresholds':thresholds, 'cases':results,
            'summary':{'case_count':len(cases), 'building_count':len(buildings), 'source_count':len(sources),
                       'cases_within_thresholds':sum(row['within_thresholds'] for row in results),
                       'missing_predictions':sum(row['status']=='missing_prediction' for row in results),
                       'incomplete_predictions':sum(row['status']=='incomplete_prediction' for row in results),
                       'all_cases_within_thresholds':all(row['within_thresholds'] for row in results),
                       'metrics':metrics},
            'metric_definitions':{'footprint_iou':'planar local polygon intersection over union, including holes',
                'boundary_hausdorff_m':'GEOS discrete boundary Hausdorff distance with quarter-edge densification',
                'position_error_m':'Euclidean XYZ distance in the declared metric frame',
                'opening_matching':'maximum qualifying one-to-one polygon IoU matches, then total overlap'},
            'training_labels_generated':0, 'model_promoted':False,
            'physical_acceptance_authorized':False, 'park_world_blocks_added':0}


def run(config, output, model=None):
    """Write one immutable benchmark run; never overwrite an earlier result."""
    root=Path(output)
    if root.exists():raise ValueError('Fresh benchmark output directory required')
    snapshot=copy.deepcopy(config)
    report=evaluate(snapshot,model)
    root.mkdir(parents=True)
    atomic_json(root/'config.json',snapshot)
    atomic_json(root/'report.json',report)
    return report


def _read(path):
    path=Path(path)
    if path.stat().st_size>MAX_JSON_BYTES:raise ValueError('Benchmark JSON byte budget exceeded')
    raw=path.read_bytes()
    def invalid(value):raise ValueError('Nonfinite JSON constant: '+value)
    value=json.loads(raw,parse_constant=invalid)
    if not isinstance(value,dict):raise ValueError('Benchmark JSON object required')
    if hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(raw).digest():
        raise ValueError('Benchmark input changed while reading')
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--model',help='Optional recognized neural/logistic JSON checkpoint; no training occurs')
    args=parser.parse_args(argv)
    report=run(_read(args.config),args.output,_read(args.model) if args.model else None)
    print(json.dumps({'status':report['status'],'dataset_kind':report['dataset_kind'],
                      'summary':report['summary'],'training_labels_generated':0}))
    return 0


if __name__=='__main__':raise SystemExit(main())
