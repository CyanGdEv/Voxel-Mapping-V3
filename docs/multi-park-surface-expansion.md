# Multi-park surface expansion and fixed transfer comparison

Two fresh surface heads were actually trained, adding Lightwater Valley and
Gulliver’s World Warrington to the original four images. The dataset contains
seven images across five parks: six training images across four parks, plus
Flamingo Land reserved from all fitting. The frozen aerial encoder was not updated.
The production baseline and world geometry remain unchanged.

## Results and decision

The reserved Flamingo comparison improves paving, structure, grass and canopy
on the provisional labelled interiors, but reduces water IoU. Alton transfer is
mixed and the tight-garden paving result regresses. Keep these experimental
checkpoints for review; do not replace the production baseline.

| Evaluation | Image | Model | Paving IoU | Structure IoU | Grass IoU | Water IoU | Canopy IoU |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| reserved-flamingo | flamingo-land | parent | 61.07% | 91.80% | 75.94% | 100.00% | 74.25% |
| reserved-flamingo | flamingo-land | expanded | 88.15% | 99.61% | 89.10% | 80.80% | 84.89% |
| alton-development | user-towers-mutiny | parent | 68.72% | 79.08% | 0.00% | 0.00% | 54.71% |
| alton-development | user-towers-mutiny | expanded | 74.85% | 80.04% | 74.08% | 15.01% | 27.38% |
| alton-development | user-gardens-lake | parent | 67.08% | 7.95% | 0.00% | 0.00% | 34.74% |
| alton-development | user-gardens-lake | expanded | 58.87% | 53.40% | 51.61% | 89.63% | 11.26% |
| alton-development | user-tight-gardens | parent | 28.64% | 16.35% | 0.00% | — | 61.58% |
| alton-development | user-tight-gardens | expanded | 16.93% | 1.35% | 42.39% | — | 37.49% |

All three Alton views are excluded from both Alton-development fits; those are
previously consumed development examples. The ordinary parent fit used only
Chessington there, with zero grass/water fitting labels. Expanded held-out
training has 22,707 grass and 9,884 water pixels, so absent-class coverage is
fixed, but that alone does not ensure precision. The original path probes fall
from **2/5 to 1/5** connected visible paths, with **0/2 false grass bridges** for
both models. Canopy transfer also regresses across all three Alton views.

The Flamingo comparison uses the parent all-four fit versus expanded all-six.
Its four ground supports are 5,157 paving, 10,164 structure, 10,198 grass and
3,771 water pixels. Only 29,290 of 1,048,576 ground pixels are labelled there.
Scores are computed only on known pixels. They are not full-scene accuracy,
surveyed edge error, or an independent human benchmark. The reserved park is
now a consumed benchmark, not a fresh unseen test for future tuning.

## Source labels and limits

New source images are original 1024-square Esri exports with returned extents
and hashes. OSM pedestrian routes define six-metre candidate-search corridors,
not path widths or copied edges. Neutral/warm RGB and low valid LiDAR heights
suggest small paving-interior candidates. Literal rectangles were visually
reviewed before fitting; ambiguous vegetation, roofs, rails and water edges were
removed. The retained paving counts are only 858 Lightwater and 980 Gulliver’s
pixels. This favours easy visible paving and is a known selection bias.

Roofs, grass, water and visible woodland interiors have separate provisional
polygons. Canopy polygons are small visible interiors, not measured complete
crowns or user marker radii. Hidden ground remains unknown; no canopy gap is
invented as observed paving. The large ambiguous green Flamingo basin remains
unknown. Conflicting classes and sparse polygon margins remain unknown. No
new dense interface labels were accepted, so no new boundary precision claim is
made. All new labels are assistant source-assisted drafts without independent
human review. Fine image export grids do not add source optical detail.

All 24 original image/receipt/mask assets are byte-identical. Original class
labels, inferred-ground exclusions and source registrations are retained.

## LiDAR and spatial alignment

Actual native one-metre EA DTM/last-return DSM pairs, British National Grid and
ODN, are retained. Lightwater uses P_10710 (18–19 November 2019, SE2575).
Gulliver’s uses P_11996 (11 February 2021, SJ5585/SJ5590). Flamingo uses P_10747
(18 April 2021, SE7575/SE7580). The latter two need tile mosaics: selection uses
the latest common matched year, then checks product survey identity/dates per
tile. Conflicting overlaps reject; native gaps stay nodata. A complete output
extent does not mean complete valid height coverage. Valid neighbourhoods cover
93.95%, 97.12% and 91.46% respectively. Survey and imagery epochs differ.

Existing Alton/Chessington pairs are reused. Height, terrain slope, three-metre
height roughness and valid-neighbourhood flags supply four context fields.
Nearest native-cell sampling preserves source resolution. Raw point clouds
were not used; low height does not prove paving, and water gaps are not flat
terrain. All cross-park image footprints exceed the 24-metre context guard;
overlapping Alton views stay in one park group.

## Training and reproducibility

A prospective protocol was frozen before new imagery or predictions. Its SHA256
is `0f945bb703213ed8b3a55d042113fdfe3f6449f1e57a3fd091b732c517770575`.
Labels were sealed before fitting; checkpoint/target hashes were sealed before
reserved prediction. No settings were selected from reserved scores and no
model is automatically promoted.

Both fits use the same 18,482-parameter, 20-channel head, frozen aerial16 plus
LiDAR4, seed137, 400 steps, batch4, 96-pixel patches, learning rate0.002,
balanced loss and 15% LiDAR dropout. This is one seed, not uncertainty across
training runs. Both parameter sets changed. Total fit/evaluation time was
118.0s at two CPU threads, peak process RSS
1123.8MiB, no GPU. Class weights use fitting labels only.
Whole-park evaluation flags are validated and rejected by generic fitting/save.

22 relevant tests pass: eight expansion/reservation/source-pin tests, eight existing
layered-learning tests and six LiDAR-context tests. The browser decodes all 30
source/label/prediction views, checks findings and captions, and has no runtime
errors, external requests or narrow-screen overflow.

The expanded dataset rebuild matches its manifest exactly. Each new LiDAR
array reproduces exactly from retained native pairs and datum grid. Four saved
candidate evaluations match safe checkpoint reloads exactly. Feature cache
receipts bind source hashes and the frozen encoder; marker colours never enter
features. Native data and recipes, source changes, model cards, checkpoint
seals, scores and tests are included in the downloadable review bundle.

The core ZIP ships the pinned built dataset, both new heads and both parent
heads. A separate source ZIP supplies all five native LiDAR pairs. The earlier
Aerial-Encoder-Research.zip supplies the unchanged common encoder. The helper
`prepare_features.py` rebuilds source-only feature caches from these inputs;
`python -m voxel_mapper.surface_transfer_experiment --help` describes the fixed
runner. Use the already-built dataset to preserve its exact ID. Relocating the
original additions request changes raw recipe hashes on a fresh build; numeric
masks remain source-bound, but that relocated build has a different identity.
This source patch requires the repository and optional research dependencies.

## Next precision work

Add independently checked, dense interfaces around narrow paths, roofs, water
edges and grass separators, including shadows and tree occlusion. Balance replay
with hard Alton examples and keep entire new parks for subsequent evaluation.
Do not tune against the consumed Flamingo scores and then call it unseen.

Imagery attribution: Esri and its providers; preserve per-source receipts and
applicable use terms. OSM © OpenStreetMap contributors, ODbL-1.0 (route search
locations and semantic checks only). Contains Environment Agency information
© Environment Agency and/or database right, OGL-UK-3.0. Frozen FLAIR encoder and
derived models retain NVIDIA upstream non-commercial research/evaluation scope;
model cards and licence accompany the bundle. No production licence expansion.
