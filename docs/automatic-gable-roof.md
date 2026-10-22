# Automatic pitched-roof hypothesis and gable checks

The new downstream pass builds a provisional pitched main roof from original
roof-plan lines and the recovered NW long-elevation panel. It checks the resulting
model against separate raster slopes in all four numbered Shop elevations. No
manual roof trace, literal component ID, supplied depth/pitch, per-view crop box
or old manually reviewed roof model supplies extraction inputs.

```sh
python -m scripts.build_automatic_gable_roof \
  --profile PROFILE_PACK --preview PREVIEW_PACK --components COMPONENT_PACK \
  --views VIEW_PACK --corpus CORPUS --output output/gable-roofs
python -m scripts.audit_automatic_gable_roof \
  --gable GABLE_PACK --profile PROFILE_PACK --preview PREVIEW_PACK \
  --components COMPONENT_PACK --views VIEW_PACK --corpus CORPUS \
  --output output/gable-roof-audit.json
python -m scripts.render_automatic_gable_roof \
  --gable GABLE_PACK --profile PROFILE_PACK --preview PREVIEW_PACK \
  --components COMPONENT_PACK --views VIEW_PACK --output output/gable-roof.html
```

Follow the [source façade profile guide](automatic-facade-profile.md) to prepare
the preceding packs from the same three verified originals. `GABLE_PACK` is the
hash-named directory reported by the build command. Its `gable-roof-review.json`
retains every source line, pixel, fit, alternative gable and model check. The HTML
embeds five untouched source crops and exports a conditional OBJ with the same
six vertices and four triangles displayed in the review. It works offline.

## Roof dimensions before gable checking

A source cohort supplies the candidate upper-panel eave above the fascia.
The pass groups the preceding roof mask's tall, narrow closed white regions by
their exact original top/bottom grid coordinates. Regions must be at least 24
pixels high and at most 16 wide. One unique cohort must have at least six members,
at least half the eligible regions, and span at least half the recovered roof
width. These roles and dimensions are determined before gable measurements.

On Wicker, 159/192 original regions at thresholds 220/235 share rows 343–468.
The source ridge grid edge is at row 342. The long-view dimensions are:

| Source quantity | Nominal drawing result |
| --- | ---: |
| Longitudinal roof span | 16.892943 m |
| Ridge above printed Shop Level | 7.256110 m |
| Upper-panel eave above printed Shop Level | 3.534938 m |
| Rise from panel eave to ridge | 3.721173 m |

The fixed non-Shop layout relation transfers only the original facing-frame
axis into the roof plan. It is not refitted. Whole original straight unclipped
roof-plan line components are retained when their direction is within five
degrees of that axis, their length agrees with the recovered roof span within
0.25 nominal m, and their transverse drift stays within 0.25 nominal m.

Every eligible triple is tested. The three original along-axis intervals must
agree within 0.25 nominal m. Transverse spacings must each be at least one metre,
total depth at most 40 m, and their difference at most 0.25 m. No line endpoint is
moved. A source endpoint determines each transverse offset; no midpoint or
symmetrized ridge is substituted. Multiple triples remain alternatives.

Wicker has three unique eligible original lines, each about 16.84 nominal m long.
Their aligned source positions supply two runs of **6.408910 m** and **6.405913 m**,
for a **12.814823 m** depth. Their eave/ridge roles remain hypotheses. Two source
height witnesses retain the same triple and yield one distinct roof geometry.

The model assumes constant longitudinal ridge and eaves, with continuous roof
planes. It retains the measured transverse ridge offset, about 0.001499 nominal m
from the centre, without interpreting that tiny source difference as physical
asymmetry. The resulting pitches are **30.140516°** and **30.152157°**. These are
nominal drawing-derived hypotheses, not surveyed geometry or verified roof pitch.

## Separate raster gable evidence

All four original elevation crops are checked at thresholds 220 and 235.
Retained native components, buffered by 1.5 source pixels, and original native
text boxes, buffered by one pixel, are excluded from raster slope proposals.
Their source records and geometries remain explicit. This raster-only recipe
can exclude a physical native edge too; it makes no claim to recover all native
roof geometry. Source images are never edited.

Original dark pixels with a diagonal Sobel boundary direction supply bounded
Hough proposals from 15–65° in either direction, in 0.5° steps. An orientation
window of 12°, integer normal bins, at least 48 votes and a 5×5 local-maximum
screen bound proposals. All tied maxima survive. Each candidate retains every
eligible original point within 1.5 normal pixels of its Hough seed, with at least
48 points over a 64-pixel horizontal span. Exact duplicate memberships share all
seed receipts; no residual-ranked best line is selected.

Even original columns fit the line; odd original columns check it. Each role
needs at least 16 pixels. All original selected points remain in their assigned
role, and every normal residual must stay within three pixels. No residual
outlier is removed. Missing source-column intervals are recorded without filling
them. These neighbouring-column checks test raster consistency; they are not
independent survey checkpoints.

Opposite-slope pairs propose ridge intersections. A ridge must lie within the
source support ranges, allowing at most 12 pixels at an end, and have at least
32 pixels of source leg width on either side. The intersection is explicitly an
inferred point. No independently measured gable depth or physical eave endpoint
is claimed from these fits.

The already constructed roof is then checked against every source gable pair.
Ridge heights must agree within 0.25 nominal m and both pitches within one degree.
The model is never refitted to pass a check. Wicker retains **80 slope candidates**,
**223 gable pairs** and **446 model/gable comparisons** across the two source
height witnesses. **28 comparisons agree**; all disagreements remain available.
These are competing edge/fascia alternatives, not 223 independent real gables.

The SW elevation supplies agreeing checks at both thresholds and has a source
frame perpendicular to the long façade plus a passing fixed target-annotation
check. The NE elevation agrees dimensionally, while its source frame/target
orientation link stays held. It contributes a check only, not placement authority.
The NW crop retains three unpaired visible slope candidates per threshold near
the adjacent small gable. Its missing opposite side, depth, complete silhouette
and building association remain unresolved; it is not added to the main roof.
The SE crop supplies no eligible diagonal slope in this recipe.

## Provisional 3D scope

The output is a real pitched 3D roof hypothesis with six vertices and four
triangles, in nominal local metres above printed Shop Level. It contains no wall,
fascia, material assignment, cut opening, geographic transform or accepted ODN
floor level. Both original long-view thresholds yield the same geometry; their
evidence remains separate.

Continuous planes are an explicit model assumption. The earlier source masks
keep every original raster hole and callout gap unchanged. Those uncertain gaps
are not incorporated as physical roof apertures, and the template does not
replace or repair the preceding source-cell meshes. Physical roof/line/gable
identity, source construction state (`unspecified`), scale and registration remain
unverified. Accepted physical components, world blocks and training labels remain
zero; the semantic ranker remains untrained. No new portal acquisition or gameplay
is claimed.

Next work is the adjacent wing's complete source correspondence, the remaining
wall and fascia surfaces, aperture/floor roles and eventual park registration.
The new roof alone is not a complete automatically reconstructed Shop building.

## Verification and limits

The pass reproduces the complete preceding profile and preview, checks all source
masks and original crops, and binds original PDF/view/component hashes before and
after work. Its contract pins implementation/dependency hashes, the full preceding
profile contract and the work limit. Saved output must match a fresh calculation.

Bounds include eight long profiles, sixteen elevation views, six million pixels
per crop, 4,096 native components, 10,000 original text traces, 65,536 eligible
edge pixels per raster, 256 Hough peaks, 8,192 pixels per line, 128 fitted lines,
512 gable pairs per variant, 64 eligible parallel plan lines, 128 triples/models,
100,000 work checks and 64 MB output. A budget hold discards all partial heights,
lines, triples, gable checks and models; it does not publish a partial best fit.

The independent audit decodes the original PDF plan strokes, checks every source
raster point and its fixed role, solves each regression through a separate
covariance formula, and verifies every Hough seed's original point membership.
It solves intersections through a separate linear system, reconstructs source
plan offsets and every roof vertex/pitch, and independently checks all gable
comparisons, perpendicular frame links and target-annotation holds.

Thirteen new regressions cover source cohort ambiguity, original line lengths,
alignment/spacing/curve holds, native text/vector exclusions, source-pixel roles
and gaps, inferred intersections, unequal roof runs, invalid dimensions,
work/source budgets, original-PDF replay, changed sources, cache tampering and
independent source-line/mesh auditing.

The final local suite passes **1,687 tests**, including thirteen new
regressions. The source-profile audit passes and all fourteen upstream hashes
reproduce. The gable audit checks 10,474 original slope pixels, 80 fit/check
solutions, 223 intersections, two models and all 446 comparisons. Browser checks
cover 40 interaction states, five source images and an exact six-vertex/four-
triangle OBJ download with zero JavaScript errors. Receipts are in
`docs/evidence/gable-roof/`.
