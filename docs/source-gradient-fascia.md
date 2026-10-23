# Original contrast fascia evidence

The [adjoining-roof review](pyramidal-roof-junctions.md) retained a missing
ink-235 support hold. A complementary local-contrast recipe now recovers the
visible fascia edges at both original ink thresholds and both contrast cutoffs.
It produces 42 conditional roof/observed-face inspection variants, with six
level/orientation groups supported across all four source configurations.
The original literal-column results and their holds remain unchanged.

## Why the literal column was held

At ink 220, an original east-crop column at x=294 contains a short run from rows
437–462. At ink 235, the grey background joins it into a much longer original
ink run, approximately rows 406–557. The preceding extractor correctly refuses
to call that whole long run a short fascia end. Other corner columns also merge
with background artwork. The original whole-source data is not clipped to the
predicted roof corner, and its threshold is not loosened.

Inspection of the checksum-verified PDF finds raster artwork at these corners,
not a native vector fascia rectangle. The new extractor therefore measures local
contrast directly from the unchanged original crop:

```
original centre grey < ink threshold
AND max(original left grey, original right grey) - original centre grey
    >= contrast cutoff
```

Ink thresholds remain 220 and 235. Contrast cutoffs are 32 and 64 grey levels.
All three pixels must be in the original raster and outside the source exclusion
mask. Flat grey background is ink at the higher threshold but has no supporting
local contrast. A single dark centre pixel can have strong neighbour contrast
even when its central Sobel response is zero. No smoothing, inferred edge pixels,
paint substitution, background removal or threshold adjustment is used.

Before any roof prediction, each whole eligible original column is partitioned
at gaps greater than two rows. Groups need at least 16 actual pixels and a span
of 16 to less than 64 rows. Runs touching the crop's top or bottom are held;
outermost columns cannot use invented neighbours. Every original centre/left/
right grey value and contrast difference is retained, as are missing row
intervals. No gap is filled or run clipped to fit a target.

The four configurations retain 116, 54, 118 and 54 column groups, respectively,
with 12,710 original pixel triplets overall. Their shared pixels are not
independent controls. Existing original slope groups, plan projections, local
corner tolerances and source-level bindings are reused without changing their
source coordinates or original failures.

## Conditional roof and strip support

The pass retains all 86 original east gable alternatives through the four source
configurations, 344 original slope/corner checks and 70 local column/corner
checks. Fourteen supported paired endcap receipts yield 42 level/orientation/
source variants. Equal-height witnesses retain every source receipt; there is
no residual ranking, averaging or nearest-column choice.

The unchanged 56 unassigned west silhouettes provide 4,704 comparisons with both
side assignments: 2,688 agree and 2,016 remain held. Common printed datum,
orthographic projection and physical correspondence are still assumptions;
these are related project drawings, not independent survey observations.

All six printed-level/orientation groups have support at 220/32, 220/64,
235/32 and 235/64. All 111 cross-configuration comparisons agree within four
nominal source pixels for roof heights and observed fascia depths. This is
source consistency for the new recipe. It does not rewrite the original binary
hold or authorize physical/world acceptance.

Original plan corners and apex supply roof XY. Relative to printed Preshow Top
Level 183.30, apex candidates are approximately 8.200714–8.209805 m high. The
first observed contrast pixels give eave candidates approximately 5.664227 m
above that reference. These are source-pixel measurements, not surveyed roof
levels. Compared with the preceding literal-column method, the new column starts
refer to different original pixels; earlier models remain separate and unchanged.

The strip preserves separate observed bottom endpoints and depths, approximately
0.58918 m and 0.61367 m. Equal depth is not imposed. The first and last eligible
contrast pixels remain proxies for physical fascia corners. A linear top/bottom
edge plane, continuous triangular surfaces and physical roof/fascia roles remain
explicit assumptions.

## One observed edge, with no depth transfer

The unchanged finite symbol aim enters the original pyramid perimeter at one
edge interior. All original finite segment/edge intersections are retained.
Starts inside the polygon, vertex entries, missing intersections and competing
first entries remain held. No diagnostic ray is lengthened to obtain a face.

For the east source, the observed perimeter edge has source ID
`4f447d70e872cce10d99bbd582b93c3eab99b15bae117a6b64e27d62869ab253`.
The shared cap has source ID
`be36604afd7b4114da4014ad0a26873113da13fc834ddf749ba502782a0d09ce`.
They are opposite edges of the original source graph. The visible fascia depth
therefore cannot be transferred to close the shared-cap junction.

Each new inspection asset contains the five roof vertices plus two observed
fascia-bottom vertices: seven vertices and six triangles. Exactly two triangles
form a strip on the one observed edge. There are no strips on the other three
edges. Top corners are shared exactly with the original roof mesh.

All 1,344 comparisons against the previous 32 gable patches retain an open join.
Minimum sampled gaps are approximately 0.579372–0.590866 nominal metre under the
new source-pixel measurements. The two-roof scene has thirteen vertices and ten
triangles: eight roof triangles plus two observed-face fascia triangles.
Three dashed lines measure the open shared-cap gap and add no mesh faces.

No shared-cap wall, fascia closure, watertight building, accepted physical
component, world block or training label is produced. Earlier source holds,
original rail tails and all preceding roof models remain unchanged. The semantic
ranker is untrained. The next source work is to bind evidence for the shared-cap
face itself and recover its actual wall/fascia interfaces before assembly and
world registration can be accepted.

## Replay and review

The same four checksum-verified PDFs and source packs are used; no new acquisition
was necessary. The builder freshly replays the preceding pyramid chain before
and after generation, pins source/crop inputs, and refuses changed saved output.
The source fixture uses 19,364 of the fixed 100,000 charged-check budget. Work or
source overflow clears every partial view, face, measurement, comparison and
model. Bounds include 2,048 columns per configuration, 256 inspection models,
8,192 stability comparisons and 64 MB compact output.

```sh
python -m scripts.build_pyramid_fascia_evidence \
  --pyramid /path/to/pyramid-review --preshow /path/to/preshow-level-review \
  --references /path/to/reference-review --topology-source /path/to/topology-review \
  --gradient /path/to/gradient-review --components /path/to/components \
  --views /path/to/views --corpus /path/to/original-corpus \
  --source-catalogue examples/wicker-preshow-reference-catalogue.json \
  --additional-pdfs /path/to/preshow-originals --output /path/to/output
```

`python -m scripts.audit_pyramid_fascia_evidence` takes the same source arguments,
`--evidence` and an `--output` receipt path. It replays the new pass, runs the
independent parent audit and separately reconstructs complete contrast-column
indices from original pixels/masks. It checks every original neighbour triplet,
finite observed-edge entry, endcap witness, cross-view comparison, roof/strip
mesh, configuration comparison and shared-cap transfer hold.

```sh
python -m scripts.export_pyramid_fascia_models \
  --evidence /path/to/output/contract-hash --output /path/to/obj
python -m scripts.render_pyramid_fascia_evidence \
  --evidence /path/to/output/contract-hash --pyramid /path/to/pyramid-review \
  --preshow /path/to/preshow-level-review --references /path/to/reference-review \
  --views /path/to/views --objs /path/to/obj --output /path/to/review.html
```

The offline review embeds the unchanged plan/elevation images, current and parent
evidence, and all 42 exact OBJ exports. It exposes both contrast cutoffs, every
original east pair/level state, the original symbol diagnostics and west source
alternatives, source failures, four-configuration coverage and the unclosed join.
OBJ files preserve nominal local metres, Z up, with exact double round trips.
Source PDFs are not redistributed. Validation receipts and the compressed full
suite log are under `docs/evidence/source-gradient-fascia/`.

Validation: **1,791 full-suite tests pass** in 1023.837s,
including eighteen new focused regressions. Browser review passes
1979 states, all 516 east pair/level/contrast states, all 42
model OBJ exports, 1,344 open-scene states, 42 exact scene downloads, all 4,704
cross-view records, five source image hashes and exact JSON export, with zero
JavaScript errors.
