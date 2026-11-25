# Real GIS production-architecture pilot, 2026-11-25

The supplied ground archive and offline pilot match their recorded SHA-256
checksums. The supplied v20 Go Jetters world has SHA-256
`0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
All three archives pass ZIP member integrity checks. The original world is
preserved; inspection uses an extracted working copy.

## Actual attachment and spatial split

The real ArcGIS/2025 land-cover context from the preceding live acquisition was
attached to **320/346** ground archive samples. All 693 original non-manifest
members retain identical bytes. The 26 unregistered views remain without
context; no provisional alignments were promoted.

`tools/prepare_mutiny_spatial_pilot.py` verifies all 80 unrotated source windows
against the supplied pilot RGB and reconstructs exactly its 3,202 deduplicated
reviewed pixels. It checks the registered chip transforms and rejects conflicting
labels. Rotated/overlapping samples are not independent validation observations.

The experiment uses the production trainer and its 28-channel architecture on a
buffered derivative of this verified source crop, not a random split of the 320
views. BNG origin is [407312,343671], at 1 m per pixel:

- Training: source columns [0,134), 12 overlapping 64-pixel windows containing
  1,146 unique reviewed pixels (212 stone, 934 brick). These windows are repeated
  views, not 12 independent geographical examples.
- Validation: source columns [166,267), one 101 × 211 image, 1,243 unique
  reviewed pixels (690 stone, 535 brick, 18 asphalt), evaluated once each.
- Excluded separation: 32 m. No training image window reaches the validation
  region. All seeds use the same explicit validation group.

This is one source crop and one spatial partition. It is **not independent
source validation, whole-park accuracy or cross-park generalisation**. The
26 other views cannot supply geographically verified holdouts yet.

## Executed results

Twelve CPU runs: four input conditions × seeds 41–43, 20 epochs, batch size 4,
64-pixel patches, learning rate 0.001, two CPU threads. Full and ablated models
retain the 28-channel width; excluded modalities and validity masks are zeroed.
RGB uses three channels. Multisource modality dropout is 0.2. Training batches,
area groups and settings match across modes at each seed. Each run selects its
checkpoint using validation mean IoU; these are not independent test scores.

| Input | Seed 41 | Seed 42 | Seed 43 | Mean IoU |
|---|---:|---:|---:|---:|
| RGB | 33.02% | 33.14% | 22.30% | **29.49%** |
| RGB + ArcGIS vectors | 19.67% | 38.28% | 23.81% | **27.25%** |
| RGB + satellite | 20.84% | 29.66% | 20.96% | **23.82%** |
| RGB + available vectors and satellite | 21.89% | 39.71% | 33.18% | **31.59%** |

Combined minus RGB: **+2.10 percentage points**, improving two seeds and
regressing one. Vector-only and satellite-only averages are below RGB. The result
does not justify production promotion. It is not directly comparable with the
earlier 13-channel experiment: architecture, input evidence, training procedure
and evaluated classes differ. Here asphalt is retained as a reviewed validation
class despite having no training pixels; the model has the existing ten outputs.

The full schema is exercised, but **not all modalities contain real evidence**:
height and intensity remain unknown, as do OS water polygons. The archived
pilot's positive vegetation counts cannot be relabelled as DSM-DTM height or raw
intensity. OSM-only and LiDAR-only ablations remain unexecuted pending suitable
aligned sources. All current geometry inputs are context, not material labels.

Per-class IoU/precision/recall, confusion matrices and dataset hashes are recorded
in `mutiny_production_28_results_2026-11-25.json`. Boundary accuracy and missing
geometry rate are not established by sparse paving masks. No whole-park or
Magic Kingdom evaluation has run; its archive is still absent.

## Inference and world gate

The trainer now exposes one shared architecture for training and standalone
inference; parameter names remain compatible with existing checkpoints.
`voxel-predict-surfaces` (or `python -m voxel_mapper.predict_ground_model`)
loads tensor-only checkpoint data, validates the input schema, applies saved
ablation groups and writes geographically aligned class and uncalibrated
confidence TIFFs with checksums and source provenance. Missing registration is
reported rather than guessed. It refuses to reuse an output directory.

Executed seed-42 combined inference on all 13 derivative samples. The east
holdout transform is [1,0,407478,0,-1,343671] in EPSG:27700. Regression testing
checks raster georeferencing and exact agreement with the trainer's held-out
confusion matrix. The validation preview shows unreliable candidate classes
outside the sparse paving labels; inference does not establish accepted geometry.

On the seed-42 validation-selected model, labelled-pixel accuracy is 54.87%
and ten-bin confidence ECE is 0.2612. This uses the same validation area and is
not independent calibration. Raw softmax scores are not calibrated confidence.
No acceptance threshold or production checkpoint was selected from this result.

The supplied world contains native LevelDB and prior placement audits, but no
geographic registration receipt or vertical datum mapping. Its positive game
coordinates must not be assigned a BNG origin from an unrelated branch merely
because they look plausible. Reuse the previously inspected native Bedrock
pipeline; establish the supplied world's transform against verified anchors
before integrating material predictions. **Zero world blocks changed; no
replacement or fabricated baseline was generated.**

## Reproduction

```sh
python tools/prepare_mutiny_spatial_pilot.py \
  --training /path/Alton_Towers_Georeferenced_Ground_Training.zip \
  --pilot /path/Mutiny_Bay_Offline_Multisource_Pilot.zip \
  --output output/mutiny-spatial.zip
voxel-pack-multisource --dataset output/mutiny-spatial.zip \
  --catalog output/alton-live/training-catalog.json --output output/mutiny-context.zip
voxel-benchmark-multisource --dataset output/mutiny-context.zip \
  --output output/seed41 --validation-group east_validation \
  --seed 41 --epochs 20 --patch-size 64 --batch-size 4 --cpu
```

Repeat seeds 42 and 43 in fresh output directories. For source ablations, run
the trainer with the same settings, `--multisource`, and either
`--context-group landcover` or all six vector groups (`building`, `water`,
`woodland`, `habitat`, `heritage`, `watercourse`). Keep the same dataset,
validation group, seed and optimizer settings. Acquisition reproduction is in
`live_alton_gis_audit_2026-11-24.md`. Generated images, checkpoint binaries and
private source/world archives remain workspace artifacts, not public Git files.
