# Open curved source networks

Planning review can now assemble an enclosure from separately painted original
curved and straight strokes. The earlier closed-curve inventory required a
boundary to be closed within one source paint primitive. This stage follows the
original operator joints across strokes and retains the complete parent records,
native Bézier controls, operator indices, paint references and hashes.

The pass reuses the existing fine-surface source windows, selecting whole paint
primitives without clipping their geometry. Recovery happens independently in
each window. Endpoints use the normalized native PDF coordinates without
snapping. Original straight-segment intersections are noded, and a curve endpoint
that lies exactly on a straight segment can join that segment. Intersections
inside a curve are not replaced by intersections with its display chords.
Uncertain near curves, overlapping curved boundaries and unsupported crossings
remain withheld. PDF parser numeric precision still limits these coordinates.

Each original operator has its own curve/error metadata. A straight part of a
compound paint group cannot inherit another part's curvature. Scoped paint
aliases are reconstructed from their own original operator/subpath records,
including when their operator ordering differs. The 0.05 PDF-point display
approximation retains its source control-hull bound; it is not a surveying
accuracy or a proof of exact curve topology near a shared endpoint.

Later paint is checked against every contributing original edge and its error
envelope. A redraw of a different edge cannot clear a covered edge. Global
original stroke checks also catch competing linework whose whole paint group
extends beyond a search window. The search window therefore cannot hide a
crossing and turn the retained subset into a successful boundary.

The pass retains holes and records contained source labels with their existing
visibility/context evidence and boundary clearance. It does not infer physical
roles or materials from those labels. The version and review status are distinct
from ordinary source-outline inventories. These records cannot enter the
building, surface, nominal-layout or world-generation stages.

## Diagnostics and bounded work

The separate original-page overlay shows assembled source rings in green and
sampled original curved operators in magenta. Red points identify unresolved
connections within the selected source scopes. Up to 128 of the longest visible
original curved operators are shown; the evidence explicitly reports sampling.
Each sampled operator retains original controls and source indices. These are
diagnostic strokes, not a complete inventory of physical paths or features.

Lower-only limits retain the existing 10,000 native candidates, 200,000 native
points and at most 32 source windows. Each scoped graph is bounded to 20,000
flattened segments. The whole pass charges at most 100,000 pair/label checks,
500 faces, 2,048 provenance edges per face, 20,000 source operators, 100,000
original control/endpoints and 8 MB of evidence. Additional global stroke
parsing is charged to these limits. Budget failure withholds all assembled
records and diagnostic geometry; cancellation never returns partial success.

## Development result and remaining blocker

The Wicker replay uses the original PDF and the previously audited surface
analysis. It reruns the new network stage and checks that the unchanged native
surface extraction still matches the prior parent-inventory hash. The saved
four-building/two-material layout is retained as a pinned baseline, rather than
rerunning unrelated glyph, section and building analysis.

The current Wicker source yields **no qualifying assembled curved faces** under
these rules. Its curved operators and unresolved connections are now available
for source inspection. This is not a new path network or world download. A
separate synthetic source demonstrates successful curved-ring assembly while
keeping the previous exported paving and building markers unchanged.

Further work needs source-backed intersections inside Bézier curves and physical
interpretation of open edges, hatching, widths, walls, grading notes and levels.
Missing source boundaries cannot be supplied by snapping endpoints or guessing
path widths. Building heights, roof reconstruction, accepted park geometry and
neural weight training are unchanged. These sources are development data;
independent reference geometry is still required for accuracy measurement.

Source-pinned results are recorded in
[`validation.json`](evidence/planning-open-curve-networks/validation.json).
