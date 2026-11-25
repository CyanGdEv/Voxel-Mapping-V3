# Expanded source-relative views and broad-class area pilot, 2026-11-25

## Actual outcome

Audited all 26 views without accepted georeferencing. **Seven** passed direct
reference matching, spatially withheld feature checks, image agreement at two
matching scales and visual alignment review. **19 remain without transforms.**
Total geographic coverage is now **327/346 samples**: 320 existing exact
source-window/rotation registrations plus seven reviewed approximate image fits.
These are not 327 independent observations or survey-verified positions.

The derivative preserves all 693 original non-manifest members byte-for-byte
and preserves all 320 existing transform dictionaries exactly. Original masks
were not repainted or converted into finer material labels. Real GIS, land cover,
DSM-DTM and raw ground-intensity context was subsequently packed for all 327
registered samples; 19 remain without context.

The supplied `Alton_Tree_Canopy_LiDAR_Training.zip` matches recorded SHA-256
`787851d42c29665049220f6876de73802b8b8afe26f7cc17db9aabe2e09f547e`.
Its 96 RGB tiles form a 2048 × 1088, 1 m EPSG:27700 mosaic with 1,499,136
known pixels. Missing tiles stay unknown; conflicting overlaps are rejected.
Only its RGB reference was used for these registrations. Canopy, mask, source
and LiDAR rasters were not substituted for reviewed ground-material targets.

The archive's older-world audit explicitly states
`x=easting-406912, z=343984-northing, y=ODN-99`. This corroborates the grid
recovered against terrain in the preceding cycle; it is related source lineage,
not a new independent survey. The RGB acquisition date and its separate license
scope are not established by the EA LiDAR's 2022 date/OGL declaration. Raw images
and masks remain workspace artifacts, not public Git files.

## Registration evidence

Each candidate is fitted **directly** to the georeferenced mosaic. A nearby
view is never used as a new geographic anchor, preventing accumulated chain
error. The matcher requires at least 24 distinct tentative correspondences,
16 fitting inliers, eight spatially withheld correspondences, 70% fitting
consensus, 80% withheld agreement within one reference pixel, at least 65%
control spread on both image axes, positive orientation and affine anisotropy
at most 1.05. At least 99% of the whole view must have known reference coverage;
grayscale image correlation must be at least 0.85.

RMS below refers to the withheld **within-1m feature-match consensus**, not all
tentative descriptors, a calibrated position error or independent ground truth.
Outlier counts and all-point p90 errors are retained in the evidence report.

| View | Withheld agreement | Within-consensus RMS | Image correlation |
|---|---:|---:|---:|
| parkwide_batch3/view_03 | 17/19 | 0.249 m | 0.965 |
| parkwide_batch3/view_04 | 8/10 | 0.420 m | 0.980 |
| parkwide_batch3/view_06 | 32/33 | 0.254 m | 0.961 |
| selected_aerials/view_01 | 15/17 | 0.305 m | 0.971 |
| selected_aerials/view_08 | 9/11 | 0.293 m | 0.959 |
| selected_aerials/view_09 | 9/11 | 0.382 m | 0.980 |
| selected_aerials/view_10 | 13/14 | 0.292 m | 0.944 |

All seven also pass at the second matching size (512 versus 1024 pixels).
Maximum corner disagreement between scales ranges from 0.069 to 0.272 m.
The original/reference/label review montage confirms matching visible scene
content; neither scale is counted as an independent evidence source.

Accepted fits carry a **minimum 1 m source-relative uncertainty allowance**,
not an independently calibrated error bound. No absolute survey accuracy or
fine material boundary precision is claimed. Pixel-centre/corner composition
and actual rounded resize dimensions are explicitly tested, including the
quarter-pixel correction needed when reference imagery is enlarged.

The 19 withheld views fail distinct-match, control-extent or fitting-consensus
gates. Reason counts overlap: 13 insufficient distinct matches, four limited
extent and three weak consensus. Very small/blurred crops cannot be admitted
merely because three points give zero affine fitting error. Two of the original
26 masks are entirely ignore; all other unregistered masks remain unchanged.

The accepted dataset contains full point evidence at
`registration-audit/primary.json`, `repeat.json` and the source-bound visual
review receipt. `apply_review` replays both fits, checks source hashes and image
agreement, refuses to replace existing registrations and writes a new archive.
Compact per-view results: `reviewed_view_registration_2026-11-25.json`.

## Split and target safeguards

Images are grouped conservatively by original source group and footprint
distance, including a 32 m requested separation plus registration allowances.
Three accepted views share one group, two share another; the seven views span
four new geographic groups, alongside the existing single Mutiny source group.
Repeated/overlapping scenes cannot become independent validation samples.

The derivative declares `registration_filter_required`. Both RGB and multisource
training then skip all 19 unregistered records; the geographic filter was
executed against the actual archive and returned 327 samples. The optional
`--require-georeference` flag enables the same filtering on older datasets.
Malformed accepted transforms are rejected rather than silently used.

For a separate broad-class experiment, the seven supplied masks were mapped
onto the native 1 m reference grid. A cell needs 95% source-class coverage;
unknown source pixels remain in the denominator. One-cell boundary erosion
leaves uncertain edges ignored. Overlaps are deduplicated and any contradictory
cell would remain ignored permanently, regardless of repeat votes.

Result: **2,333 unique conservative cells**, with zero remaining class conflicts:
474 generic grass and 1,859 generic paving. No stone, brick, asphalt, gravel,
concrete or vegetation-species labels were created from these broad masks.

The held-out geographic group is selected by `selected_aerials/view_01` before
model fitting. Training uses 2,097 unique cells (361 grass, 1,736 paving) in
46 overlapping windows across the other three areas. Validation contains
236 unique cells (113 grass, 123 paving), evaluated once each. Minimum distance
between training **image footprints** and the validation image is 406.17 m,
exceeding the requested buffer even with registration allowances.

## Executed broad-class benchmark

Six CPU runs: RGB versus 28-channel available-source context, seeds 41–43,
20 epochs, 64-pixel patches, batch size four, learning rate 0.001, two threads,
context dropout 0.2. Identical source archive, target pixels, geographic split
and hyperparameters are checked for each paired comparison.

| Seed | RGB mean IoU | Multisource mean IoU |
|---|---:|---:|
| 41 | 95.44% | 76.26% |
| 42 | 95.83% | 97.48% |
| 43 | 85.83% | 68.90% |
| Mean | **92.37%** | **80.88%** |

The multisource model is lower on average by **11.49 percentage points** and
regresses in two seeds. It is not promoted. The result supports further source
normalization/ablation work rather than assuming more channels improve accuracy.

This evaluates **two broad classes on 236 conservative interior cells in one
held-out area**. It is not comparable to the earlier brick/stone/asphalt IoU,
not fine-material or park-wide accuracy, and not independent imagery-source or
cross-park testing. Boundary pixels are deliberately ignored. Checkpoints are
selected on this validation area; there is no separate test set. Train windows
and seeds are not independent geographic replications.

Standalone seed-41 RGB and multisource inference was also executed. Its
georeferenced prediction rasters reproduce the respective trainer validation
confusion matrices exactly. Predictions remain candidates; uncalibrated
confidence does not authorize world placement. Full class metrics, confusion
matrices, hashes and preparation counts: `expanded_broad_area_results_2026-11-25.json`.

**Zero world blocks changed, no production model replaced, no new world export.**
The original v20 baseline is preserved. The expanded data supplies broad grass
and paving coverage; additional reviewed fine-material targets and more held-out
areas are still needed before a reliable reconstruction update.

## Reproduction

```sh
python -m pip install -e '.[gis,matching,train]'
python tools/audit_view_georef.py audit --dataset ground.zip --reference canopy.zip \
  --output output/audit-1024 --long-side 1024
python tools/audit_view_georef.py audit --dataset ground.zip --reference canopy.zip \
  --output output/audit-512 --long-side 512
# A source-bound review must identify the visually checked candidate IDs.
python tools/audit_view_georef.py apply --dataset ground.zip --reference canopy.zip \
  --primary output/audit-1024/audit.json --repeat output/audit-512/audit.json \
  --review review.json --output output/expanded-registered.zip
python tools/prepare_registered_broad_chips.py --dataset output/expanded-registered.zip \
  --reference canopy.zip --holdout-sample selected_aerials/view_01 \
  --output output/broad-area.zip
voxel-pack-multisource --dataset output/broad-area.zip \
  --catalog output/alton-live/training-catalog-full.json --output output/broad-context.zip
voxel-benchmark-multisource --dataset output/broad-context.zip --output output/seed41 \
  --validation-group geographic_299b80e09090 --require-georeference \
  --seed 41 --epochs 20 --patch-size 64 --batch-size 4 --cpu
```

Repeat seeds 42/43 in fresh output directories. Use the holdout group from the
generated manifest if view selection changes. The existing exact-paving recovery
now shares the validated mosaic reader; regression and actual-data checks confirm
the old 320 transforms remain intact. Tests cover resize/pixel conventions,
withheld-point rejection, repeated points, missing/conflicting reference tiles,
review replay/tampering, unknown-target handling and persistent conflict ignores.
