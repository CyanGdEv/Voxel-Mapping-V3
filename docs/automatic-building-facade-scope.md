# Automatic named building scope and facade references

[Automatic elevation level context](automatic-elevation-level-context.md) now
adds conditional original-row support above printed levels alongside these links.

Automatic component inventory v5 adds visible named source enclosures and
numbered facade-ray hypotheses. This follows the broad
[plan opening width links](automatic-plan-opening-links.md) and keeps those
alternatives available. It requires no manual wing, building box, label seed,
footprint trace, opening trace or facade origin.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-building-scope-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-building-scope-job.json --output output/building-scope-audit.json
```

## Visible labels and source-only enclosures

Inside each automatic non-roof floor-plan view, the adapter identifies standalone
`Shop`, `Station` / `Ride Station`, and ordinary names ending in `Building`.
The literal original text, trace/character indices, native bounding polygon and
original-font raster screen remain evidence. This bounded grammar is a label
discovery vocabulary; it is not a trained semantic model or universal name parser.

For each visible occurrence, the existing mixed-source footprint kernel uses
its original glyph-box centre as an automatic seed. The source network consists
of exact supported solid straight page strokes and nonwhite supported clipped
fill boundaries. It runs only the source baseline, with **zero inferred gap
corridors**. Original source vertices remain unchanged. No snapping, convex hull,
minimum rectangle or automatic gap closure supplies a building outline.

A centre-containing face qualifies only if the entire original label polygon and
entire enclosure lie inside their respective source scopes. Every qualifying
alternative remains, with its original stroke/fill/clip interval proofs. Faces
that cross the label or view remain explicit exclusions. Original interior rings
are preserved as unclassified drafting voids. A named enclosure can still be an
internal room, drafting region or incomplete physical footprint.

Each plan gap with positive exact area overlap with a qualified enclosure gains
a candidate label/enclosure association. Every overlap is retained with its
fraction and original gap hash. There is no nearest building choice. Gaps may
associate with multiple candidates; unassigned gaps remain in the broad inventory.
Neither overlap nor a unique source face verifies a physical building assignment.

## Numbered references, facing segments and plan positions

Original sheet headers must pass the original-font glyph screen before producing
an elevation project/sheet/view key. The elevation number comes from its existing
caption evidence. Catalogue identity and construction state are never inherited.

The original Revit-style reference kernel retains circle curves, corner fills,
number trace indices and glyph screens. A reference can enter this view's facade
search only when its entire circle and corner bounding polygons are covered by
the automatic plan-view scope. Outside/crossing references remain original-page
context. Existing clipping and marker semantics remain unverified.

For every eligible marker/enclosure pair, the existing ray kernel retains all
isolated outward-facing exterior segments within five degrees. It never selects
a nearest ray hit. A marker inside the enclosure, tangential intersection or
missing facing segment produces an explicit hold. A printed direction is not a
verified geographic bearing, camera interpretation or building association.

Candidate gap links additionally require the source gap axis to be within five
degrees of the facing segment and both source cap centres within 0.25 nominal
metres of its support plane. These are discovery windows. All eligible alternatives
remain; a gap's endpoints are never moved onto the wall.

The stage records the original gap's nominal projected position interval within
the plan enclosure's projected extent. It uses the uncorrected printed nominal
scale. It does not import historical furniture-layout correction, choose an
elevation facade boundary or fit an origin to make candidate positions agree.
`position_alignment_verified` stays false and the independent elevation facade
origin remains required.

`building-facade-links.json` links these hypotheses only to broad width matches
with the same numbered project/sheet/view key. Duplicate target keys remain
multiple alternatives. Every narrower link binds the original broad match hash,
projection and source inventory hashes. The broad inventory is preserved; this
channel is not a replacement complete opening search.

## Budgets, validation and limits

At most 16 supported named label occurrences enter a plan pass. Each existing
source-only enclosure attempt uses the configured component work ceiling, up to
100,000 checks, with the existing segment/face/provenance caps. Exact gap-overlap
association and, separately, facade-ray/link work also have that ceiling. A late
budget hold discards all partial labels/associations or facade links, respectively.
The existing reference kernel retains its fixed 500,000 primitive comparison cap.
The 32-view and cumulative 64 MB component-pack limits include the new output.

Contracts pin the adapter, source-only footprint, original edge/reference and
facade-ray implementations. Inventory v5 advances area/controller to v10/v8;
use a fresh work directory for older jobs. Original PDFs and all upstream source
artifacts are rechecked before publishing the completed component report.

The Wicker validation uses the same three checksum-pinned original shop drawings.
Audit receipts are retained under `docs/evidence/building-facade-scope/`. They check
source text, whole-label containment, original boundary intervals, protected
holes, exact gap overlap, marker segment proofs, plan projections and narrower
width links, plus fresh replay of every output and preservation of the earlier
broad width-pair set.

Physical exterior/aperture roles, complete neighbouring-building scopes, facade
origin/position alignment, dimensions/construction state and independent map
registration/vertical datum remain gates. Accepted physical components, world
blocks and training labels remain zero. This step produces no new reconstructed
world, and the semantic ranker remains untrained.

## Wicker result

| Source evidence | Retained result |
| --- | ---: |
| Original visible supported building-name occurrences | 5 |
| Enclosures containing their entire label polygon | 1, labelled Shop |
| Protected holes in that source enclosure | 7 |
| Original boundary-interval proofs for that enclosure | 436 |
| Gap/enclosure overlap candidates | 6 of 24 plan gaps |
| Numbered marker/enclosure reviews | 4 |
| Facing source-segment hypotheses | 4 |
| Gap/direction hypotheses passing the plane/axis windows | 2 |
| Narrower numbered-reference width links | 40 |

The shop candidate is a labelled source enclosure, with its full irregular outline
and seven holes. It is not accepted as the complete physical exterior. The ride
station, maintenance and comms labels have no exact whole-label enclosure in this
recipe. The centre-containing preshow face crosses its full label and is excluded.
The remaining 18 plan gaps are unassigned in this channel, not classified as
belonging to another building or physically absent.

The south-west hypothesis has no compatible retained residual width family.
The north-west hypothesis retains 40 alternatives. South-east has no qualifying
projected gap, while north-east is explicitly held because the marker centre lies
inside this enclosure. No nearest boundary or alternative marker interpretation
is substituted. These findings expose missing correspondence evidence, rather
than proving a source drawing has no opening.

All 955 broad width-pair alternatives remain available. The two broad SE/NW
raster passes remain pair-budget withheld. Independent elevation facade extent
and origin, marker semantics and physical boundary roles remain unresolved;
position alignment and physical opening acceptance stay false.

The final local suite passes **1,589 tests**, including nine new regressions.
The focused related suite passes 51 tests. All eight output artifacts match a
fresh replay, with all 955 broad width-pair alternatives preserved.
