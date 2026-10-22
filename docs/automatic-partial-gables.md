# Short source strokes around partially occluded gables

This downstream pass recovers short diagonal source strokes that the preceding
[automatic pitched-roof pass](automatic-gable-roof.md) deliberately excludes.
It pairs them with previously unpaired long slopes and retains all eligible
intersections, including failed checks. It does not complete an occluded roof.
No manual trace, literal view/component ID, supplied pitch, depth or crop window
enters extraction. The original four elevation crops are scanned at both source
thresholds; the main roof and all preceding evidence remain unchanged.

```sh
python -m scripts.build_automatic_partial_gables \
  --gable GABLE_PACK --profile PROFILE_PACK --preview PREVIEW_PACK \
  --components COMPONENT_PACK --views VIEW_PACK --corpus CORPUS \
  --output output/partial-gables
python -m scripts.audit_automatic_partial_gables \
  --partial PARTIAL_PACK --gable GABLE_PACK --profile PROFILE_PACK \
  --preview PREVIEW_PACK --components COMPONENT_PACK --views VIEW_PACK \
  --corpus CORPUS --output output/partial-gable-audit.json
python -m scripts.render_automatic_partial_gables \
  --partial PARTIAL_PACK --gable GABLE_PACK --views VIEW_PACK \
  --output output/partial-gables.html
```

Follow the preceding guide to reproduce `GABLE_PACK` from the same three
checksum-verified original PDFs. `PARTIAL_PACK` is the hash-named build directory.
Its `partial-gables.json` retains original source pixels, their fixed fit/check
roles, whole Hough seed/group receipts, gaps, fitted lines, inferred intersections
and every retained check. The offline HTML embeds four untouched original crops,
shows all alternatives and exports the complete evidence JSON. There is no new
wing mesh or wing OBJ.

## Source recipe

The parent review is freshly reproduced through its complete profile/preview
chain. Original PDFs, source crops, reports, masks and output hashes must match.
The short pass inherits the parent's native/vector/text exclusion mask without
editing a source image. As before, raster-only exclusions can also hide a
physical native edge; this is not a complete native-and-raster roof extractor.

The same diagonal Sobel eligibility, 15–65 degree directions, 0.5 degree Hough
steps, 12 degree orientation window and 1.5 normal-pixel membership band apply.
A separate short-edge recipe requires 16 Hough votes. Every tied 5×5 local
maximum remains eligible. Whole seed members are sorted by original column and
split wherever adjacent supported columns differ by more than four pixels,
**before fitting**. This partitions source support; it neither fills a gap nor
extends a dark-pixel corridor.

Each retained whole local group has at least 24 original points, a horizontal
span of at least 24 and less than 64 pixels, and at least eight points in each
fixed role. Even original columns fit; odd columns check. Every selected point
remains in its role; no residual outlier is removed. Every normal residual must
stay within three source pixels. Exact duplicate memberships retain all Hough
seed receipts. Missing column intervals remain explicit. These checks measure
raster consistency, not independent survey accuracy or physical roof identity.

Only long lines with no eligible gable pair in the **preceding recipe at the same
threshold** supply anchors. This means "previously unpaired" is an algorithmic
status, not proof of a missing physical roof side. Each opposite-slope short
candidate is considered. Ridge intersections must lie within source support
intervals plus a twelve-pixel allowance, with a separation of at least 32 pixels
from each outer support end. All intersections meeting this gate remain in the output.

Two checks distinguish conditional partial support from a held interpretation:
the inferred intersection must be within twelve pixels of both visible support
ends, and pitch magnitudes must differ by at most two degrees. In particular,
an intersection through the interior of a long stroke remains held. Similar
pitches are a screening hypothesis only; no symmetric roof is constructed.
The long source line is never refitted to the short candidate.

Conditional pairs at both thresholds are compared by a ridge separation of at
most four source pixels and left/right pitch differences of at most two degrees.
All such comparisons remain available without selecting or refitting a winner.
If either threshold lacks a conditional pair, stability is explicitly unestablished;
it is not asserted as a measured dimensional contradiction.

## Wicker result

| Original elevation | Threshold | Short strokes | Partial intersections | Conditional alternatives |
| --- | ---: | ---: | ---: | ---: |
| SE | 220 | 13 | 0 | 0 |
| SE | 235 | 19 | 0 | 0 |
| NW | 220 | 7 | 0 | 0 |
| NW | 235 | 38 | 21 | 5 |
| SW | 220 | 136 | 60 | 0 |
| SW | 235 | 198 | 0 | 0 |
| NE | 220 | 25 | 0 | 0 |
| NE | 235 | 43 | 0 | 0 |

The pass retains **479 short-stroke alternatives**, containing **17,683 original
pixel memberships**, and **81 partial intersections**. Five conditional
alternatives lie around the visible NW adjacent gable; the remaining 76
intersections stay held. These counts describe competing source interpretations,
not independent physical strokes or buildings; overlapping memberships can share
source pixels. The 530 retained Hough group receipts include duplicate memberships
with different seeds.

The five NW threshold-235 intersections lie at approximately x=268.11–268.23,
y=388.26–388.35 source pixels. Their nominal ridge heights are 5.8871–5.8900 m
above printed Shop Level. The long-source pitch is about 39.33 degrees; short
alternatives are about 38.97–39.35 degrees. Those narrow ranges describe
algorithmic alternatives, not physical uncertainty bounds or survey precision.

Threshold 220 has no eligible opposite short edge under this recipe. **No view
has conditional support at both thresholds.** The source-threshold hold remains
explicit, and no full gable outline, eave endpoints, independent wing depth or
building association is accepted. The unchanged main-roof model remains separate.
No complete wing, wall or aperture is generated; accepted physical components,
world blocks and training labels remain zero. The semantic ranker is untrained.
No new portal acquisition, gameplay, merge or deployment is claimed.

## Verification and bounds

The contract binds implementation hashes, the preceding gable contract and
review, and work budget. Fresh replay must match saved output; changed original
PDFs, crops, exclusions, reports, profile masks or cached JSON are rejected.
Before return, the pass rechecks all source reports and profile/preview images.
Budgets discard all partial source candidates and intersections; no best subset
is silently published.

Limits include 16 views, six million pixels per raster and a 3,000-pixel maximum
dimension, 65,536 eligible diagonal pixels, 2,048 Hough peaks, 1,024 source points
per local line, 1,024 short lines per variant, 128 preceding long lines, 512
preceding pairs, 2,048 partial pairs per variant, 4,096 threshold comparisons per
view, 100,000 work checks and 64 MB JSON/HTML outputs.

The independent audit reproduces the complete source chain, checks original
image hashes, every selected pixel/role and all 530 full seed/group memberships,
uses a separate covariance regression for each short line and a separate 2×2
linear solve for each intersection, and verifies support-end, pitch, stability
and acceptance holds. The parent audit separately verifies the unchanged
original roof-plan strokes and main-roof geometry.

Twelve regressions cover short-only evidence, original gaps and exclusions,
fixed pixel roles, untouched long anchors, false interior intersections, pitch
failures, prior-pair exclusion, all cross-threshold alternatives and disagreements,
source/work budgets, early/late discard, changed parent/crop/cache rejection and
independent source replay. Browser checks exercise every retained pair option,
both thresholds and all four views, original coordinates/roles, fit spans,
inferred intersections, display toggles, failure visibility and evidence export.

Next: establish robust wing evidence across source variants and its independent
plan correspondence, then recover eaves, depth, wall surfaces and openings.
The five conditional alternatives alone cannot authorize a complete wing model.

The final local suite passes **1,699 tests**, including twelve new
regressions. Both original-source audits and all 113 browser states pass.
All 81 pair choices, four untouched source images, original coordinates/roles,
fit intervals, inferred intersections, held alternatives and JSON export are
verified, with zero JavaScript errors. Receipts and the compressed full-suite
log are in `docs/evidence/partial-gables/`.
