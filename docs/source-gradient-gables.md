# Original grayscale gable evidence and plan-direction ambiguity

This complementary pass recovers bright, partly visible diagonal strokes directly
from original grayscale gradients. It checks the new short-edge evidence against
the unchanged long-edge anchors from both preceding ink thresholds, then reviews
source plan directions under the fixed artwork relation. No manual trace,
literal source ID, supplied pitch/depth, crop window or old manually reviewed
model enters extraction. The preceding binary-threshold result and main roof
remain unchanged.

```sh
python -m scripts.build_source_gradient_gables \
  --source-partial PARTIAL_PACK --gable GABLE_PACK --profile PROFILE_PACK \
  --preview PREVIEW_PACK --components COMPONENT_PACK --views VIEW_PACK \
  --corpus CORPUS --output output/source-gradient-gables
python -m scripts.audit_source_gradient_gables \
  --gradient GRADIENT_PACK --source-partial PARTIAL_PACK --gable GABLE_PACK \
  --profile PROFILE_PACK --preview PREVIEW_PACK --components COMPONENT_PACK \
  --views VIEW_PACK --corpus CORPUS --output output/source-gradient-audit.json
python -m scripts.render_source_gradient_gables \
  --gradient GRADIENT_PACK --source-partial PARTIAL_PACK --gable GABLE_PACK \
  --views VIEW_PACK --output output/source-gradient-gables.html
```

Prepare the preceding packs using the [partial-gable guide](automatic-partial-gables.md).
`GRADIENT_PACK` is the hash-named build directory. Its `source-gradient-gables.json`
retains every source pixel, fit/check role, seed/group receipt, candidate,
comparison, plan line and projection diagnostic. The offline HTML embeds six
untouched original crops and exports the complete evidence JSON. No new wing
mesh or wing OBJ is produced.

## Complementary grayscale recipe

The source partial-gable review is freshly reproduced through its complete
roof/profile/preview chain. Original PDF, raster, report and profile-mask pins
must match. Native/vector/text exclusions remain unchanged; as before, a
raster-only exclusion can also hide a physical native edge.

The preceding pass used Sobel derivatives of a binary ink mask. This pass uses
Sobel derivatives of the **untouched original uint8 grayscale**, without smoothing.
Pixels must have an original intensity below 250 and gradient magnitude of at
least 32 or 64, in separate source variants. The near-white foreground ceiling
remains fixed at 250; this is a bounded case-study recipe, not a claim that all
image-parameter variation or other parks have been validated. Gradient units are
raw Sobel response units for the 8-bit source, not physical contrast or metres.

The original 15–65 degree slope eligibility, 0.5 degree Hough steps, 12 degree
orientation window, 1.5 normal-pixel membership band, 16 minimum votes and tied
5×5 maxima remain. Whole original seed memberships split on column steps greater
than four **before fitting**. Each local group needs at least 24 original points,
a 24–63 pixel horizontal span and eight points per fixed role. Even original
columns fit; odd columns check. Every selected point stays in its role, no
residual outlier is removed, and all normal residuals must stay within three
pixels. Gaps remain recorded and unfilled. These neighbouring-column checks
measure raster consistency, not independent survey accuracy.

Each grayscale variant is compared separately with the previously unpaired long
anchors at **both unchanged parent ink thresholds, 220 and 235**. The long anchor
is never refitted. Every eligible intersection remains available, including the
failed support-end and two-degree pitch checks from the preceding recipe.

Conditional pairs compare across the two gradient cutoffs with each parent
anchor fixed. A separate comparison checks the two parent anchors at each
fixed gradient cutoff. Ridge separation must stay within four source pixels and
left/right apparent pitch differences within two degrees. All failed comparisons
remain explicit. Pixel memberships can overlap, and the two parent-anchor checks
reuse the same grayscale short-edge evidence. They are not independent survey
controls or proof of a unique physical correspondence. The view-level status
means each fixed parent anchor has some pairwise support across both contrast
cutoffs; it does not select one common physical winner.

The old binary-threshold hold is **not overridden**. The new pass supplies a
complementary source-consistency result, not a retroactive pass for the old recipe.

## Original plan directions and conditional pitch

Every whole straight, unclipped two-point plan line of at least one nominal
metre contributes an untouched source receipt. Curves and longer polylines do
not supply these direction witnesses. Directions are grouped into rounded
one-degree bins modulo 180. A repeated cohort needs at least three members.
All lesser-supported cohorts remain held in the output. The lexically first
original source component supplies the direction witness, before any gable
comparison; points and directions are never averaged or fitted to the gable.
Hatching and other line semantics remain unresolved, so a repeated direction is
not classified as a roof edge or gable-width axis.

The existing non-Shop artwork controls transfer only source directions. A
projection context requires an original facade frame and a passing fixed target
annotation check. The new pass does not refit the layout relation or apply a
plan translation. Every eligible floor/roof direction pair remains in the
comparison set; agreement within one degree does not establish a building match.

For every conditional gable and repeated roof direction, let `f` be the absolute
dot product of the source view's horizontal axis and the original plan direction.
**If** the gable width follows that direction and the ridge is perpendicular to
it, the conditional true-pitch diagnostic is:

`atan(tan(apparent_source_pitch) * f)`

This assumed orthographic gable template is diagnostic only. Directions within
five degrees of edge-on withhold pitch. Neither a physical width axis, true pitch,
ridge orientation, eave endpoint nor depth is established. For example, an
apparent slope around 39 degrees can correspond to a pitch around 30 degrees
under an oblique plan direction. A face-on hypothesis retains the apparent angle.
The pass preserves both possibilities; it cannot attach the visible gable to a
specific structure from direction agreement alone.

## Wicker result

| Original elevation | Gradient cutoff | Short strokes | Parent 220: partial / conditional | Parent 235: partial / conditional |
| --- | ---: | ---: | ---: | ---: |
| SE | 32 | 95 | 0 / 0 | 0 / 0 |
| SE | 64 | 85 | 0 / 0 | 0 / 0 |
| NW | 32 | 149 | 77 / 10 | 78 / 10 |
| NW | 64 | 138 | 86 / 13 | 86 / 13 |
| SW | 32 | 452 | 56 / 0 | 0 / 0 |
| SW | 64 | 427 | 56 / 0 | 0 / 0 |
| NE | 32 | 132 | 0 / 0 | 0 / 0 |
| NE | 64 | 121 | 0 / 0 | 0 / 0 |

There are **1,599 grayscale stroke alternatives**, **87,262 original pixel
memberships**, **1,652 whole Hough group receipts** and **439 inferred partial
intersections**. Forty-six NW intersections pass local checks conditionally;
393 interpretations remain held. These overlapping alternatives are not
independent real strokes, buildings or physical uncertainty bounds.

The NW source has pairwise support across both gradient cutoffs with each fixed
parent anchor. **252 of 260** contrast comparisons agree; **259 of 269**
parent-anchor comparisons agree. The eight contrast disagreements and ten
anchor disagreements remain visible. No other elevation has conditional support
under this recipe. The old binary-threshold result still has no view supported
at both original ink thresholds.

The plan review verifies **2,695 original native line receipts**, with **24
repeated direction cohorts**: six floor and eighteen roof cohorts. Four source
projection contexts survive: one SE, two SW and one NW. The NE frame stays held.
All **432 floor/roof direction checks** remain; **24 agree**. The NW conditional
intersections produce **828 pitch-projection diagnostics**, including **46
edge-on pitch holds**. This is direction evidence, not a wing footprint or
building identity match. Several orientations remain plausible.

Wing eaves, source construction state, true pitch/orientation, full silhouette,
independent plan depth and physical building correspondence remain unresolved.
There is no new wing/wall/opening mesh, source-mask repair, accepted component,
world block or training label. The main roof is unchanged; the semantic ranker
remains untrained. Same three originals; no new portal acquisition, gameplay,
merge or deployment is claimed.

## Verification and bounds

The contract binds implementation/dependency hashes, the source partial-review
hash and contract, and work budget. Fresh replay must match saved output. Original
PDFs, crops, profile masks and all source reports are checked again before return.
Any work or source budget hold discards every partial grayscale, direction and
projection review; it does not publish a best subset.

Limits include sixteen elevation views, six million pixels per source and a
3,000-pixel maximum dimension, 65,536 eligible pixels, 2,048 Hough peaks, 1,024
pixels and 1,024 short candidates per variant, 128 parent long candidates, 512
parent pairs, 2,048 partial pairs per anchor/contrast variant, 4,096 comparisons
per comparison family, 4,096 native components per plan inventory, 128 source
projection contexts, 8,192 direction comparisons and 8,192 pitch diagnostics,
100,000 work checks and 64 MB JSON/HTML outputs. A direction bin is evidence
organization only; it neither snaps nor moves original endpoints.

The independent audit recomputes original grayscale gradients, every eligible
source membership/role and whole Hough group, uses a separate covariance
regression and 2×2 intersection solve, checks every source comparison and decodes
all original plan strokes from the checksum-verified PDFs. It independently
inverts the fixed layout matrix, checks every source frame/direction comparison,
and verifies all conditional pitch diagnostics through a separate sine/cosine
formula. The preceding partial-gable audit also checks the unchanged old evidence.

Twelve regressions cover bright-edge recovery at both contrast levels, original
pixels/roles, source gaps/exclusions, white-background exclusion, invalid inputs
and budgets, target-independent direction roles, curves/short-line holds, oblique
and edge-on projection, failed/shared-source comparisons, all direction
alternatives, target-frame holds, unchanged parents, late/early discard,
source/cache tampering and independent original-source replay.

Next: establish the gable's physical plan/building correspondence, recover eaves
and depth from that source, and only then construct a conditional wing mesh.
Source consistency and a possible deprojected pitch cannot authorize that mesh.

The final local suite passes **1,711 tests**, including twelve new
regressions. Both original-source audits pass. Browser checks cover all 439
partial pair options, 503 source states and 149 plan/frame states,
with six original image hashes, exact points/roles/native endpoints, holds and
JSON export verified, and zero JavaScript errors. Receipts and compressed
full-suite log are in `docs/evidence/source-gradient-gables/`.
