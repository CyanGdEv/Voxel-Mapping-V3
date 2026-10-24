# Fine component boundary recovery

Floor-plan analysis now runs a focused fine-linework pass when the original
page has visible standalone `Container` or `Shipping Container` labels. The
coarse inventory remains unchanged: several labels in one enclosure still
produce one shared-enclosure hint. The fine pass can independently recover
smaller closed faces around individual labels.

The motivation is a measurable extraction gap. Coarse discovery omits lines
shorter than 12 PDF points; CAD boundaries made from many short segments can
therefore remain open or lose their partitions. The focused pass retains
straight lines down to 0.25 PDF points and polygonizes their exact network.
It does not move endpoints, bridge gaps or replace missing edges.

The scan rectangle encloses visible component labels plus a 144 PDF-point
margin, bounded by the original page. This is a search region, not an inferred
building or view boundary. Complete paint primitives that cross its edges stay
withheld. Large components and sparse labels may therefore remain unresolved.
No user-provided component recipe, training label or new model weight is needed.

A candidate requires a complete bounded extraction and recovery, the existing
source paint/visibility filters, one unique whole-label enclosure, one visible
component label, consistent role/state claims, and no interior rings. Conflicting
roles, legend labels, shared enclosures, nested competing outlines, hidden text,
dashed dividers, obscured boundaries and interior rings remain explicit gaps.
Native geometry, source record hashes, exact label/glyph evidence and original
paint/line provenance accompany each candidate.

These are **source component boundary hypotheses**, not verified building
exteriors. A closed face can still be a room, annotation or another partition.
View scope, wall role, physical component identity, printed versus current state,
scale, elevations, ground levels and geographic alignment remain unresolved.
The stage neither emits accepted park buildings nor trains a neural model.

## Review and bounds

Run **Collect & analyse PDFs** and open Results → `review.html`. Purple outlines
show the fine component candidates alongside the unchanged cyan/orange/green
inventories. Page JSON includes the focused extraction settings, inventory and
association hashes, exact candidate records, and withheld-boundary decisions.
Counts propagate through individual pilots, web handoff, automatic batches and
the desktop summary. Collection scopes pin this implementation, so an upgrade
analyses verified cached sources under a new scope; repeating that request
reuses its checked saved batches.

Per-page defaults cap 32 component labels, 10,000 native candidates, 200,000
native points, 500 filtered source outlines and 8 MB of component output. Options
are lower-only. Fine line recovery retains at most 2,048 provenance references
per face and uses the existing network budgets. Incomplete extraction, recovery,
association and output budgets publish zero successful component candidates.
Cancellation is checked between stages and candidates; managed worker termination
still supplies cancellation during native operations. Native PDF parsing itself
is not a hard memory reservation.

## Woodcutters development result

The previously inspected SMD/2024/0136 floor plan supplies six printed Container
labels. Five pass the existing glyph comparison. The focused pass finds four
unique visible-label enclosures; three have no interior rings and become
individual source boundary candidates. One enclosure has interior rings and
remains withheld, one label has no supported closed boundary, and one fails the
glyph comparison. The title-block Facilities Building label supplies no component.

This is development evidence from previously inspected cached originals, not an
unseen-area benchmark or independent geometry truth. Paths/plazas, raster
elevations and park placement remain unfinished. See the retained
[collection and restart proof](evidence/component-footprints/woodcutters-development-validation.json).
