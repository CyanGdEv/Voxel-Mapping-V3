# Closed curved source boundary review

Planning pilots now inventory closed curved paint separately from the straight
building and surface hypotheses. A new original-page overlay is linked from
`review.html`; the page JSON retains original native Bézier controls, line and
rectangle operators, closure flags, fill rules, colours, opacity, paint order,
source ordinals and hashes. Original holes remain in the display polygon.

The pass scans the whole original page, independently of nearby labels. This
avoids mistaking a label-centred crop for a complete inventory. Only whole
supported closed paint primitives enter the inventory. Open curves cannot join
other strokes, snap small gaps, or acquire inferred widths. Filled PDF subpaths
retain the PDF's own implicit closure and fill rule. Compound closed strokes,
multipart fills, unsupported clips/compositing, nonopaque paint, crop crossings,
tiny symbols and glyph masks remain outside this first supported class.

Adaptive De Casteljau subdivision bounds the distance of each retained cubic
segment to its chord by at most **0.05 PDF points**. The evidence retains the
actual bound, requested tolerance, original controls and generated vertices.
This is a display approximation bound, not a physical surveying accuracy or an
exact-curve topology proof. At nominal 1:250 it corresponds to about 4.4 mm;
this pass itself supplies no scale or geographic registration.

The curve uncertainty envelope must fit supported clipping/crop boundaries.
Later fill/image/shade bounds that intersect the buffered boundary withhold the
record, including paint between a straight display chord and the original
curve. This is a conservative visibility screen, not proof of physical identity.
Original duplicate paint witnesses remain attached, and original page bytes are
rechecked. White fill-only paint cannot supply a boundary.

The review has lower-only caps of 500 extracted candidates, 200,000 flattened
points, 20,000 retained source operators, 100,000 original control points and
8 MB of evidence. Existing native path, paint-reference and per-primitive point
limits remain. Quota failure withholds all records. Cancellation propagates
without producing a successful truncated inventory. The new runtime module is
included in pilot implementation fingerprints and frozen Windows smoke checks.

## Physical interpretation is still required

The inventory version and review-only status are distinct from source-outline
inventories used to authorize semantic associations. None of these records is
fed to the building, surface, nominal-layout or world-generation stages.
Closed curves may describe trees, legend symbols, annotations or theming rather
than paving. Existing valid building/surface proposals therefore remain intact.

The Wicker source is previously inspected development data. The first retained
source excerpt shows the largest eligible curved boundary is a tree illustration
in the legend, demonstrating why simply allowing curved polygons into the
surface stage would be unsafe. This pass supplies no new paths, building
heights, accepted park geometry, neural training labels or weight updates.

Next work is source-backed interpretation of open curved linework and its
relationship to the path descriptions, hatching, retaining walls and levels.
Original endpoints and controls must remain intact; connectivity and surface
closure cannot be manufactured by snapping or filling gaps. Separate reference
geometry is still required before reconstruction accuracy can be measured.

The source-pinned development replay and validation are recorded in
[`validation.json`](evidence/planning-curved-boundaries/validation.json).
