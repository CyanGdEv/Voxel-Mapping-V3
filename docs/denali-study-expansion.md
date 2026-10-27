# Denali drawing expansion and site-isolated model comparison

This stage adds 21 source-reviewed component examples from three Denali buildings
and compares the existing small classifier with frozen pretrained visual features.
It improves the evidence and evaluation tools; it does not promote a reconstruction
model or generate world blocks.

## Original sources and review

The source profile pins three Library of Congress HABS field-team drawing JPEGs:

| Building | Catalogue | Sheet |
| --- | --- | --- |
| Former comfort station / residence | [AK-35-N](https://www.loc.gov/item/ak0139/) | 1 |
| Electric light plant / ranger office | [AK-35-L](https://www.loc.gov/item/ak0137/) | 1 |
| Administration building | [AK-35-C](https://www.loc.gov/item/ak0128/) | 1 |

All three assets were downloaded twice with identical pinned bytes (286,696 bytes
total). They are service JPEGs approximately 1024 pixels wide, not original CAD or
high-resolution survey scans. The LOC advisory distinguishes Government-made
images from potentially restricted third-party copies. This intake uses the HABS
measured drawings, retaining the scoped advisory and original bytes.

The assistant visually reviewed the original sheets and crop/mask gallery before
evaluation. Review coordinates retain three-original-pixel uncertainty. Survey
epoch remains unknown in the machine-readable records; source state means the
historical condition as drawn, not current physical verification. Component counts:
four plan envelopes, six roof envelopes/partial traces, three doors, three windows,
three wall envelopes and two brace traces. Multiple floors of one building are
one connected group. Wall plan envelopes include openings; they are not solid
wall occupancy masks. Partial roof and brace traces remain open lines.

Two central openings on the plant's south elevation were excluded before freezing
the review because their window/door identity was ambiguous at this resolution.
The final review contains 21 examples; an initial untrained review draft had 23.
No labels were changed after inspecting predictions. Original raster replay from
the independently downloaded cache was byte-identical.

## Evaluation boundaries

The intake has 183 examples, three sites, 16 connected groups and 30 original
source identities (23 PDFs and seven rasters). Training uses 148 Alton examples
plus 14 Glen Echo examples. Glen Echo's previous holdout is now development
training data and must no longer be reported as untouched evaluation evidence.
All 21 Denali examples, all three Denali buildings and their source hashes remain
outside training normalization and fitted weights.

The fixed comparison uses the established 150-epoch, 16-hidden-unit small
classifier and the registered frozen MobileNetV2 descriptors with class/mask
ridge heads (alpha 100, 64-pixel masks decoded on a 16-pixel grid). The generic
encoder remains unchanged. Both saved checkpoints fit training sites only, with
no final all-data refit. The template is the mean training mask, without a
held-out class or mask selecting its prediction.

| Denali measure | Small classifier | Frozen features | Baseline |
| --- | ---: | ---: | ---: |
| Correct component classes | 10/21 (47.62%) | 7/21 (33.33%) | Majority: 2/21 (9.52%) |
| Class macro F1 over union of 14 classes | 0.25714 | 0.24459 | 0.02899 |
| Equal-building class accuracy | 45.48% | 29.05% | — |
| Mean binary mask IoU | — | 0.45360 | Mean mask: 0.30184 |
| Equal-building binary mask IoU | — | 0.45479 | Mean mask: 0.29593 |
| Mean soft mask IoU | — | 0.37536 | Mean mask: 0.25498 |

Neither model classifies any of the four building-plan examples correctly. The
pretrained model's class accuracy is weaker than the small classifier's here,
although its mask predictions beat the template on average. These 21 supplied
crops from three historical buildings do not demonstrate complete building
recognition, automatic page discovery, dimensions, multi-view assembly or park
reconstruction. No new path/plaza examples were acquired. Results on this new
site/protocol cannot be treated as a gain over the previous 2/14 Glen Echo test.

Denali is now inspected evaluation evidence. Reserve a fresh site before tuning
or selecting models in a later stage. No hyperparameter search or production
promotion follows this comparison.

## Replay and implementation

```sh
python -m voxel_mapper.study_source_acquisition \
  --profile evidence/denali-source-profile.json --output FRESH-SOURCES
python -m voxel_mapper.study_raster_dataset \
  --review evidence/denali-source-review.json --sources FRESH-SOURCES \
  --output FRESH-DENALI-DATASET
# Build the three-dataset intake with denali-national-park reserved.
python -m voxel_mapper.study_site_evaluation \
  --dataset FRESH-INTAKE --output FRESH-CROP-EXPERIMENT
python -m voxel_mapper.study_site_transfer \
  --dataset FRESH-INTAKE --output FRESH-TRANSFER-EXPERIMENT \
  --encoder PATH/mobilenetv2-12-gap.onnx \
  --encoder-sha256 674dc0911a76190cb956be54ab6190b260e9cb5b7ef758a4742cfeeaacdcf6eb
```

The portable delivery includes an intake request with relative paths, unmodified
original datasets, both checkpoints, frozen encoder and attribution, reports and
review galleries. Changing the request's path spelling changes its manifest ID;
fitted parameter values and results should reproduce in the recorded runtime.
The default all-data trainers continue refusing reserved evaluation datasets.

The new site transfer evaluator recomputes the reservation, verifies masks and
crops, passes source pixels only to the frozen encoder, and fits only the training
partition. Output is fresh and atomically published with the pinned encoder and
license. Synthetic tests change held-site pixels and masks together and confirm
identical training parameters/normalization. They also exercise forged/missing
reservations, corrupt assets and cancellation. Sixty-seven focused engineering
tests pass; these are software checks, not physical reconstruction acceptance.

The validation receipt in `evidence/denali-study-validation.json` records the
actual source/model pins, reproduced saved predictions and normalization, lineage
isolation and record/equal-building metrics. The next data priority remains
clear independent path/plaza plans and further buildings on new sites.
