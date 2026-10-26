# Complete tiled planning-world previews

The flat area exporter now supports a complete platform larger than one
128×128 metre section. Version `planning-area-world-preview-v2` partitions
integer cell intervals into at most four disjoint sections and writes one
Bedrock world. It preserves the shared nominal coordinate frame and every
candidate. Sections never crop source polygons, move distant proposals,
rescale the layout or fill geometric gaps.

Each section remains bounded to 128×128 cells. The global limit remains
**100,000 native write attempts**, counting every ground cell, its three
foundation cells and each distinct feature-cell write. Therefore the complete
platform cannot exceed 25,000 cells before feature writes. Candidate, source
point and sampling limits remain 128, 200,000 and 262,144. A long sparse
platform can still exceed the four-section limit and is withheld in full.
Legacy v1 requests retain their original single-platform limit.

Source polygons are centre-sampled section by section. Disjoint half-open
intervals cover each original sampling cell exactly once, including features
crossing section edges. Holes, narrow geometry losses and four-neighbour
membership remain explicit. Matching surface proposals may share cells;
inconsistent finishes or building/surface overlaps remain withheld globally.
Palette patterns retain source coordinates, so they do not restart at seams.

The intent file streams sections into the existing SQLite-backed native writer,
which commits one chunk at a time. The sampler's combined feature dictionaries
remain bounded by the global platform/write limits; this is not unlimited-area
generation. Saved readback now retains one decoded chunk at a time and checks
**every platform cell**, including grass and seams, plus two air cells above it.
Per-section saved ground, feature, paving and candidate counts must match.
The native writer also verifies every composed block and all unwritten air.
Archive bytes/CRC, fresh extraction, chunk coverage and spawn checks still run.
Cancellation, any quota failure, source-pin changes or readback errors cannot
publish a partial output. Existing output directories are never overwritten.

## Wicker development export

The exact saved layout from coalesced recovery is unchanged:
`ca5f53d7a33d8cd22f1e91983372cc17c78df65f32d403c2a7a6893a3d2b946c`.
Its complete padded bounds are `[6,33,202,148]` in nominal source metres:
**196×115 m**, **22,540 platform cells**, covered by two sections of 14,720
and 7,820 cells. This exceeds the old global span and area caps while remaining
inside the unchanged total write cap: **90,281 attempts**, **90,160 composed
blocks**, **104 saved chunks**.

All five proposals remain at their original positions: three yellow building
footprint markers (113 cells) and two material-surface proposals (eight cells).
The distant kiosk is retained. The eight material cells form three grid
components; they are **not verified paths, plazas or a park paving network**.
All candidates still have unknown heights. No roofs, openings, finished levels,
physical identities or surveyed park alignment are supplied. No accepted park
geometry, training labels or neural updates are created. Minecraft import and
gameplay have not been tested. The original plan was previously inspected
development data, not an unseen accuracy benchmark.

Use **Export plan layout** on the completed planning job. The managed desktop
automatically requests v2; the source CLI also accepts a pinned v2 JSON request
as described in [shared area layouts](planning-area-layouts.md). Old source
layouts need no geometry edits or new analysis to use this export.

Regression checks cover source-derived larger PDF export, seam paving, negative
coordinates, holes, point contacts, four-section coverage, all work ceilings,
legacy requests, cancellation after section two and saved grass corruption in
section two. The managed/frozen smoke retains the original 149 paving cells and
two components, then analyses a second complete synthetic A1 PDF exceeding both
old platform caps. It checks all five proposals, independently calculated
building spacing, complete saved sections, output hashes and persistent restart.

The [development receipt](evidence/tiled-area-world-previews/validation.json)
records exact layout/world pins and an independent full-platform archive audit.
The next reconstruction work is physical surface interpretation and more
complete path/plaza coverage, followed by cross-view building heights and roofs.
