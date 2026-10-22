# Adjoining pyramidal roof and the open junction

The [preshow partial-roof pass](preshow-level-geometry.md) left two original
0.50376339 m rail tails unmeshed. A new opt-in pass discovers an adjoining closed
four-spoke source graph and measures the shared junction. It produces six
conditional taller-roof inspection variants and a local two-roof review. The
source gap remains open; a complete physical building is not accepted.

## Original graph and tail evidence

Discovery examines all 2,492 eligible original roof-plan strokes before looking
at elevation measurements. Four different corner endpoints must share one exact
original apex endpoint. Four whole original perimeter strokes must connect those
corners, forming a valid convex rectangle-like polygon containing the apex.
Adjacent/opposite directions allow five degrees, with nominal edge lengths
2–40 m. No endpoint tolerance closes a missing stroke: nearly matching coordinates
remain disconnected. Exact duplicate paints share a geometric edge but retain
every original source identity. Connected hatching can still satisfy this
unclassified pattern; a graph does not prove a physical roof role.

The original fixture yields one candidate, with four original spokes and four
perimeter edges approximately 7.84433 m long. Its apex and slightly unequal runs
remain original; no centring or symmetry is imposed. The earlier gable's far cap
is the same original source component as one perimeter edge of this graph.
Each whole rail's retained tail coincides exactly with an adjoining boundary
interval for 0.50376339 nominal metre. Duplicate paints do not double-count
coverage. Whole rails are neither shortened nor extended.

This is evidence of a shared drawing boundary. It does not establish a flush
roof connection, physical building identity, construction detail or wall face.

## Source context and height comparisons

All thirteen original finite symbol diagnostics are compared with the new
perimeter. Their existing reach is unchanged: original centre through V tip plus
two symbol radii. Only the exact available reference to **2967/30/6 East** has
positive intersection and a direction within five degrees of a perimeter edge.
The other twelve remain held for this pattern. Original reference visibility
holds, including the north reference, are not overridden.

The east crop retains 21 original gable intersections at ink 220 and 65 at ink
235. Whole Hough pixel groups remain intact, including unrelated source pixels
that can share a fitted line. A corner proposal needs original pixels from both
slope groups within four pixels of its predicted position. This is a local source
support check, not a semantic roof classification or permission to trim the group.
All 250 corner/edge checks remain: 53 support both corners and 197 are held.

The literal-column recipe uses the same original ink, minimum 16 pixels, span
16 to less than 64 pixels and maximum two-row gap as the parent pass. The denser
east crop requires a separate bounded index: ink 220 yields 1,812 columns and ink
235 yields 2,062, just beyond the unchanged parent's 2,048-column cap. The new
index permits at most 8,192 whole columns. Thresholds, eligibility and original
pixel membership are unchanged; the old extractor and its contract are untouched.

All 1,631 local corner receipts remain, including 1,580 failures. Original column
candidates are indexed horizontally; each failed side is recorded once. Only
supported side pairs form Cartesian endcap checks. Every pair containing a
failed side is held by that side receipt rather than expanded repeatedly.
Thirty paired endcap checks agree. Equal-height witnesses can share a silhouette
record, retaining all original check IDs and pixel alternatives without averaging
or choosing a nearest column. Six east silhouettes remain in three printed-level
frames and both side orientations.

The preceding west crop supplies 56 **unassigned** silhouette hypotheses. Both
side assignments and every printed-level conversion are retained in 672 height
comparisons: 384 agree within 0.25 nominal metre for the apex and both eaves;
288 are held. A common printed datum and the west physical correspondence remain
assumptions. These views share a project drawing and are not independent survey
controls. The lower front gable remains a competing west source hypothesis.

## Conditional surfaces and unresolved threshold

Six five-vertex/four-triangle taller-roof variants are available for inspection:
two side orientations in each of three printed-level frames. They are alternatives
for one proposal, not six separate buildings. The raw source labels are `Preshow
Top Level 183.30`, `Undercroft Level 178.00` and `Level 181.25`. The generic third
label is not promoted to a passenger floor, platform or accepted physical role.

Original corners and apex provide every horizontal vertex. Two separate eave
measurements define an explicitly assumed linear eave-height plane; four
independent corner heights have not been observed. Continuous triangular surfaces
and roof roles are also assumed. Relative to Preshow Top Level, the apex is about
**8.200714 m** high and corner candidates range **5.688776–5.737875 m**.

**Only ink 220 supports these inspection models. Ink 235 produces none.** All
six reference/orientation groups carry `pyramid_cross_threshold_support_missing`
with missing threshold 235 and physical acceptance disabled. The zero paired
threshold comparisons are not reported as successful stability checks. There is
no threshold loosening or replacement of original source pixels.

## An open join, not a completed building

Each taller-roof alternative is compared with all 32 previous gable patches.
At the shared original cap, three original source points sample the earlier
patch's two eaves and ridge endpoint. The adjoining boundary height is measured
from the conditional eave plane in the same assumed printed datum. All 192
comparisons retain a positive gap, with minimum sampled clearances ranging
**0.628423–0.640012 m**. No translation, roof height, source tail or source point
is adjusted to close it.

The interactive scene uses original native plan XY and a selected printed-level
reference, with eleven vertices and eight roof triangles. Three dashed gap
measurements add no faces. The scene has no wall, closing fascia, foundation,
openings, complete watertight building or geographic registration. No accepted
physical component, world block or training label is produced. The semantic
ranker is untrained. Earlier source holds and all previous roof models remain
unchanged.

Next evidence work is to resolve the missing second-threshold corner support,
verify physical correspondence and recover the actual wall/fascia geometry at
the shared boundary. A complete building needs those controls before roof/wall
assembly and park placement can be accepted.

## Replay, export and verification

No new source acquisition was required. Use the same four checksum-verified
original PDFs and the existing source packs. The builder freshly replays the
entire preceding preshow pass before and after its own work, checks original
source/crop pins again, and requires saved output to match a fresh result.
The original fixture uses 58,176 charged checks of the fixed 100,000-check
budget. Work or source overflow clears every partial graph, context, measurement
and surface. Additional bounds include 4,096 original lines, 256 spoke
combinations per endpoint, 64 graph candidates, 512 silhouette groups,
256 surfaces and a 64 MB compact output limit.

```sh
python -m scripts.build_pyramidal_roof_evidence \
  --preshow /path/to/preshow-level-review \
  --references /path/to/reference-review --topology-source /path/to/topology-review \
  --gradient /path/to/gradient-review --components /path/to/components \
  --views /path/to/views --corpus /path/to/original-corpus \
  --source-catalogue examples/wicker-preshow-reference-catalogue.json \
  --additional-pdfs /path/to/preshow-originals --output /path/to/output
```

`python -m scripts.audit_pyramidal_roof_evidence` takes those source arguments,
`--evidence` and an `--output` receipt path. It freshly replays the new pass and
runs the independent parent audit. Separate arithmetic verifies all eight
original spoke/perimeter witnesses, both original boundary intervals, thirteen
finite context intersections, 5,548 slope pixels, 111,973 column pixels, 125 slope
intersections, all corner and cross-view checks, six surfaces, all 576 gap samples
and six missing-threshold holds.

```sh
python -m scripts.export_pyramidal_roof_models \
  --evidence /path/to/output/contract-hash --output /path/to/obj
python -m scripts.render_pyramidal_roof_evidence \
  --evidence /path/to/output/contract-hash --preshow /path/to/preshow-level-review \
  --references /path/to/reference-review --views /path/to/views \
  --objs /path/to/obj --output /path/to/review.html
```

OBJ files use unplaced nominal metres, Z up. Seventeen-digit formatting preserves
exact array values. The offline HTML embeds the original plan and all four
preshow crops, exact new/parent evidence JSON and the six pyramid OBJ exports.
It exposes every east source pair, west silhouette, symbol diagnostic, corner
failure and threshold hold, plus rotatable two-roof scenes and open-scene OBJ
exports. Source PDFs are not redistributed. Receipts and the compressed full
suite log are under `docs/evidence/pyramidal-roof-junctions/`.

Validation: **1,773 full-suite tests pass** in 463.893s,
including twenty new focused regressions. Browser checks pass 813
states, all 258 east pair/level combinations, all thirteen finite context
diagnostics, six exact pyramid OBJ downloads, all 192 open-scene OBJ downloads,
all 672 cross-view side assignments, five PNG hashes and exact JSON export,
with zero JavaScript errors.
