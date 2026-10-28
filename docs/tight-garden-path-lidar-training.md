# Tight garden paths with aligned LiDAR context

The fourth user example adds narrow garden paths, bends, terraces and planted
separators. Training now compares imagery alone with matched dated LiDAR
context, retaining independent ground and canopy heads. Models remain research
checkpoints; the production baseline and world geometry are unchanged.

## Intake and draft labels

The original 778 × 1280 user image yields 475 red path-boundary marks, 61 purple
structure marks and 35 tree locations. The image is aligned to separately pinned,
unmarked Esri imagery using 694 SIFT inliers, median error
0.366 and p95 error
0.926 clean pixels. This is image registration,
not surveyed ground accuracy. Annotation colours never enter neural features.
The source receipt reports a 0.5 m image observation dated 27 May 2023; the
0.190 m export grid does not add optical detail.

Seventeen literal regions contain eight path polygons, five structure polygons
(including the user-confirmed purple circle) and four grass patches. The circle
is structure supervision, not canopy; conflicting path-edge pixels stay unknown. A small dense window labels two nearby paths and their
intervening grass. Four visible crown polygons are traced independently of green
marker radii. Ground beneath crowns and existing inferred canopy paths stays
unknown for observed supervision. No water labels are invented for this image.

New known ground counts: 23,135 paving,
8,402 structures,
13,180 grass. New canopy-positive pixels:
13,202. Most pixels remain unknown. Surface and
crown vertices are assistant source-assisted drafts, not independently reviewed
human truth. The three prior ground and canopy mask hashes remain unchanged.
The source image partially overlaps earlier garden imagery; it is not a new
independent blind test. All three Alton views are grouped for head holdouts.

## Actual LiDAR inputs

Matched EA National LIDAR DTM and last-return DSM pairs were acquired for both
parks, on identical native one-metre British National Grid rasters and ODN
heights:

- Alton Towers: survey P_10682, 5 January 2022, tile SK0540.
- Chessington: survey P_12756, 16 January 2023, tile TQ1560.

The actual exported aerial extents, rather than just requested imagery bounds,
are covered. An initial crop missed the east edge of the square image export;
the crop was extended before final input generation, affected checkpoints were
invalidated and refitted, and retained checkpoints had unchanged source lineage.
The four images have zero pixels outside the final native LiDAR raster extents.
Valid height neighborhoods cover 99.62% of Towers Street, 92.20% of the earlier
garden image, 99.64% of Chessington and 94.08% of the new garden image. Native
surface gaps are preserved, not interpolated or interpreted as flat paths.

Four fields are computed at original resolution before nearest-cell sampling to
the aerial grid: DSM minus DTM height (clipped at 30 m), terrain slope magnitude,
three-metre surface-height roughness (clipped at 5 m standard deviation), and a
valid DTM/DSM neighborhood flag. Source pins, dates and the retained OSTN15 grid
are recorded. The best available horizontal transform has stated accuracy of
one metre. Fine image pixels do not become fine LiDAR measurements.

These are **LiDAR-derived raster features**, not raw point-return density or
proof of paving below trees. Raw point-cloud products are advertised but are not
used in this experiment. Low grass and low paving can have similar height;
height supports RGB interpretation and never creates semantic labels. Survey
and aerial epochs differ, so heights do not override user boundaries. No-data
features carry a missingness flag; LiDAR models also use 15% modality dropout.

## Fixed training and holdouts

The comparison uses the same 400-step, seed-137 CPU schedule, four samples per
batch, 96-pixel patches, two threads and learning rate 0.002. All heads share
balanced cross entropy, labelled-interface weighting and soft Dice, with separate
canopy loss. The aerial model uses RGB plus thirteen frozen FLAIR probabilities;
LiDAR models add four height/context fields. The larger input stem means this is
not a capacity-matched comparison. The encoder stays frozen.

`lidar_narrow` gives eligible local narrow-paving anchors a 50% sampling chance.
A metric disk identifies labelled strips narrower than roughly four metres,
using projected image sampling. These are sampling estimates, not surveyed
widths or new labels, and include some clipped corners. Prior examples remain
in replay fitting. Default training retains its previous sampling behavior.
No checkpoint or hyperparameter is selected using the held-out scores.

Same-park overlapping views stay in one group. The 24 m context guard applies
across training/test parks; their closest known labels are about 211 km apart.
Within-park distances and source overlap are retained explicitly. Holding out
Alton excludes all three Alton images, including the new narrow-path example.
This is a two-park development comparison, not an independent blind evaluation.

| Park-held-out image | Variant | Paving IoU | Structure IoU | Grass IoU | Water IoU | Canopy IoU |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| user-towers-mutiny | aerial_balanced | 66.87% | 75.11% | 0.00% | 0.00% | 26.40% |
| user-gardens-lake | aerial_balanced | 72.46% | 7.38% | 0.00% | 0.00% | 29.44% |
| user-tight-gardens | aerial_balanced | 25.88% | 5.53% | 0.00% | — | 61.43% |
| user-towers-mutiny | lidar_balanced | 68.72% | 79.08% | 0.00% | 0.00% | 54.71% |
| user-gardens-lake | lidar_balanced | 67.08% | 7.95% | 0.00% | 0.00% | 34.74% |
| user-tight-gardens | lidar_balanced | 28.64% | 16.35% | 0.00% | — | 61.58% |
| user-towers-mutiny | lidar_narrow | 69.56% | 81.12% | 0.00% | 0.00% | 41.29% |
| user-gardens-lake | lidar_narrow | 69.38% | 7.05% | 0.00% | 0.00% | 36.74% |
| user-tight-gardens | lidar_narrow | 15.68% | 18.40% | 0.00% | — | 71.45% |
| user-chessington-courtyard | aerial_balanced | 83.68% | 71.66% | — | — | 32.61% |
| user-chessington-courtyard | lidar_balanced | 33.35% | 43.34% | — | — | 33.59% |
| user-chessington-courtyard | lidar_narrow | 81.05% | 73.48% | — | — | 32.48% |

LiDAR changes paving, structure and canopy performance, with the exact results
above. Gains are mixed across images. Targeted narrow sampling helps some
classes while harming some paths, and is not an overall winner. Missing grass/water labels in Chessington
fitting still prevent reliable Alton transfer for those classes. No-data support,
source age and one-metre resolution also limit tight-edge accuracy.

## Local path checks

Five source-defined visible path corridors test connection retention; two local
corridors test false bridges across explicit grass. Those paths may connect
elsewhere in the garden, so the negative test is local rather than a global
component-separation claim. Endpoints are supported by known paving, with less
than one clean pixel of adjustment in this run. Unknown edges are not promoted
into positive path truth.

| Scope | Variant | Visible paths connected | False local grass bridges |
| --- | --- | ---: | ---: |
| park_holdout | aerial_balanced | 1/5 | 0/2 |
| park_holdout | lidar_balanced | 2/5 | 0/2 |
| park_holdout | lidar_narrow | 0/5 | 0/2 |
| fitted_not_validation | aerial_balanced | 2/5 | 0/2 |
| fitted_not_validation | lidar_balanced | 4/5 | 0/2 |
| fitted_not_validation | lidar_narrow | 5/5 | 0/2 |

The frozen prior model and all revised-model path counts are in the local
report. Fitted previews have seen this example and are not validation. Holding
out Alton excludes this image entirely. Narrow sampling is not consistently
better than the ordinary LiDAR head. Passing separator tests alone
is insufficient: predicting no paths would also avoid false bridges. All class,
partial-boundary, intrusion, connection and probe-support scores are retained.
Zeroing the four height channels changes model predictions, confirming sensor
input use; that ablation is a same-checkpoint diagnostic, not a newly trained
control or independent validation.

## Checks, source and reproduction

Ninety-one relevant tests passed, including nodata preservation, relative heights,
native-cell sampling, physical-width sampling, local versus global connections,
20-channel training and safe reloads. Both datasets reproduce exactly. All four
numeric LiDAR feature grids reproduce exactly. Twelve final checkpoint/image
pairs reproduce both output masks (24 exact checks). The three prior masks are
preserved. Browser comparison checks and the archive SHA manifest accompany the
package. No Windows executable, world blocks or accepted geometry is generated.

Nine completed comparison/final heads are retained, CPU only. The last resumed
invocation took 418.93 seconds and peaked at
1175.2 MB RSS, reusing 3 compatible checkpoints;
that timing excludes earlier work and superseded crops/labels. After the user
confirmed the circle as a structure, the three heads fitted only on unchanged
Chessington targets were reused with verified identical masks and six heads
using Alton targets were refitted. The confirmation ledger is retained. No GPU was used.
The pinned RGB production checkpoint remains unchanged. The source remains a
small, provisional four-image/two-park dataset.

The [FLAIR aerial encoder](https://huggingface.co/alanoix/segformer_b0_flair_one)
and its stricter NVIDIA upstream licence remain non-commercial research and
evaluation only. Runtime uses safe tensors and no remote code or pickle. The
new main ZIP omits the common encoder weights to keep downloads manageable;
use `Aerial-Encoder-Research.zip`, or reuse the identical `aerial-encoder` folder
from the previous layered benchmark package. Both artifacts retain source cards
and the full licence. The main ZIP includes completed head weights, all images,
LiDAR GeoTIFFs, datum grids, exact labels, source code patch and receipts.

Install the full repository at this revision with `.[aerialsegmentation]`, then
from the extracted package (with the common encoder folder present):

```bash
python -m voxel_mapper.connected_surfaces --examples inputs/examples.json --recipe surface-recipe.json --output rebuilt-source
python -m voxel_mapper.layered_surface_benchmark --source-dataset rebuilt-source --examples inputs/examples.json --recipe layered-recipe.json --output rebuilt-dataset
python -m voxel_mapper.lidar_surface_features --dataset rebuilt-dataset --pairs lidar --output rebuilt-lidar-fields
python source/scripts/train_layered_surfaces.py --dataset rebuilt-dataset --encoder aerial-encoder --lidar-cache rebuilt-lidar-fields --profile narrow_lidar --output fresh-training
```

The large frozen-feature cache is recomputed when omitted. The package retains
original experiment feature receipts and a separate coverage audit; an extra
coverage QA field in a fresh receipt can change metadata hashes without changing
numeric grids. Exact array reproduction and saved-checkpoint prediction reloads
are verified, not byte-identical refitted metadata on every platform.

Imagery: Esri World Imagery and its providers. LiDAR: Environment Agency,
OGL-UK-3.0, with EA attribution and original source receipts retained. Marked
references: user-provided. No independent surface review has been received.
