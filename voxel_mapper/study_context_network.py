"""Bounded source-only NumPy context decoder for proposed crop research.

The full 16 by 16 source grid reaches every mask logit through a learned dense
context bottleneck.  A local branch supplies edge detail; it cannot substitute
for the global decoder.  Target masks supervise training only.  The spatial
bias is initialized from the current fitting set's mean mask, never a held-out
mask.  This module has a separate checkpoint version from the older local CNN.
"""
from concurrent.futures import CancelledError
import copy
import math

import numpy as np

from .building_spec import digest

VERSION = 'study-context-network-v1'
MAX_ROWS = 2048
MAX_FIT_FORWARD_MACS = 4_000_000_000
MAX_ACTIVATION_BYTES = 64_000_000
MAX_PARAMETERS = 100_000
GRID = 16
LEARNING_RATE = .005
REGULARIZATION = .0001
# Declared before any held-out experiment; these are not selected on its scores.
DEFAULT_CONFIGURATION = {'input_size': 64, 'channels': 4, 'epochs': 40,
    'batch_size': 4, 'learning_rate': LEARNING_RATE, 'regularization': REGULARIZATION}
PARAMETER_KEYS = ('conv1_weights', 'conv1_bias', 'conv2_weights', 'conv2_bias',
    'context_weights', 'context_bias', 'class_weights', 'class_bias',
    'mask_weights', 'mask_bias', 'local_weights')
SCOPE = 'Class and filled mask for an already-proposed source crop; not full-page discovery or 3D reconstruction.'
ASSUMPTIONS = [
    'Source crops are already proposed and aligned to a common square grid.',
    'The training-fold mean mask initializes a spatial prior; held-out masks never initialize or condition inference.',
    'Only source pixels condition the learned decoder; semantic labels and masks supervise training.',
    'The 16 by 16 decoder limits boundary resolution and does not establish complete geometry or 3D placement.']


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study context training cancelled')


def _settings(size, channels, classes, epochs=1, batch_size=4):
    if (type(size) is not int or size not in (32, 64)
            or type(channels) is not int or not 1 <= channels <= 8
            or type(classes) is not int or not 1 <= classes <= 16
            or type(epochs) is not int or not 1 <= epochs <= 100
            or type(batch_size) is not int or not 1 <= batch_size <= 8):
        raise ValueError('Bounded 32/64 pixel context settings required')


def _shapes(channels, classes):
    latent = 8*channels
    return {'conv1_weights': (3, 3, 1, channels), 'conv1_bias': (channels,),
        'conv2_weights': (3, 3, channels, channels), 'conv2_bias': (channels,),
        'context_weights': (64*channels, latent), 'context_bias': (latent,),
        'class_weights': (latent, classes), 'class_bias': (classes,),
        'mask_weights': (latent, GRID*GRID), 'mask_bias': (GRID*GRID,),
        'local_weights': (channels,)}


def estimate_work(rows, *, input_size=64, channels=4, classes=11, epochs=40, batch_size=4):
    _settings(input_size, channels, classes, epochs, batch_size)
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError('One to 2048 bounded context examples required')
    latent = 8*channels
    per_row = input_size*input_size + GRID*GRID*9*channels + 64*9*channels*channels
    per_row += 64*channels*latent + latent*(classes+GRID*GRID) + GRID*GRID*channels
    parameters = sum(math.prod(shape) for shape in _shapes(channels, classes).values())
    # Includes normalization, convolution caches/gradients, logits and pooling
    # workspaces. No full-dataset hidden activation tensor is ever allocated.
    activation = min(rows, batch_size)*(input_size*input_size*4+GRID*GRID*(24*channels+32))*8
    return {'forward_macs': rows*epochs*per_row,
        'forward_backward_macs_estimate': 3*rows*epochs*per_row,
        'activation_bytes_upper_bound': activation,
        'training_input_bytes': rows*input_size*input_size*8*2,
        'parameter_count': parameters, 'batch_size': min(rows, batch_size), 'input_size': input_size}


def _images(value, name, *, unit_interval=True):
    if (not isinstance(value, np.ndarray) or value.ndim != 3
            or not 1 <= value.shape[0] <= MAX_ROWS
            or value.shape[1] not in (32, 64) or value.shape[2] != value.shape[1]
            or value.dtype.kind not in 'fiu'):
        raise ValueError('Bounded N by 32/64 by 32/64 '+name+' arrays required')
    if not np.isfinite(value).all():
        raise ValueError('Finite '+name+' values required')
    bound = 1. if unit_interval else 20.
    if np.any(value > bound) or np.any(value < (0. if unit_interval else -bound)):
        raise ValueError('Bounded '+name+' values required')
    return value.astype(np.float64, copy=False)


def _bounded_array(value, shape, name, *, low=-100., high=100.):
    # Bound each list dimension before NumPy conversion of checkpoint input.
    def bounded(item, dimensions):
        if isinstance(item, np.ndarray):
            return (item.shape == dimensions and item.dtype.kind in 'fiu'
                and bool(np.isfinite(item).all()) and bool((item >= low).all())
                and bool((item <= high).all()))
        if not dimensions:
            return type(item) in (int, float) and math.isfinite(item) and low <= item <= high
        return (isinstance(item, list) and len(item) == dimensions[0]
            and all(bounded(child, dimensions[1:]) for child in item))
    if not bounded(value, shape):
        raise ValueError('Finite bounded context array required: '+name)
    return np.asarray(value, dtype=np.float64)


def _prior(value):
    if value is None:
        return np.full((GRID, GRID), .5, dtype=np.float64)
    return _bounded_array(value, (GRID, GRID), 'mask prior', low=.05, high=.95)


def _prior_logits(value):
    prior = _prior(value)
    return np.log(prior/(1-prior)).reshape(GRID*GRID)


def initialize(input_size=32, channels=4, classes=2, seed=0, *, mask_prior=None):
    _settings(input_size, channels, classes)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('Bounded deterministic context seed required')
    rng = np.random.default_rng(seed)
    latent = 8*channels
    return {'conv1_weights': rng.normal(0., 1/3, (3, 3, 1, channels)),
        'conv1_bias': np.zeros(channels),
        'conv2_weights': rng.normal(0., 1/math.sqrt(9*channels), (3, 3, channels, channels)),
        'conv2_bias': np.zeros(channels),
        'context_weights': rng.normal(0., 1/math.sqrt(64*channels), (64*channels, latent)),
        'context_bias': np.zeros(latent),
        'class_weights': rng.normal(0., 1/math.sqrt(latent), (latent, classes)),
        'class_bias': np.zeros(classes),
        'mask_weights': rng.normal(0., .1/math.sqrt(latent), (latent, GRID*GRID)),
        'mask_bias': _prior_logits(mask_prior).copy(), 'local_weights': np.zeros(channels)}


def _parameters(value, channels=None, classes=None):
    if not isinstance(value, dict) or set(value) != set(PARAMETER_KEYS):
        raise ValueError('Exact context parameter inventory required')
    first, last = value['conv1_bias'], value['class_bias']
    if (not isinstance(first, (list, np.ndarray)) or not isinstance(last, (list, np.ndarray))
            or isinstance(first, np.ndarray) and first.ndim != 1
            or isinstance(last, np.ndarray) and last.ndim != 1
            or len(first) not in range(1, 9) or len(last) not in range(1, 17)):
        raise ValueError('Bounded context channel and class counts required')
    c, k = len(first), len(last)
    if channels is not None and channels != c or classes is not None and classes != k:
        raise ValueError('Context architecture/parameter mismatch')
    return {key: _bounded_array(value[key], shape, key) for key, shape in _shapes(c, k).items()}


def _area(x, grid=GRID):
    b, h, w = x.shape
    stride = h//grid
    return x.reshape(b, grid, stride, grid, stride).mean(axis=(2, 4))


def _conv(x, weights, bias):
    b, h, w, inputs = x.shape
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0)))
    out = np.zeros((b, h, w, weights.shape[-1]), dtype=np.float64)
    for row in range(3):
        for column in range(3):
            patch = padded[:, row:row+h, column:column+w, :].reshape(-1, inputs)
            out += (patch@weights[row, column]).reshape(out.shape)
    return out+bias


def _conv_backward(x, weights, delta, *, input_gradient=True):
    b, h, w, inputs = x.shape
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0)))
    dx = np.zeros_like(padded) if input_gradient else None
    dw = np.zeros_like(weights)
    flat_delta = delta.reshape(-1, weights.shape[-1])
    for row in range(3):
        for column in range(3):
            patch = padded[:, row:row+h, column:column+w, :].reshape(-1, inputs)
            dw[row, column] = patch.T@flat_delta
            if dx is not None:
                dx[:, row:row+h, column:column+w, :] += (flat_delta@weights[row, column].T).reshape(b, h, w, inputs)
    return dw, delta.sum(axis=(0, 1, 2)), None if dx is None else dx[:, 1:-1, 1:-1, :]


def _pool(x):
    b, h, w, c = x.shape
    return x.reshape(b, h//2, 2, w//2, 2, c).mean(axis=(2, 4))


def _softmax(logits):
    exp = np.exp(logits-logits.max(axis=1, keepdims=True))
    return exp/exp.sum(axis=1, keepdims=True)


def _forward(p, x):
    source = _area(x)[..., None]
    h1 = np.tanh(_conv(source, p['conv1_weights'], p['conv1_bias']))
    pooled = _pool(h1)
    h2 = np.tanh(_conv(pooled, p['conv2_weights'], p['conv2_bias']))
    flattened = h2.reshape(len(x), -1)
    context = np.tanh(flattened@p['context_weights']+p['context_bias'])
    class_logits = context@p['class_weights']+p['class_bias']
    logits = (context@p['mask_weights']+p['mask_bias']).reshape(len(x), GRID, GRID)
    logits += h1@p['local_weights']
    mask = 1/(1+np.exp(-np.clip(logits, -60., 60.)))
    return _softmax(class_logits), mask, (source, h1, pooled, h2, flattened, context, class_logits, logits)


def loss_and_gradients(parameters, x_normalized, masks, targets, *, class_weights=None,
        mask_weights=None, mask_prior=None, regularization=REGULARIZATION):
    """True joint gradients; caller fixes normalization, prior and balancing.

    ``mask_prior`` is the training-fold 16x16 probability grid, clipped to
    [.05,.95]. Finite-difference callers may omit it for a neutral .5 prior.
    Class CE and dense BCE are evaluated with stable, unclipped loss logits.
    """
    p = _parameters(parameters)
    x = _images(x_normalized, 'normalized source', unit_interval=False)
    mask = _images(masks, 'mask')
    if x.shape != mask.shape or len(x) > 8:
        raise ValueError('Matching bounded context image/mask minibatch required')
    if isinstance(targets, np.ndarray):
        target = targets
    elif (isinstance(targets, (list, tuple)) and len(targets) == len(x)
            and all(type(value) is int for value in targets)):
        target = np.asarray(targets)
    else:
        raise ValueError('One bounded class index per context image required')
    classes = len(p['class_bias'])
    if (target.shape != (len(x),) or target.dtype.kind not in 'iu'
            or np.any(target < 0) or np.any(target >= classes)):
        raise ValueError('One bounded class index per context image required')
    cw = np.ones(classes) if class_weights is None else _bounded_array(
        class_weights, (classes,), 'class balancing weights', low=0., high=MAX_ROWS)
    if (cw.shape != (classes,) or not np.isfinite(cw).all()
            or np.any(cw <= 0) or np.any(cw > MAX_ROWS)):
        raise ValueError('Positive bounded class balancing weights required')
    mw = {'positive': 1., 'negative': 1.} if mask_weights is None else mask_weights
    if (not isinstance(mw, dict) or set(mw) != {'positive', 'negative'}
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100 for v in mw.values())):
        raise ValueError('Bounded foreground/background mask balancing weights required')
    if type(regularization) not in (int, float) or not math.isfinite(regularization) or not 0 <= regularization <= .1:
        raise ValueError('Finite bounded context regularization required')
    prior_logits = _prior_logits(mask_prior)
    probabilities, predicted_mask, cache = _forward(p, x)
    source, h1, pooled, h2, flattened, context, class_logits, mask_logits = cache
    b = len(x)
    reduced_target = _area(mask)
    weights = cw[target]
    largest = class_logits.max(axis=1)
    log_normalizer = largest+np.log(np.exp(class_logits-largest[:, None]).sum(axis=1))
    class_loss = float(np.mean(weights*(log_normalizer-class_logits[np.arange(b), target])))
    positive, negative = mw['positive'], mw['negative']
    mask_loss = float(np.mean(positive*reduced_target*np.logaddexp(0., -mask_logits)
        +negative*(1-reduced_target)*np.logaddexp(0., mask_logits)))
    class_delta = probabilities.copy()
    class_delta[np.arange(b), target] -= 1
    class_delta *= weights[:, None]/b
    gradients = {'class_weights': context.T@class_delta, 'class_bias': class_delta.sum(axis=0)}
    mask_delta = ((positive*reduced_target+negative*(1-reduced_target))*predicted_mask
        -positive*reduced_target)/(b*GRID*GRID)
    flat_mask_delta = mask_delta.reshape(b, GRID*GRID)
    gradients['mask_weights'] = context.T@flat_mask_delta
    gradients['mask_bias'] = flat_mask_delta.sum(axis=0)
    gradients['local_weights'] = np.sum(h1*mask_delta[..., None], axis=(0, 1, 2))
    dcontext = (class_delta@p['class_weights'].T+flat_mask_delta@p['mask_weights'].T)*(1-context*context)
    gradients['context_weights'] = flattened.T@dcontext
    gradients['context_bias'] = dcontext.sum(axis=0)
    dh2 = (dcontext@p['context_weights'].T).reshape(h2.shape)*(1-h2*h2)
    dw2, db2, dpool = _conv_backward(pooled, p['conv2_weights'], dh2)
    gradients.update(conv2_weights=dw2, conv2_bias=db2)
    dh1 = np.repeat(np.repeat(dpool, 2, axis=1), 2, axis=2)/4
    dh1 += mask_delta[..., None]*p['local_weights']
    dh1 *= 1-h1*h1
    dw1, db1, _ = _conv_backward(source, p['conv1_weights'], dh1, input_gradient=False)
    gradients.update(conv1_weights=dw1, conv1_bias=db1)
    # Penalize decoder residuals, including movement away from the training
    # spatial prior, rather than forcing the prior itself toward a neutral mask.
    regularization_loss = 0.
    for key in PARAMETER_KEYS:
        residual = p[key]-prior_logits if key == 'mask_bias' else p[key]
        regularization_loss += .5*regularization*float(np.sum(residual*residual))
        gradients[key] += regularization*residual
    metrics = {'class_loss': class_loss, 'mask_loss': mask_loss,
        'regularization_loss': regularization_loss}
    return class_loss+mask_loss+regularization_loss, gradients, metrics


def _loss(p, x, masks, targets, class_weights, mask_weights, prior, batch_size, cancelled):
    values = {'class_loss': 0., 'mask_loss': 0., 'regularization_loss': 0.}
    for start in range(0, len(x), batch_size):
        _check(cancelled)
        end = min(len(x), start+batch_size)
        _, _, metrics = loss_and_gradients(p, x[start:end], masks[start:end], targets[start:end],
            class_weights=class_weights, mask_weights=mask_weights, mask_prior=prior)
        for key in values:
            values[key] += metrics[key]*(end-start)/len(x)
    return {**values, 'total_loss': sum(values.values())}


def _architecture(size, channels, classes):
    return {'input_size': size, 'input_channels': 1, 'channels': channels,
        'source_grid': GRID, 'source_downsampling': 'area_mean', 'conv_kernel_size': 3,
        'convolutions': 2, 'pool_stride': 2, 'context_grid': 8,
        'context_features': 64*channels, 'context_units': 8*channels,
        'mask_grid': GRID, 'mask_decoder': 'global_dense_plus_local_residual',
        'classes': classes, 'activation': 'tanh', 'mask_upsampling': 'nearest',
        'mask_activation': 'sigmoid'}


def _seal(value):
    value['id'] = digest({k: v for k, v in value.items() if k != 'id'})
    return value


def fit(x, masks, ylabels, *, epochs=40, channels=4, seed=0, batch_size=4,
        cancelled=lambda: False, progress=lambda value: None):
    images, targets_mask = _images(x, 'image'), _images(masks, 'mask')
    if images.shape != targets_mask.shape:
        raise ValueError('Matching source images and supervised target masks required')
    if (not isinstance(ylabels, list) or len(ylabels) != len(images)
            or any(not isinstance(v, str) or not v or len(v) > 80 for v in ylabels)):
        raise ValueError('One bounded semantic class per context image required')
    classes = sorted(set(ylabels))
    _settings(images.shape[1], channels, len(classes), epochs, batch_size)
    if type(seed) is not int or not 0 <= seed < 2**32 or not callable(cancelled) or not callable(progress):
        raise ValueError('Bounded context seed and callbacks required')
    work = estimate_work(len(images), input_size=images.shape[1], channels=channels,
        classes=len(classes), epochs=epochs, batch_size=batch_size)
    if (work['forward_macs'] > MAX_FIT_FORWARD_MACS
            or work['activation_bytes_upper_bound'] > MAX_ACTIVATION_BYTES
            or work['parameter_count'] > MAX_PARAMETERS):
        raise ValueError('Context training work, activation or parameter budget exceeded')
    _check(cancelled)
    mean, scale = float(images.mean()), max(.1, float(images.std()))
    norm_x = (images-mean)/scale
    # Every statistic below is fit from this call's training data only.
    prior = np.clip(_area(targets_mask).mean(axis=0), .05, .95)
    target = np.asarray([classes.index(value) for value in ylabels], dtype=np.int64)
    counts = np.bincount(target, minlength=len(classes))
    class_weights = len(images)/(len(classes)*counts.astype(np.float64))
    foreground = float(targets_mask.mean())
    mask_weights = {'positive': .5/max(foreground, .01), 'negative': .5/max(1-foreground, .01)}
    parameters = initialize(images.shape[1], channels, len(classes), seed, mask_prior=prior)
    initial_parameters = {key: value.copy() for key, value in parameters.items()}
    initial_pin = digest({key: value.tolist() for key, value in parameters.items()})
    initial = _loss(parameters, norm_x, targets_mask, target, class_weights, mask_weights, prior, batch_size, cancelled)
    first = {key: np.zeros_like(value) for key, value in parameters.items()}
    second = {key: np.zeros_like(value) for key, value in parameters.items()}
    rng = np.random.default_rng(seed)
    step = 0
    for epoch in range(epochs):
        _check(cancelled)
        order = rng.permutation(len(images))
        running = 0.
        for begin in range(0, len(images), batch_size):
            _check(cancelled)
            batch = order[begin:begin+batch_size]
            loss, gradients, _ = loss_and_gradients(parameters, norm_x[batch], targets_mask[batch], target[batch],
                class_weights=class_weights, mask_weights=mask_weights, mask_prior=prior)
            running += loss*len(batch)/len(images)
            step += 1
            for key in PARAMETER_KEYS:
                gradient = gradients[key]
                first[key] = .9*first[key]+.1*gradient
                second[key] = .999*second[key]+.001*gradient*gradient
                parameters[key] -= LEARNING_RATE*(first[key]/(1-.9**step))/(np.sqrt(second[key]/(1-.999**step))+1e-8)
                np.clip(parameters[key], -100., 100., out=parameters[key])
        progress({'epoch': epoch+1, 'epochs': epochs, 'loss': running})
    _check(cancelled)
    final = _loss(parameters, norm_x, targets_mask, target, class_weights, mask_weights, prior, batch_size, cancelled)
    training = {'records': len(images), 'epochs': epochs, 'channels': channels,
        'seed': seed, 'batch_size': batch_size, 'class_balanced': True,
        'mask_balancing_weights': mask_weights, 'optimizer': 'Adam', 'learning_rate': LEARNING_RATE,
        'regularization': REGULARIZATION, 'mask_prior': 'training_fold_mean_only',
        'initial_parameters_sha256': initial_pin,
        'conv_filters_updated': any(np.any(parameters[key] != initial_parameters[key]) for key in ('conv1_weights', 'conv2_weights')),
        'context_decoder_updated': any(np.any(parameters[key] != initial_parameters[key]) for key in ('context_weights', 'mask_weights'))}
    for key in ('total_loss', 'class_loss', 'mask_loss', 'regularization_loss'):
        suffix = 'loss' if key == 'total_loss' else key
        training['initial_'+suffix] = initial[key]
        training['final_'+suffix] = final[key]
    result = {'version': VERSION, 'architecture': _architecture(images.shape[1], channels, len(classes)),
        'classes': classes, 'normalization': {'mean': mean, 'scale': scale},
        'parameters': {key: value.tolist() for key, value in parameters.items()},
        'mask_prior': prior.tolist(), 'training': training, 'work_estimate': work,
        'production_eligible': False, 'prediction_scope': SCOPE, 'assumptions': ASSUMPTIONS.copy()}
    _seal(result)
    validate(result)
    return result


def _strict_json(value):
    """Bound JSON traversal before hashing arbitrary checkpoint metadata."""
    stack = [(value, 0)]
    seen = 0
    while stack:
        item, depth = stack.pop()
        seen += 1
        if seen > 120_000 or depth > 12:
            raise ValueError('Bounded context JSON checkpoint required')
        if type(item) is dict:
            if len(item) > 64 or any(type(key) is not str or len(key) > 100 for key in item):
                raise ValueError('Bounded context JSON keys required')
            stack.extend((child, depth+1) for child in item.values())
        elif type(item) is list:
            if len(item) > 1024:
                raise ValueError('Bounded context JSON arrays required')
            stack.extend((child, depth+1) for child in item)
        elif type(item) is str:
            if len(item) > 512:
                raise ValueError('Bounded context JSON strings required')
        elif type(item) in (int, float):
            if not math.isfinite(item) or abs(item) > 10**15:
                raise ValueError('Finite bounded context JSON numbers required')
        elif type(item) is not bool and item is not None:
            raise ValueError('Open JSON context checkpoint required')


def validate(network):
    _strict_json(network)
    expected_keys = {'version', 'id', 'architecture', 'classes', 'normalization', 'parameters',
        'mask_prior', 'training', 'work_estimate', 'production_eligible', 'prediction_scope', 'assumptions'}
    if (not isinstance(network, dict) or set(network) != expected_keys
            or network.get('version') != VERSION or network.get('production_eligible') is not False
            or network.get('prediction_scope') != SCOPE or network.get('assumptions') != ASSUMPTIONS):
        raise ValueError('Exact research context network required')
    architecture, classes = network['architecture'], network['classes']
    if (not isinstance(architecture, dict) or not isinstance(classes, list)
            or not 1 <= len(classes) <= 16
            or any(type(value) is not str or not value or len(value) > 80 for value in classes)
            or classes != sorted(set(classes))):
        raise ValueError('Bounded context architecture and classes required')
    _settings(architecture.get('input_size'), architecture.get('channels'), len(classes))
    channels, size = architecture['channels'], architecture['input_size']
    expected_architecture = _architecture(size, channels, len(classes))
    if (architecture != expected_architecture
            or any(type(architecture[key]) is not type(value) for key, value in expected_architecture.items())):
        raise ValueError('Exact bounded context architecture required')
    norm = network['normalization']
    if (not isinstance(norm, dict) or set(norm) != {'mean', 'scale'}
            or type(norm['mean']) not in (int, float) or not 0 <= norm['mean'] <= 1
            or type(norm['scale']) not in (int, float) or not .1 <= norm['scale'] <= 1):
        raise ValueError('Finite bounded training-fold context normalization required')
    _parameters(network['parameters'], channels, len(classes))
    _prior(network['mask_prior'])
    training = network['training']
    training_keys = {'records', 'epochs', 'channels', 'seed', 'batch_size', 'class_balanced',
        'mask_balancing_weights', 'optimizer', 'learning_rate', 'regularization', 'mask_prior',
        'initial_parameters_sha256', 'conv_filters_updated', 'context_decoder_updated',
        'initial_loss', 'final_loss', 'initial_class_loss', 'final_class_loss',
        'initial_mask_loss', 'final_mask_loss', 'initial_regularization_loss', 'final_regularization_loss'}
    if not isinstance(training, dict) or set(training) != training_keys:
        raise ValueError('Exact bounded context training record required')
    _settings(size, channels, len(classes), training['epochs'], training['batch_size'])
    if (type(training['records']) is not int or not 1 <= training['records'] <= MAX_ROWS
            or type(training['channels']) is not int or training['channels'] != channels
            or type(training['seed']) is not int
            or not 0 <= training['seed'] < 2**32 or training['class_balanced'] is not True
            or training['optimizer'] != 'Adam' or training['learning_rate'] != LEARNING_RATE
            or training['regularization'] != REGULARIZATION or training['mask_prior'] != 'training_fold_mean_only'
            or type(training['conv_filters_updated']) is not bool or type(training['context_decoder_updated']) is not bool):
        raise ValueError('Bounded context training settings required')
    pin = training['initial_parameters_sha256']
    if type(pin) is not str or len(pin) != 64 or any(character not in '0123456789abcdef' for character in pin):
        raise ValueError('Pinned context initialization required')
    for key in training_keys:
        if key.startswith(('initial_', 'final_')) and key != 'initial_parameters_sha256':
            if type(training[key]) not in (int, float) or not 0 <= training[key] <= 1_000_000:
                raise ValueError('Finite bounded context loss required')
    weights = training['mask_balancing_weights']
    if (not isinstance(weights, dict) or set(weights) != {'positive', 'negative'}
            or any(type(value) not in (int, float) or not 0 < value <= 100 for value in weights.values())):
        raise ValueError('Bounded context mask balancing record required')
    work = estimate_work(training['records'], input_size=size, channels=channels, classes=len(classes),
        epochs=training['epochs'], batch_size=training['batch_size'])
    if (network['work_estimate'] != work
            or any(type(network['work_estimate'][key]) is not int for key in work)
            or work['forward_macs'] > MAX_FIT_FORWARD_MACS
            or work['activation_bytes_upper_bound'] > MAX_ACTIVATION_BYTES or work['parameter_count'] > MAX_PARAMETERS):
        raise ValueError('Bounded context checkpoint work estimate required')
    if network['id'] != digest({key: value for key, value in network.items() if key != 'id'}):
        raise ValueError('Context checkpoint self-hash mismatch')
    return network


def infer(network, x):
    validate(network)
    images = _images(x, 'image')
    if images.shape[1] != network['architecture']['input_size']:
        raise ValueError('Inference crop size differs from trained context network')
    parameters = _parameters(network['parameters'])
    norm = network['normalization']
    classes, masks = [], []
    stride = images.shape[1]//GRID
    for start in range(0, len(images), 8):
        batch = (images[start:start+8]-norm['mean'])/norm['scale']
        probabilities, mask, _ = _forward(parameters, batch)
        classes.append(probabilities)
        masks.append(np.repeat(np.repeat(mask, stride, axis=1), stride, axis=2))
    return np.concatenate(classes), np.concatenate(masks)


def encode(network):
    validate(network)
    return copy.deepcopy(network)


def decode(value):
    validate(value)
    return copy.deepcopy(value)
