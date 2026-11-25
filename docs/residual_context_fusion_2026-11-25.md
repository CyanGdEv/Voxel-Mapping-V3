# Frozen RGB with bounded contextual corrections

This experiment addresses full-context regression without changing the existing
RGB model weights. It adds an opt-in `rgb_residual_v1` architecture to the shared
trainer/inference factory; existing three- and 28-channel U-Net state dictionaries
retain their previous keys and default behavior.

The frozen RGB U-Net supplies logits. A small convolutional adapter reads RGB
and the aligned context and adds `tanh(adapter)`, bounded to ±1 logit per class.
Its last layer is zero-initialized. RGB parameters and BatchNorm running
statistics remain frozen. At any pixel without a known contextual source,
the correction is exactly zero. This is a missing-context guarantee, not a
conflict-detection or per-pixel correctness guarantee.

An RGB-only adapter control has the same parameter count, correction bound,
initialization and availability gate, but receives zeros in all contextual
adapter inputs. It can learn RGB corrections and uses the same outage gate.
Comparison against this control distinguishes extra optimization/capacity from
benefit attributable to contextual inputs. Availability itself remains shared.

Each warm start must have matching declared training and validation membership,
source ZIP hashes, class map, seed, split and inference tile size. The checkpoint
and its report hashes are recorded. This validates supplied training metadata;
it is not an independent certification of a checkpoint's training history.

## Fixed protocol

Reuse the three buffered area datasets and RGB seed checkpoints from the
72-run ablation cycle. Each adapter trains for 20 additional epochs, batch 4,
64-pixel patches, learning rate 0.001, two CPU threads, context dropout 0.2.
Fit height/intensity p95 caps on training inputs only. Add 0.05 times mean squared
logit correction to the training loss. These settings are fixed across areas
and seeds, with no per-area tuning.

The zero-correction checkpoint is explicitly included in validation selection.
Thus validation non-regression is partly guaranteed by selection and cannot
establish non-regression on new data. This is a warm-start experiment with extra
optimization, not a compute-matched comparison to from-scratch RGB training.
Both context and RGB-only correction modes must be reported.

```bash
python -m tools.benchmark_residual_fusion \
  --baselines /workspace/experiments/registered-area-ablations-v1 \
  --output /workspace/experiments/residual-fusion-v1
python -m tools.benchmark_residual_fusion \
  --baselines /workspace/experiments/registered-area-ablations-v1 \
  --output /workspace/experiments/residual-rgb-control-v1 --rgb-only-control
```

The runner checks initial validation IoU against the paired baseline, reuses
existing paired comparison checks and standalone inference, and verifies exact
confusion-matrix equality. It records actual held-out pixel changes, newly
corrected mistakes and previously correct pixels harmed, as well as precision,
recall, IoU, false-positive rates and descriptive top-label confidence reliability.

An independent new reviewed area is not available in the current accepted
archives. Existing areas have already informed architecture development. These
runs are diagnostic validation, not an independent final test. Broad paving
labels do not establish brick, stone or another fine material. No result from
this experiment automatically replaces production or authorizes block placement.
Existing verified world geometry remains untouched.
