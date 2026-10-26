# Complete long curved source strokes

The original label search windows can omit a long planning stroke even when it
passes several visible labels. The Wicker source includes red curved strokes
spanning over 1,000 native PDF points that intersect several windows but fit
inside none. Cropping those strokes or joining pieces from unrelated windows
would invent source geometry.

Planning pilots now add a separate complete-stroke review. A planner finds
opaque, solid, supported open curved paint groups that cross the existing
windows while remaining wholly inside the original page and supported clips.
It records their original ordinals, complete operator/control witnesses, styles
and intersected seed windows. Naturally closed, clipped, nonopaque, optional
layer and unsupported groups cannot select an open-curve scope.

Scopes contain the entire original stroke bounds and their intersected seed
windows, with a 0.5 native-point source margin bounded by the original page.
Exact original RGB colour, width and dash style keep source families separate.
These fields supply provenance, not physical path, material or drawing-state
classification. Differently coloured half-rings cannot close one another in
this separate review.

The native reader selects whole paint groups within their own matching scopes.
It preserves original global ordinals, clips, opacity and layer checks, and
reports whether each anchor's eligible original subpaths were retained. No
source points are clipped, snapped, rescaled or given invented widths. Native
style filters participate in the extraction contract; unfiltered extraction
retains its existing contract and output. Existing source-label/fine-surface
recovery and accepted layout inputs are unchanged.

The existing network recovery then works within each complete source family.
Its global original-stroke and later-paint screens still apply, including
competing strokes of other styles. Intersections inside curves remain
unverified; a display-chord crossing cannot replace an original Bézier crossing.
Recovered rings and diagnostic curves remain review-only and do not enter
world generation. A separate original-page overlay is linked from `review.html`.

## Bounds and validation

Scope planning has lower-only caps of 32 families, 256 original anchors, 20,000
operator work units, 200,000 flattened points, 100,000 scope checks and 8 MB of
evidence. Clip parsing is charged to the same work limits. The native/network
candidate, point, graph, provenance and output limits remain unchanged. Quota
failure withholds the whole new plan/review; cancellation cannot return a
successful subset. Planning and recovery share one immutable page-paint cache,
verified against the original page identity and content hash.

The Wicker development replay now retains both previously excluded long red
strokes, with every eligible original subpath present. It uses the original PDF
and pinned, previously audited seed-scope analysis. The legacy native extraction
is checked against its previous inventory hash; unrelated glyph, building and
section analysis is not repeated for this stage-only replay.

This pass does **not** supply a new Wicker path network. A candidate ring remains
withheld by the original paint/visibility safeguards. Controlled full-pilot and
managed/frozen examples demonstrate successful long-ring recovery while keeping
it outside the exported paving. The existing paving cells, tiled preview and
persistent restart remain covered by the desktop checks.

Further work requires verified intersections inside Bézier curves and physical
interpretation of boundaries, hatching, widths, walls and grading notes. Source
RGB and plot-line thickness cannot supply those meanings. Building heights,
accepted park geometry, neural weights and the existing real-area layout are
unchanged. This remains development evidence, not an unseen accuracy benchmark.

Source-pinned results:
[`validation.json`](evidence/planning-complete-curve-scopes/validation.json).
