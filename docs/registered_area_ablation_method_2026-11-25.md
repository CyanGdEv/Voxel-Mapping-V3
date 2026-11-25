# Buffered registered-area source ablations

The earlier broad-label pilot found worse average validation IoU with context.
This cycle tests whether that result depends on source, geographic area, input
width, continuous-value scaling, or the context available at crop edges. The
production model and supplied Bedrock world are not replaced by these tests.

## Protocol

Use the seven reviewed direct registrations in
`Alton_Towers_Expanded_Registered_Training_V2.zip`, with the SHA-256-verified
canopy archive as the native 1m RGB reference. Retain only reviewed broad grass
and unspecified paving. Require 95% class coverage, erode uncertain boundaries,
deduplicate overlaps, and ignore conflicts. Source lineage remains shared.

Prepare separate holdouts using `selected_aerials/view_01`,
`parkwide_batch3/view_03`, and `selected_aerials/view_10`. These names identify
source views, not independently verified park attractions. Expand each tight
validation box by 64 pixels on every side, preserving the inference tile phase.
Do not add validation labels. Keep training images at least 34m from the expanded
validation image, including the existing registration allowances. Refuse an
expansion that would clip the origin and change tile phase.

Run seeds 41, 42 and 43, 20 epochs, batch size 4, 64-pixel patches, learning rate
0.001, ten output IDs, CPU with two Torch threads, and whole-modality dropout
0.2. Keep the existing validation-based checkpoint selection. This is not an
independent test set; neither selection across epochs nor source ablation
establishes deployment accuracy.

Configurations:

- RGB, using the existing three-channel model.
- Zero-context 28-channel control, including zero validity masks. This separates
  changes in input width and initialization from contextual evidence.
- Vector evidence only, satellite land cover only, height only, intensity only.
- All available context with existing fixed physical normalization.
- All context with training-input-only positive-value p95 caps for height and
  intensity. Clip values at one; preserve missing zeros and validity masks.
  Height caps cannot be smaller than 1m. Persist fitted state in checkpoints and
  replay it in standalone inference. No validation values or labels enter this
  fit. Overlapping training pixels contribute to scaling statistics; they are
  not independent observations.

`tools/benchmark_registered_areas.py` calls the existing trainer and writes
input hashes, coverage, reports and checkpoints. `tools/evaluate_ground_candidates.py`
reuses candidate inference to score held-out rasters, checks geographic grids,
and reports per-class IoU, precision, recall, false-positive rates and 15-bin
top-label confidence reliability. The mean IoU denominator remains the reviewed
validation classes, matching the trainer. Confidence statistics are descriptive
on validation-selected checkpoints, not proof of calibration.

True boundary accuracy cannot be established with deliberately eroded interior
labels. Missing reconstruction geometry cannot be measured from classification
rasters. Those metrics remain explicitly unavailable. Unspecified paving cannot
establish a fine Minecraft material.

## Reproduction

```bash
python -m tools.prepare_registered_broad_chips \
  --dataset Alton_Towers_Expanded_Registered_Training_V2.zip \
  --reference Alton_Tree_Canopy_LiDAR_Training.zip \
  --holdout-sample selected_aerials/view_01 --validation-margin 64 \
  --output east.zip
python -m voxel_mapper.multisource_chips --dataset east.zip \
  --catalog evidence/alton/training-catalog-full.json --output east-context.zip
# Repeat preparation/packing for the other two holdout views.
python -m tools.benchmark_registered_areas \
  --dataset east=east-context.zip --dataset south=south-context.zip \
  --dataset north=north-context.zip --output experiments/area-ablations
```

All outputs remain candidates. The unchanged original world checksum is
`0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
