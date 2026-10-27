# Ride reconstruction learning: first source-bound component model

This stage starts a separate ride learning task. It trains new component-class
and source-mask heads using drawings from three rides in three parks. It does not
train complete 3D track or support reconstruction, and changes no world blocks.

## Actual training evidence

The original proposed landscape plan 373/95/7 B is retained at SHA256
`1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`.
Its existing reviewed source markings have SHA256
`fcae6aad3c6c4f7a2c70a68e3a709ff0520c6dfc730eb73e04a1d1f339996659`.
The [public planning attachment](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=176955)
is reference material; public availability is not a blanket reuse license.
Original architect/applicant rights remain, and this package is a local research
source review, not a new open-license ride dataset.

The new review specifies exact selectors into the original source geometry:

| Learning class | Examples | Target |
| --- | ---: | --- |
| Ride track centreline | 24 | Consecutive original vertex spans |
| Ride support footprint | 24 | Original closed footing-mark polygons |
| Ride support cross-line | 24 | Original lines connecting retained footing groups |

The 24 spans reproduce all 428 original route vertices and 427 edges, preserving
their order and open endpoints. They exclude the estimated circuit closure.
The source route measures about 773.57 nominal metres under the retained plan
scale; this is not a new physical survey. Footing symbols are drawing marks, not
measured foundation shapes or sizes. Cross-lines are plan geometry, not verified
3D diagonal members or a guarantee of support-to-track branch assignment.

Support samples are deterministic selections from 877 retained footing symbols
and 502 native cross-lines. They do not add inferred intermediate footings.
The original source-crop and separate-mask gallery was visually reviewed before
training. Native-coordinate selector and geometry hashes are checked on every
export; changed source bytes or invented selectors fail. One PDF-point trace
uncertainty is retained. All inputs are unmarked original page crops, with masks
stored separately. Source render width is 3200 pixels; upsampling small marks
does not supply additional independent detail.

## Model and honest evaluation boundary

The registered CPU MobileNetV2 encoder remains frozen at
`674dc0911a76190cb956be54ab6190b260e9cb5b7ef758a4742cfeeaacdcf6eb`.
Actual class and 16×16 mask heads were fitted with the existing ridge learner,
alpha 100, on all 72 source pairs. The checkpoint, unchanged encoder, license,
provenance and training report are saved together. This fits project heads; it
does not fine-tune the neural encoder or add a reasoning model.

**There is one ride and one source-connected group.** Related crops, overlapping
track spans and all views of this ride remain in that group. The report states
`unassessed_single_source_group`, with no evaluation folds or held-out predictions.
Held-ride accuracy is null. Training loss is a fitting statistic, not quality on
an unseen ride. No random crop split, fabricated independent score or production
promotion is used.

An independent audit reproduced the saved normalization and refitted the fixed
heads from pinned crops/masks with identical parameters. Sixty-three focused local
tests pass, including source binding, closure exclusion, corrupt source/review
rejection, cancellation, grouping and existing track/support checks. These are
engineering checks, not physical reconstruction acceptance or an in-game review.

## Elevation, crossings and LiDAR

The separately retained context contains the 56,568-return EA January 2022 crop
and its verified checksum, attribution, BNG/ODN datum and survey date. It also
retains the existing fourteen HP/LP marker hypotheses and their alternative
branch candidates. Neither becomes fitted height or support truth.

The proposed plan and later LiDAR describe different epochs. Raw classifications
can label track returns as vegetation, and missing returns cannot prove the
absence of lower track. Marker branch assignments, world height interpolation,
clearance corrections, routed transfer members, hidden braces and generated world
variants are excluded from targets. The new model therefore cannot yet infer
correct elevation or safely join supports at crossings.

User material and generation preferences are retained as context: dark oak fence
supports from original brown footprint starts to their corresponding centreline
undersides, increased source-supported density, crossing clearance, and full or
double slabs on steep deck sections. Preferences are distinct from measured
geometry; the new recognizer does not automatically alter a world generator.

## Replay

```sh
python -m voxel_mapper.ride_training build \
  --review evidence/wicker-ride-source-review.json \
  --markings PATH/source-markings.json --sources PATH/original-pdfs \
  --output FRESH-RIDE-DATASET
python -m voxel_mapper.ride_training train \
  --dataset FRESH-RIDE-DATASET --output FRESH-RIDE-MODEL \
  --encoder PATH/mobilenetv2-12-gap.onnx \
  --encoder-sha256 674dc0911a76190cb956be54ab6190b260e9cb5b7ef758a4742cfeeaacdcf6eb
```

The portable bundle includes original PDF/markings, pinned source selections,
crop/mask pairs, context, checkpoint and encoder with attribution. Keep directory
structure when extracting on Windows and run with the project CPU environment.
This stage does not rebuild or install the Windows executable.

## Expansion to other parks and ride types

Following the first Wicker-only run, the dataset was expanded before a separate
fixed multi-ride experiment:

| Ride/site | Type | Reviewed pairs |
| --- | --- | ---: |
| Wicker Man / Alton Towers | Wooden coaster | 72 |
| Dentzel Carousel / Glen Echo Park | Rotating carousel | 10 |
| RU.22/0374 proposed coaster / Thorpe Park | Steel coaster | 14 |

The [Glen Echo source](https://www.loc.gov/item/md1366/) is the HABS mechanical
axonometric, sheet 6, previously excluded from the architectural task. Its new
labels trace projected visible member edges, not complete machinery or 3D
connections. This does not reuse building-envelope labels as ride labels.

The Thorpe source is the official Runnymede 5 October 2022 planning committee
pack, pages 79–80, retained at SHA256
`9941a31ca0ccba828234c806f8c2135b2e6388a5804b7f145acddf585ec98291`.
It supplies eight visible structure traces, four track-profile traces and two
partial layout traces. These are reduced proposed drawings, not precise CAD or
current as-built geometry. The original applicant/architect rights remain; this
is scoped local research tracing, not blanket permission to reuse the pack.
The earlier architectural pilot used the pack as reference only; these new
ride-specific source reviews explicitly add limited drawing-component targets.

The 96-example intake has six classes and three connected groups. All source
views/crops of each physical ride remain together. Fixed leave-one-group-out
evaluation uses three folds, each also holding out a complete park in this
particular collection. Each fold fits its own normalization and heads; the
encoder is unchanged. The final saved checkpoint then fits all 96 examples,
so it has no untouched final-checkpoint test.

The result exposes inadequate coverage: **7/96** component classes correct
(7.29%); **78/96** have a class absent from their fold's training rides. Among
the 18 available-class cases, 7 are correct (38.89%). Equal-ride class accuracy
is 16.67%. Soft mask IoU is 0.02410, below the training-only mean-mask template's
0.02627. Binary mask IoU is only 0.00091. Thin traces are poorly recovered by the
16×16 decoder. No accuracy improvement or autonomous reconstruction is claimed.

All three fold parameter sets, normalization and predictions were independently
reproduced from pinned inputs. The final fitted weights also reproduced exactly.
No reviews, labels or hyperparameters changed after predictions. **64** focused
local engineering tests pass after the multi-ride training guard was added.
The inventory and validation receipts distinguish trained types from pending
water rides, drop towers, other flat rides and transport rides.

Use the portable `multi-ride-replay-request.json` with `study_intake`, then the
same `ride_training train` command on the combined dataset. The CLI accepts
ride-only reviewed intakes and rejects mixtures with architectural classes.

Next, acquire independent ride plans with the same classes and reserve whole
rides for evaluation. For actual 3D learning, add reviewed plan/section links,
height datum and explicit support-foot-to-track-visit bindings, especially at
crossings. The current source-component model is an initial tool for finding
drawing evidence, not a complete ride reconstruction system.
