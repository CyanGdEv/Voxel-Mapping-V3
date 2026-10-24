"""Prepare a hash-pinned pooled encoder from an already acquired official model.

Development command only: requires onnx==1.17.0, not an application dependency.
No network access or automatic model downloads are performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxel_mapper import study_pretrained_encoder as encoder


def _read(path, expected_sha256, expected_bytes=None, limit=64 * 1024 * 1024):
    source = Path(path)
    if not source.is_file() or not 0 < source.stat().st_size <= limit:
        raise ValueError('Bounded existing upstream artifact required: ' + str(source))
    with source.open('rb') as stream:
        raw = stream.read(limit + 1)
    if (len(raw) > limit or hashlib.sha256(raw).hexdigest() != expected_sha256
            or (expected_bytes is not None and len(raw) != expected_bytes)):
        raise ValueError('Upstream artifact hash or size changed: ' + str(source))
    return raw


def derive_model(source):
    """Stable extraction with ONNX's official graph extractor; no retraining."""
    import onnx
    if onnx.__version__ != '1.17.0':
        raise RuntimeError('Reproducible preparation requires development onnx==1.17.0')
    spec = encoder._registry()[encoder.PRETRAINED_SHA256]
    provenance = spec['provenance']
    if (len(source) != provenance['source_bytes']
            or hashlib.sha256(source).hexdigest() != provenance['source_sha256']):
        raise ValueError('Exact original MobileNetV2 graph bytes required')
    original = onnx.load_model_from_string(source)
    if any(t.data_location == onnx.TensorProto.EXTERNAL or t.external_data
            for t in original.graph.initializer):
        raise ValueError('Embedded tensor data required')
    pooled = onnx.utils.Extractor(original).extract_model(['input'], ['472'])
    # Shape inference cannot resolve this export's dynamic flatten dimensions.
    pooled.graph.output[0].CopyFrom(onnx.helper.make_tensor_value_info(
        '472', onnx.TensorProto.FLOAT, ['batch_size', 1280]))
    pooled.producer_name = 'voxel-mapper-study-gap-extractor'
    pooled.producer_version = '1'
    pooled.doc_string = ('Modified from onnx/models MobileNetV2 opset12: expose pooled 1280D '
        'tensor472; remove unreachable ImageNet classifier. Apache-2.0.')
    onnx.helper.set_model_props(pooled, {
        'upstream_sha256': provenance['source_sha256'],
        'upstream_commit': provenance['commit'], 'license': 'Apache-2.0'})
    if (any(node.op_type == 'Gemm' for node in pooled.graph.node)
            or any(t.name.startswith('classifier.') for t in pooled.graph.initializer)):
        raise ValueError('ImageNet classifier must be absent from pooled graph')
    onnx.checker.check_model(pooled)
    raw = pooled.SerializeToString(deterministic=True)
    if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != encoder.PRETRAINED_SHA256:
        raise ValueError('Derived graph differs from the registered deterministic artifact')
    return raw


def prepare_encoder(source_model, output_directory, *, license_file, readme_file):
    spec = encoder._registry()[encoder.PRETRAINED_SHA256]
    provenance = spec['provenance']
    source = _read(source_model, provenance['source_sha256'], provenance['source_bytes'])
    license_raw = _read(license_file, provenance['license_sha256'], limit=64_000)
    readme_raw = _read(readme_file, provenance['readme_sha256'], limit=64_000)
    raw = derive_model(source)
    output = Path(output_directory).expanduser().resolve()
    if output.exists():
        raise ValueError('Fresh output directory required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.study-encoder-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'bundle'
        stage.mkdir()
        name = 'mobilenetv2-12-gap.onnx'
        model_path = stage / name
        model_path.write_bytes(raw)
        info = encoder.encoder_info(model_path, encoder.PRETRAINED_SHA256)
        portable_info = {k: v for k, v in info.items() if k != 'path'}
        portable_info['filename'] = name
        (stage / 'encoder.json').write_text(json.dumps(portable_info, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        (stage / 'LICENSE').write_bytes(license_raw)
        (stage / 'UPSTREAM-README.md').write_bytes(readme_raw)
        notice = f'''# Frozen MobileNetV2 pooled encoder

This is a modified Apache-2.0 model from the official onnx/models repository.
Upstream commit: `{provenance['commit']}`.
Original URL: {provenance['source_url']}
Original SHA-256: `{provenance['source_sha256']}`; {provenance['source_bytes']} bytes.
Derived SHA-256: `{encoder.PRETRAINED_SHA256}`; {len(raw)} bytes.

Modification: ONNX 1.17.0's official Extractor exposes tensor `472`, the 1280-dimensional
flattened global-average-pool output, and removes unreachable ImageNet classifier
operations and weights. The output shape is explicitly declared. Producer metadata
and this change description were added; deterministic protobuf serialization is used.
Convolution weights are unchanged. The original model metadata says PyTorch 1.8;
the generic upstream README describes ImageNet training and MXNet workflows.
No more precise training checkpoint provenance was established.

`LICENSE` is the complete upstream Apache License 2.0. `UPSTREAM-README.md` is the
unmodified model README, with its Apache-2.0 statement, attribution and citations.
Preserve both with redistribution. This document records local modifications;
it is not an upstream NOTICE file. Source images from ImageNet are not included.

The model consumes RGB float32 tensors `[N,3,224,224]`, normalized from `[0,1]`
using mean `[0.485,0.456,0.406]` and standard deviation `[0.229,0.224,0.225]`.
The application resizes the whole supplied crop and composites alpha over white.
Descriptors are frozen visual inputs to a separate project-trained head; ImageNet
classes are not building predictions. There is no source-specific fine-tuning.

Preparation validates hashes, the ONNX graph and CPU ONNX Runtime interface.
No network access, remote inference, model auto-download or CUDA is used.
Windows execution and hardware-specific memory/latency require package testing.
'''
        (stage / 'PROVENANCE.md').write_text(notice, encoding='utf-8')
        pins = []
        for path in sorted(stage.iterdir()):
            pins.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name)
        (stage / 'SHA256SUMS').write_text('\n'.join(pins) + '\n', encoding='utf-8')
        os.replace(stage, output)
    result = dict(portable_info)
    result['path'] = str(output / name)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-model', required=True)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--license-file', required=True)
    parser.add_argument('--readme-file', required=True)
    args = parser.parse_args(argv)
    result = prepare_encoder(args.source_model, args.output_directory,
        license_file=args.license_file, readme_file=args.readme_file)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
