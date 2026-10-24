"""Pinned, CPU-only frozen visual descriptors for bounded supplied PNG crops.

Only the registered graph bytes are accepted. The encoder receives pixels only;
project classes, target masks and source identifiers are never encoder inputs.
The tiny embedded graph is a synthetic runtime fixture, not pretrained AI.
"""
import base64
from concurrent.futures import CancelledError
import copy
import hashlib
from importlib.resources import files
from io import BytesIO
import json
from os import PathLike
from pathlib import Path

import numpy as np
from PIL import Image

PRETRAINED_SHA256 = '674dc0911a76190cb956be54ab6190b260e9cb5b7ef758a4742cfeeaacdcf6eb'
SYNTHETIC_SHA256 = '60727da04ebe53faef18baa0b6ac4fc300d32ea86d88c4a55969ddacf5c8a4ce'
MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 1_000_000
MAX_IMAGES = 2048
MAX_BATCH = 4
INPUT_SIZE = 224
_KNOWN = {
    PRETRAINED_SHA256: ('mobilenetv2-imagenet-gap-v1', 8_844_908, 1280, False, '472'),
    SYNTHETIC_SHA256: ('synthetic-mean-rgb-v1', 226, 3, True, 'mean_rgb'),
}
_SYNTHETIC_BASE64 = (
    'CAcSHnZveGVsLW1hcHBlci1zeW50aGV0aWMtZml4dHVyZTq3AQpLCgVpbnB1dBIIbWVhbl9y'
    'Z2IaDHNwYXRpYWxfbWVhbiIKUmVkdWNlTWVhbioNCgRheGVzQAJAA6ABByoPCghrZWVwZGlt'
    'cxgAoAECEh92b3hlbF9tYXBwZXJfc3ludGhldGljX21lYW5fcmdiWiYKBWlucHV0Eh0KGwgB'
    'EhcKBxIFYmF0Y2gKAggDCgMI4AEKAwjgAWIfCghtZWFuX3JnYhITChEIARINCgcSBWJhdGNo'
    'CgIIA0IECgAQDA=='
)


def _registry_document():
    raw = files('voxel_mapper').joinpath('data/study-pretrained-encoder.json').read_bytes()
    if len(raw) > 64_000:
        raise ValueError('Bounded encoder registry required')
    value = json.loads(raw)
    if value.get('version') != 'study-pretrained-encoder-registry-v1':
        raise ValueError('Known encoder registry required')
    return value


def _registry():
    value = _registry_document()
    encoders = value.get('encoders')
    if not isinstance(encoders, list) or len(encoders) != len(_KNOWN):
        raise ValueError('Exact registered encoders required')
    result = {}
    for item in encoders:
        sha = item.get('sha256')
        if sha not in _KNOWN or sha in result:
            raise ValueError('Known encoder SHA-256 required')
        identity, size, count, synthetic, output = _KNOWN[sha]
        if (item.get('id'), item.get('bytes'), item.get('feature_count'),
                item.get('synthetic'), item.get('output_name')) != (
                    identity, size, count, synthetic, output):
            raise ValueError('Registered encoder interface changed')
        result[sha] = item
    return result


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise CancelledError('Frozen study encoder cancelled')


def validate_info(metadata, *, allow_synthetic=False):
    """Validate portable encoder metadata without loading a model or runtime."""
    if not isinstance(metadata, dict) or type(allow_synthetic) is not bool:
        raise ValueError('Registered encoder metadata required')
    sha = metadata.get('sha256')
    if not isinstance(sha, str) or sha not in _KNOWN:
        raise ValueError('Known encoder metadata SHA-256 required')
    spec = _registry()[sha]
    if spec['synthetic'] and not allow_synthetic:
        raise ValueError('Synthetic encoder metadata requires an explicit synthetic dataset')
    if any(type(metadata.get(key)) is not type(value) or metadata.get(key) != value
            for key, value in spec.items()):
        raise ValueError('Registered encoder metadata changed')
    if 'provider' in metadata and metadata['provider'] != 'CPUExecutionProvider':
        raise ValueError('CPU-only encoder metadata required')
    if 'input_name' in metadata and metadata['input_name'] != 'input':
        raise ValueError('Registered encoder input name required')
    for name, dimensions in [('input_shape', [3, 224, 224]),
                             ('output_shape', [spec['feature_count']])]:
        if name in metadata:
            shape = metadata[name]
            if (not isinstance(shape, list) or len(shape) != len(dimensions) + 1
                    or shape[1:] != dimensions or shape[0] not in ('batch', 'batch_size')):
                raise ValueError('Registered encoder tensor shape metadata required')
    return copy.deepcopy(metadata)


def attribution_assets(metadata):
    """Return pinned attribution bytes for a portable bundle, with no network IO."""
    info = validate_info(metadata, allow_synthetic=True)
    portable = {k: v for k, v in info.items() if k != 'path'}
    result = {'encoder-provenance.json':
        (json.dumps(portable, indent=2, sort_keys=True) + '\n').encode('utf-8')}
    if info['synthetic']:
        result['encoder-NOTICE.txt'] = (info['provenance']['scope'] + '\n').encode('utf-8')
        return result
    documents = _registry_document().get('upstream_documents', {})
    for name, pin in [('LICENSE', info['provenance']['license_sha256']),
                      ('UPSTREAM-README.md', info['provenance']['readme_sha256'])]:
        text = documents.get(name)
        if not isinstance(text, str) or hashlib.sha256(text.encode('utf-8')).hexdigest() != pin:
            raise ValueError('Pinned packaged upstream attribution text required')
        result[name] = text.encode('utf-8')
    result['encoder-MODIFICATIONS.txt'] = (
        'Modified Apache-2.0 MobileNetV2 graph from ' + info['provenance']['repository'] + '\n'
        + 'Upstream commit: ' + info['provenance']['commit'] + '\n'
        + 'Original SHA-256: ' + info['provenance']['source_sha256'] + '\n'
        + 'Derived SHA-256: ' + info['sha256'] + '\n'
        + info['provenance']['modification'] + '\n'
        + 'The accompanying README is unmodified upstream attribution.\n').encode('utf-8')
    return result


def license_text(metadata):
    """Return the complete pinned Apache license, or synthetic fixture notice."""
    assets = attribution_assets(metadata)
    return assets.get('LICENSE', assets.get('encoder-NOTICE.txt')).decode('utf-8')


def _checked_model(path, sha256, allow_synthetic):
    if type(allow_synthetic) is not bool or not isinstance(sha256, str) or sha256 not in _KNOWN:
        raise ValueError('An exact registered encoder SHA-256 is required')
    spec = _registry()[sha256]
    if spec['synthetic'] and not allow_synthetic:
        raise ValueError('Synthetic encoder is allowed only for an explicit synthetic dataset')
    source = Path(path).expanduser()
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_MODEL_BYTES:
        raise ValueError('Bounded existing embedded-data ONNX encoder required')
    with source.open('rb') as stream:
        raw = stream.read(MAX_MODEL_BYTES + 1)
    if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('Encoder bytes do not match the registered SHA-256 and size')
    return source, raw, spec


def _session(raw, spec):
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError('The packaged CPU ONNX Runtime is required for frozen visual features') from error
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # Bytes, rather than a model filename, prevent relative external-data loads.
    session = ort.InferenceSession(raw, sess_options=options, providers=['CPUExecutionProvider'])
    session.disable_fallback()
    if session.get_providers() != ['CPUExecutionProvider']:
        raise ValueError('CPU-only encoder execution required')
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if (len(inputs) != 1 or len(outputs) != 1
            or inputs[0].name != 'input' or inputs[0].type != 'tensor(float)'
            or len(inputs[0].shape) != 4 or inputs[0].shape[1:] != [3, 224, 224]
            or outputs[0].name != spec['output_name'] or outputs[0].type != 'tensor(float)'
            or len(outputs[0].shape) != 2 or outputs[0].shape[1] != spec['feature_count']):
        raise ValueError('Registered encoder tensor interface changed')
    return session, ort.__version__


def encoder_info(path, sha256, *, allow_synthetic=False):
    """Verify model bytes and actual CPU runtime interface; return JSON metadata."""
    source, raw, spec = _checked_model(path, sha256, allow_synthetic)
    session, runtime_version = _session(raw, spec)
    result = copy.deepcopy(spec)
    result.update(path=str(source.resolve()), provider='CPUExecutionProvider',
        runtime_version=runtime_version, input_name='input',
        input_shape=list(session.get_inputs()[0].shape),
        output_shape=list(session.get_outputs()[0].shape),
        preprocessing=copy.deepcopy(_registry()[sha256]['preprocessing']))
    return result


def _source_tensor(image):
    if isinstance(image, bytes):
        raw = image
    elif isinstance(image, (str, PathLike)):
        path = Path(image)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError('Bounded existing source PNG required')
        with path.open('rb') as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
    else:
        raise ValueError('Source crops must be PNG bytes or paths')
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError('Source PNG must be at most 1 MB')
    try:
        with Image.open(BytesIO(raw)) as original:
            width, height = original.size
            if (original.format != 'PNG' or not 1 <= width <= 256 or not 1 <= height <= 256
                    or getattr(original, 'n_frames', 1) != 1):
                raise ValueError('Single-frame PNG crop at most 256 by 256 required')
            if original.mode in ('RGBA', 'LA') or 'transparency' in original.info:
                rgba = original.convert('RGBA')
                opaque = Image.new('RGBA', original.size, 'white')
                opaque.alpha_composite(rgba)
                rgb = opaque.convert('RGB')
            else:
                rgb = original.convert('RGB')
            # Resize the entire supplied crop; no target-derived bounding box or crop.
            resized = rgb.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
            pixels = np.asarray(resized, dtype=np.float32) / np.float32(255.)
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('Valid bounded source PNG required') from error
    mean = np.asarray([.485, .456, .406], dtype=np.float32)
    std = np.asarray([.229, .224, .225], dtype=np.float32)
    return np.ascontiguousarray(((pixels - mean) / std).transpose(2, 0, 1))


def extract(images, encoder_path, encoder_sha256, *, allow_synthetic=False,
            cancelled=None, progress=None):
    """Return N by D frozen descriptors; callbacks receive no labels or targets."""
    if not isinstance(images, (list, tuple)) or not 0 <= len(images) <= MAX_IMAGES:
        raise ValueError('At most 2048 bounded source PNG crops required')
    _check(cancelled)
    _, raw, spec = _checked_model(encoder_path, encoder_sha256, allow_synthetic)
    session, _ = _session(raw, spec)
    result = np.empty((len(images), spec['feature_count']), dtype=np.float32)
    for start in range(0, len(images), MAX_BATCH):
        _check(cancelled)
        batch = []
        for image in images[start:start + MAX_BATCH]:
            _check(cancelled)
            batch.append(_source_tensor(image))
        _check(cancelled)
        output = session.run([spec['output_name']], {'input': np.stack(batch)})[0]
        _check(cancelled)
        stop = start + len(batch)
        if (output.shape != (len(batch), spec['feature_count'])
                or output.dtype != np.float32 or not np.isfinite(output).all()):
            raise ValueError('Finite registered encoder output shape required')
        result[start:stop] = output
        if progress is not None:
            progress({'progress': stop / len(images), 'message': 'Extracting frozen CPU visual features',
                'completed': stop, 'total': len(images)})
    _check(cancelled)
    return result


def synthetic_encoder(path):
    """Write a fresh tiny fixture for explicit synthetic tests; never pretrained AI."""
    target = Path(path).expanduser()
    raw = base64.b64decode(_SYNTHETIC_BASE64, validate=True)
    if hashlib.sha256(raw).hexdigest() != SYNTHETIC_SHA256:
        raise ValueError('Embedded synthetic fixture changed')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(raw)
    result = copy.deepcopy(_registry()[SYNTHETIC_SHA256])
    result['path'] = str(target.resolve())
    return result
