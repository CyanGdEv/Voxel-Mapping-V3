"""Bounded NumPy convolutions for source-crop class and mask research tasks."""
from concurrent.futures import CancelledError
import copy
import math

import numpy as np

from .building_spec import digest

VERSION = 'study-vision-network-v1'
MAX_ROWS = 2048
MAX_FIT_FORWARD_MACS = 4_000_000_000
MAX_ACTIVATION_BYTES = 64_000_000
PARAMETER_KEYS = ('conv1_weights', 'conv1_bias', 'conv2_weights', 'conv2_bias',
                  'class_weights', 'class_bias', 'mask_weights', 'mask_bias')


def _check(cancelled):
    if cancelled():
        raise CancelledError('Study convolution training cancelled')


def _settings(size, channels, classes, epochs=1, batch_size=4):
    if (type(size) is not int or size not in (32, 64)
            or type(channels) is not int or not 1 <= channels <= 8
            or type(classes) is not int or not 1 <= classes <= 16
            or type(epochs) is not int or not 1 <= epochs <= 100
            or type(batch_size) is not int or not 1 <= batch_size <= 8):
        raise ValueError('Bounded 32/64 pixel convolution settings required')


def estimate_work(rows, *, input_size=64, channels=4, classes=11, epochs=30, batch_size=4):
    _settings(input_size, channels, classes, epochs, batch_size)
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError('One to 2048 bounded convolution examples required')
    # Two 3x3 convolutions, full then half resolution, followed by spatial
    # classification and a half-resolution dense mask head. Backpropagation is
    # conservatively estimated at three times the forward multiply-add count.
    h = input_size
    per_row = h*h*9*channels + (h//2)**2*9*channels*channels
    per_row += 16*channels*classes + (h//2)**2*channels
    activations = min(rows, batch_size)*h*h*(10*channels+12)*8
    return {'forward_macs': rows*epochs*per_row,
        'forward_backward_macs_estimate': 3*rows*epochs*per_row,
        'activation_bytes_upper_bound': activations,
        'training_input_bytes': rows*h*h*8*2,
        'batch_size': min(rows, batch_size), 'input_size': h}


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


def initialize(input_size=32, channels=4, classes=2, seed=0):
    _settings(input_size, channels, classes)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('Bounded deterministic convolution seed required')
    rng = np.random.default_rng(seed)
    return {'conv1_weights': rng.normal(0., 1/3, (3, 3, 1, channels)),
        'conv1_bias': np.zeros(channels),
        'conv2_weights': rng.normal(0., 1/math.sqrt(9*channels), (3, 3, channels, channels)),
        'conv2_bias': np.zeros(channels),
        'class_weights': rng.normal(0., 1/math.sqrt(16*channels), (16*channels, classes)),
        'class_bias': np.zeros(classes), 'mask_weights': rng.normal(0., 1/math.sqrt(channels), channels),
        'mask_bias': np.asarray(0., dtype=np.float64)}


def _parameters(value, channels=None, classes=None):
    if not isinstance(value, dict) or set(value) != set(PARAMETER_KEYS):
        raise ValueError('Exact convolution parameter inventory required')
    first, last = value['conv1_bias'], value['class_bias']
    if not isinstance(first, (list, np.ndarray)) or not isinstance(last, (list, np.ndarray)):
        raise ValueError('Bounded convolution bias arrays required')
    if ((isinstance(first, np.ndarray) and first.ndim != 1)
            or (isinstance(last, np.ndarray) and last.ndim != 1)
            or len(first) not in range(1, 9) or len(last) not in range(1, 17)):
        raise ValueError('Bounded convolution channel and class counts required')
    c, k = len(first), len(last)
    if channels is not None and c != channels or classes is not None and k != classes:
        raise ValueError('Convolution architecture/parameter mismatch')
    shapes = {'conv1_weights': (3, 3, 1, c), 'conv1_bias': (c,),
        'conv2_weights': (3, 3, c, c), 'conv2_bias': (c,),
        'class_weights': (16*c, k), 'class_bias': (k,), 'mask_weights': (c,), 'mask_bias': ()}
    # Check every list dimension before NumPy allocation, not after converting
    # an attacker-supplied huge nested array.
    def bounded(item, shape):
        if not shape:
            if isinstance(item, np.ndarray):
                return item.shape == () and item.dtype.kind in 'fiu' and math.isfinite(float(item)) and abs(float(item)) <= 100
            return type(item) in (int, float, np.float64, np.float32) and math.isfinite(float(item)) and abs(float(item)) <= 100
        if isinstance(item, np.ndarray):
            return (item.shape == shape and item.dtype.kind in 'fiu' and bool(np.isfinite(item).all())
                and bool((item >= -100).all()) and bool((item <= 100).all()))
        return isinstance(item, list) and len(item) == shape[0] and all(bounded(child, shape[1:]) for child in item)
    for name, shape in shapes.items():
        if not bounded(value[name], shape):
            raise ValueError('Finite bounded convolution parameter shape required: '+name)
    return {name: np.asarray(value[name], dtype=np.float64) for name in PARAMETER_KEYS}


def _conv(x, weights, bias):
    b, h, w, inputs = x.shape
    outputs = weights.shape[-1]
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0)))
    out = np.zeros((b, h, w, outputs), dtype=np.float64)
    # Nine bounded patch views, never an N*H*W*9*C im2col tensor.
    for row in range(3):
        for column in range(3):
            patch = padded[:, row:row+h, column:column+w, :].reshape(-1, inputs)
            out += (patch@weights[row, column]).reshape(b, h, w, outputs)
    return out+bias


def _conv_backward(x, weights, delta, *, input_gradient=True):
    b, h, w, inputs = x.shape
    outputs = weights.shape[-1]
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0)))
    dx = np.zeros_like(padded) if input_gradient else None
    dw = np.zeros_like(weights)
    flat_delta = delta.reshape(-1, outputs)
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


def _softmax(value):
    exp = np.exp(value-value.max(axis=1, keepdims=True))
    return exp/exp.sum(axis=1, keepdims=True)


def _forward(p, x):
    h1 = np.tanh(_conv(x[..., None], p['conv1_weights'], p['conv1_bias']))
    pooled = _pool(h1)
    h2 = np.tanh(_conv(pooled, p['conv2_weights'], p['conv2_bias']))
    b, h, w, c = h2.shape
    cell = h//4
    spatial = h2.reshape(b, 4, cell, 4, cell, c).mean(axis=(2, 4))
    features = spatial.reshape(b, 16*c)
    probabilities = _softmax(features@p['class_weights']+p['class_bias'])
    logits = h2@p['mask_weights']+p['mask_bias']
    mask = 1/(1+np.exp(-np.clip(logits, -60, 60)))
    return probabilities, mask, (h1, pooled, h2, features, logits)


def loss_and_gradients(parameters, x_normalized, masks, targets, *, class_weights=None, mask_weights=None):
    """Joint balanced class CE + dense mask BCE, with genuine conv gradients.

    For finite-difference checks, normalization and balancing weights are fixed
    caller inputs. x_normalized is source-image data only, never a target mask.
    """
    p = _parameters(parameters)
    x = _images(x_normalized, 'normalized image', unit_interval=False)
    mask = _images(masks, 'mask')
    if x.shape != mask.shape or x.shape[0] > 8:
        raise ValueError('Matching bounded convolution image/mask minibatch required')
    target = np.asarray(targets)
    classes = len(p['class_bias'])
    if target.shape != (len(x),) or target.dtype.kind not in 'iu' or np.any(target < 0) or np.any(target >= classes):
        raise ValueError('One bounded class index per convolution image required')
    cw = np.ones(classes) if class_weights is None else np.asarray(class_weights, dtype=np.float64)
    if cw.shape != (classes,) or not np.isfinite(cw).all() or np.any(cw <= 0) or np.any(cw > MAX_ROWS):
        raise ValueError('Positive bounded class balancing weights required')
    mw = {'positive': 1., 'negative': 1.} if mask_weights is None else mask_weights
    if (not isinstance(mw, dict) or set(mw) != {'positive', 'negative'}
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100 for v in mw.values())):
        raise ValueError('Bounded foreground/background mask balancing weights required')
    probabilities, prediction_mask, cache = _forward(p, x)
    h1, pooled, h2, features, mask_logits = cache
    b, half_h, half_w, c = h2.shape
    reduced_target = _pool(mask[..., None])[..., 0]
    weights = cw[target]
    class_logits = features@p['class_weights']+p['class_bias']
    largest = class_logits.max(axis=1)
    log_normalizer = largest+np.log(np.exp(class_logits-largest[:, None]).sum(axis=1))
    class_loss = float(np.mean(weights*(log_normalizer-class_logits[np.arange(b), target])))
    # logaddexp keeps BCE stable without clipping the loss's true logits.
    positive, negative = mw['positive'], mw['negative']
    mask_loss = float(np.mean(positive*reduced_target*np.logaddexp(0., -mask_logits)
        +negative*(1-reduced_target)*np.logaddexp(0., mask_logits)))
    delta = probabilities.copy()
    delta[np.arange(b), target] -= 1
    delta *= weights[:, None]/b
    gradients = {'class_weights': features.T@delta, 'class_bias': delta.sum(axis=0)}
    cell = half_h//4
    dh2_class = (delta@p['class_weights'].T).reshape(b, 4, 4, c)
    dh2_class = np.repeat(np.repeat(dh2_class, cell, axis=1), cell, axis=2)/(cell*cell)
    mask_delta = ((positive*reduced_target+negative*(1-reduced_target))*prediction_mask
        -positive*reduced_target)/(b*half_h*half_w)
    gradients['mask_weights'] = np.sum(h2*mask_delta[..., None], axis=(0, 1, 2))
    gradients['mask_bias'] = np.asarray(mask_delta.sum())
    dh2 = (dh2_class+mask_delta[..., None]*p['mask_weights'])*(1-h2*h2)
    dw2, db2, dpool = _conv_backward(pooled, p['conv2_weights'], dh2)
    gradients.update(conv2_weights=dw2, conv2_bias=db2)
    dh1 = np.repeat(np.repeat(dpool, 2, axis=1), 2, axis=2)/4
    dh1 *= 1-h1*h1
    dw1, db1, _ = _conv_backward(x[..., None], p['conv1_weights'], dh1, input_gradient=False)
    gradients.update(conv1_weights=dw1, conv1_bias=db1)
    return class_loss+mask_loss, gradients, {'class_loss': class_loss, 'mask_loss': mask_loss}


def _loss(p, x, masks, targets, class_weights, mask_weights, batch_size, cancelled):
    values = {'class_loss': 0., 'mask_loss': 0.}
    for start in range(0, len(x), batch_size):
        _check(cancelled)
        end = min(len(x), start+batch_size)
        _, _, metrics = loss_and_gradients(p, x[start:end], masks[start:end], targets[start:end],
            class_weights=class_weights, mask_weights=mask_weights)
        for key in values:
            values[key] += metrics[key]*(end-start)/len(x)
    return {**values, 'total_loss': sum(values.values())}


def _seal(value):
    value['id'] = digest({k: v for k, v in value.items() if k != 'id'})
    return value


def fit(x, masks, ylabels, *, epochs=30, channels=4, seed=0, batch_size=4,
        cancelled=lambda: False, progress=lambda value: None):
    images, targets_mask = _images(x, 'image'), _images(masks, 'mask')
    if images.shape != targets_mask.shape:
        raise ValueError('Matching source images and supervised target masks required')
    if (not isinstance(ylabels, list) or len(ylabels) != len(images)
            or any(not isinstance(v, str) or not v or len(v) > 80 for v in ylabels)):
        raise ValueError('One bounded semantic class per convolution image required')
    classes = sorted(set(ylabels))
    _settings(images.shape[1], channels, len(classes), epochs, batch_size)
    if type(seed) is not int or not 0 <= seed < 2**32 or not callable(cancelled) or not callable(progress):
        raise ValueError('Bounded convolution seed and callbacks required')
    work = estimate_work(len(images), input_size=images.shape[1], channels=channels,
        classes=len(classes), epochs=epochs, batch_size=batch_size)
    if work['forward_macs'] > MAX_FIT_FORWARD_MACS or work['activation_bytes_upper_bound'] > MAX_ACTIVATION_BYTES:
        raise ValueError('Convolution training work or activation budget exceeded')
    _check(cancelled)
    mean, scale = float(images.mean()), max(.1, float(images.std()))
    # Only the current fitting fold contributes normalization or class/mask
    # balance statistics. Held-out crops are never passed to this function.
    norm_x = (images-mean)/scale
    target = np.asarray([classes.index(value) for value in ylabels], dtype=np.int64)
    counts = np.bincount(target, minlength=len(classes))
    class_weights = len(images)/(len(classes)*counts.astype(np.float64))
    foreground = float(targets_mask.mean())
    mask_weights = {'positive': .5/max(foreground, .01), 'negative': .5/max(1-foreground, .01)}
    parameters = initialize(images.shape[1], channels, len(classes), seed)
    initial_pin = digest({k: v.tolist() for k, v in parameters.items()})
    initial = _loss(parameters, norm_x, targets_mask, target, class_weights, mask_weights, batch_size, cancelled)
    first = {k: np.zeros_like(v) for k, v in parameters.items()}
    second = {k: np.zeros_like(v) for k, v in parameters.items()}
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
                class_weights=class_weights, mask_weights=mask_weights)
            running += loss*len(batch)/len(images)
            step += 1
            for key in PARAMETER_KEYS:
                gradient = gradients[key]
                first[key] = .9*first[key]+.1*gradient
                second[key] = .999*second[key]+.001*gradient*gradient
                parameters[key] -= .01*(first[key]/(1-.9**step))/(np.sqrt(second[key]/(1-.999**step))+1e-8)
                np.clip(parameters[key], -100, 100, out=parameters[key])
        progress({'epoch': epoch+1, 'epochs': epochs, 'loss': running})
    _check(cancelled)
    final = _loss(parameters, norm_x, targets_mask, target, class_weights, mask_weights, batch_size, cancelled)
    arrays = {key: value.tolist() for key, value in parameters.items()}
    result = {'version': VERSION, 'architecture': {'input_size': images.shape[1], 'input_channels': 1,
        'channels': channels, 'conv_kernel_size': 3, 'convolutions': 2, 'pool_stride': 2,
        'class_grid': 4, 'class_features': 16*channels, 'classes': len(classes),
        'activation': 'tanh', 'mask_upsampling': 'nearest_2x', 'mask_activation': 'sigmoid'},
        'classes': classes, 'normalization': {'mean': mean, 'scale': scale}, 'parameters': arrays,
        'training': {'records': len(images), 'epochs': epochs, 'channels': channels,
            'seed': seed, 'batch_size': batch_size, 'class_balanced': True,
            'mask_balancing_weights': mask_weights, 'optimizer': 'Adam', 'learning_rate': .01,
            'initial_loss': initial['total_loss'], 'final_loss': final['total_loss'],
            'initial_class_loss': initial['class_loss'], 'final_class_loss': final['class_loss'],
            'initial_mask_loss': initial['mask_loss'], 'final_mask_loss': final['mask_loss'],
            'initial_parameters_sha256': initial_pin,
            'conv_filters_updated': any(np.any(parameters[k] != initialize(images.shape[1], channels, len(classes), seed)[k])
                for k in ('conv1_weights', 'conv2_weights'))},
        'work_estimate': work, 'production_eligible': False,
        'prediction_scope': 'Class and mask for an already-proposed source crop; not full-page discovery or 3D reconstruction.'}
    _seal(result)
    validate(result)
    return result


def validate(network):
    if (not isinstance(network, dict) or network.get('version') != VERSION
            or network.get('id') != digest({k: v for k, v in network.items() if k != 'id'})
            or network.get('production_eligible') is not False):
        raise ValueError('Exact research convolution network required')
    architecture, classes = network.get('architecture'), network.get('classes')
    if (not isinstance(architecture, dict) or not isinstance(classes, list)
            or not 1 <= len(classes) <= 16 or any(not isinstance(v, str) or not v or len(v) > 80 for v in classes)
            or classes != sorted(set(classes))):
        raise ValueError('Bounded convolution architecture and classes required')
    _settings(architecture.get('input_size'), architecture.get('channels'), len(classes))
    expected = {'input_size': architecture['input_size'], 'input_channels': 1,
        'channels': architecture['channels'], 'conv_kernel_size': 3, 'convolutions': 2,
        'pool_stride': 2, 'class_grid': 4, 'class_features': 16*architecture['channels'],
        'classes': len(classes), 'activation': 'tanh', 'mask_upsampling': 'nearest_2x', 'mask_activation': 'sigmoid'}
    if architecture != expected:
        raise ValueError('Exact bounded convolution architecture required')
    normalization = network.get('normalization')
    if (not isinstance(normalization, dict) or set(normalization) != {'mean', 'scale'}
            or type(normalization['mean']) not in (int, float) or not math.isfinite(normalization['mean'])
            or not 0 <= normalization['mean'] <= 1
            or type(normalization['scale']) not in (int, float) or not math.isfinite(normalization['scale'])
            or not .1 <= normalization['scale'] <= 1):
        raise ValueError('Finite bounded training-fold normalization required')
    _parameters(network.get('parameters'), architecture['channels'], len(classes))
    return network


def infer(network, x):
    validate(network)
    images = _images(x, 'image')
    if images.shape[1] != network['architecture']['input_size']:
        raise ValueError('Inference crop size differs from trained convolution network')
    p = _parameters(network['parameters'])
    normalization = network['normalization']
    classes, masks = [], []
    for start in range(0, len(images), 8):
        batch = (images[start:start+8]-normalization['mean'])/normalization['scale']
        probabilities, mask, _ = _forward(p, batch)
        classes.append(probabilities)
        masks.append(np.repeat(np.repeat(mask, 2, axis=1), 2, axis=2))
    return np.concatenate(classes), np.concatenate(masks)


def encode(network):
    validate(network)
    return copy.deepcopy(network)


def decode(value):
    if not isinstance(value, dict):
        raise ValueError('Open JSON convolution network object required')
    validate(value)
    return copy.deepcopy(value)
