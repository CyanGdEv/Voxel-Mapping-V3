# Automatic component evidence inside drawing views

Area runs can inventory native boundary regions and opening evidence without a
local-wing recipe, facade datum, manually traced aperture or per-view rectangle.
The stage consumes the automatic drawing-view pack and current native extraction.
It produces source evidence for subsequent building interpretation; it does not
select an exterior, carve an opening or assemble a building.

## Running it

```json
{
  "drawing_views": {"enabled": true, "render_width": 1200},
  "drawing_view_components": {
    "enabled": true,
    "max_views": 32,
    "max_checks": 100000,
    "max_frames": 512
  }
}
```

Both settings are opt-in. Component discovery requires automatic drawing views.
The example includes the existing checksum-pinned acquisition catalogue:

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-view-components-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-view-components-job.json --output output/view-components-audit.json
```

The area report and all-area sweep expose `drawing_view_components`. Output under
`drawing-view-components/CONTRACT/` contains one JSON file per inspected view and
a hash-bound `component-report.json`. Source PDFs and original-source crops stay
in the upstream corpus/view pack. No synthetic physical recipe is produced.

Inventory v2 also adds [drawing text and repeated-stroke context](drawing-stroke-context.md),
retaining the broad scan alongside an explicitly scoped residual search.

## Native boundaries and wall bands

Only whole, uniquely assigned native parents enter a view. Parent record hashes,
original geometry, same-page membership and crossing exclusions are checked
against the current source feed and view pack. Component decomposition retains
source paints, parent references, curve approximation bounds and protected holes.
Closed polygons and already closed rings are retained as complete source regions.
They can be rooms, hatches, labels, context or physical boundary linework; closed
geometry alone does not decide their role. Open paths stay open. No bounding box,
convex hull, gap closure or object crop replaces a boundary.

Floor-plan views with a nominal scale use the existing paired-line wall kernel.
Original side intervals and supported disjoint fragments are retained; missing
opposite fragments are not extended. Competing overlapping alternatives remain
withheld. Roof-plan regions stay separate from floor-plan wall-band discovery.

Elevation views with a nominal scale use the existing native rectangle-cycle
kernel. Every cycle retains all four original source-side interval proofs.
Its 0.15–5 metre dimension range is a nominal discovery filter, not an accepted
physical size. Nested panes, frames and larger cycles remain alternatives;
there is no largest/nearest cycle selection or automatic aperture role.

## Raster opening evidence

The stage reads the exact upstream composited crop, checks its PNG/source receipt,
and converts it to grayscale. Caption reading direction selects an exact quarter
turn so raster columns correspond to vertical drawing strokes. Pixel-edge
transforms retain the pixmap's outward-rounded origin. No interpolation, resizing
or source-image tile clipping occurs.

The existing indexed jamb/head scanner runs on every supported elevation crop,
including crops with no native building edges. Both thresholds (220 and 235),
all eligible jamb pairs and every supported threshold-consensus family remain
in the evidence. The default discovery bounds are 24 pixels high, 20–600 pixels
wide, at most 700 pixels high, two-pixel endpoint spread and 90% dark head support.
These are raster discovery heuristics. Rails, texture and annotations can pass
them. A family is never silently labelled a window or door, assigned a sill,
or used to remove material from a wall.

Each family links back to its indexed threshold-pair proofs and source crop,
and has reversible native drawing coordinates. A nominal local copy exists only
when that view has a unique printed scale claim. Missing scale keeps pixel/native
evidence without metric dimensions. Any polygon crossing the inferred source-view
region is explicitly withheld; no clipping repairs it.

## Budgets and acceptance

At most 32 views and 512 native cycles per view are inspected. The configurable
100,000-check ceiling applies separately to each existing discovery kernel.
The raster scanner also retains its 512 vertical-run-group and 8,192 indexed-pair
limits. Its six-million-pixel/3,000-pixel-side limit withholds oversized raster
passes without pretending the view was fully scanned. Kernel exhaustion discards
that kernel's partial result; native/raster statuses remain separate. The view
limit reports a partial inventory and deferred count. Cumulative view JSON output
is capped at 64 MB; failure leaves no completed component report.

Contracts bind source report/feed/artifact hashes, source PDFs, implementation
hashes for the adapter and existing kernels, options and runtime dependencies
(including Shapely/GEOS, PyMuPDF, NumPy and Pillow).
Replay verifies inputs and every output; a fresh audit recomputes all view files.
The original inventory used area/controller v6/v4; context v2 uses v7/v5 and
[partitioned discovery](partitioned-jamb-discovery.md) v3 uses v8/v6. Use a fresh work directory for older
area jobs and retain prior worlds as pinned baselines.

The remaining building gates are actual boundary/aperture identity, construction
state, reconciliation across views, verified dimensions/levels, and independent
site registration and vertical datum. Accepted physical components, world blocks
and training labels remain zero in this inventory.

## Wicker validation

The original three checksum-pinned shop sheets are downloaded using the recorded
same-resource transports, verified against their known hashes, then used offline
for the area run. Six source views yield 3,528 unchanged native components,
110 closed source regions, 14 floor-plan wall-band candidates and 28 complete
native rectangle cycles. All 112 native cycle-side interval proofs reproduce
original source endpoints. No view rectangles or local-wing seeds are supplied.

Three elevation raster passes exceed the existing indexed-pair or run-group
limits and publish no partial families. The fourth (north-east) completes with
2,520 threshold-consensus families. This is **not an opening count**: the source
contains shutter rails and cladding lines that satisfy the same geometric tests.
Every family retains its alternatives, with no window/door or physical aperture
assignment. All four original crop grayscale hashes and all successful family
transforms are checked. The area report explicitly records the three withheld
passes and `all_requested_passes_completed: false`.

All six inventory files match a fresh independent replay. Source per-view
construction state remains unspecified, and accepted physical geometry remains
zero. The actual next gap is semantic boundary/aperture identification and
bounded handling of dense raster ambiguity, followed by cross-view reconciliation
and independent placement. Raising budgets alone would not resolve the false
matches.

Retained audit and local-test receipts are in `docs/evidence/view-components/`.

| Source view | Closed regions | Native rectangle cycles | Raster pass |
| --- | ---: | ---: | --- |
| Ground-floor plan | 48 | — | Not an elevation |
| Roof plan | 28 | — | Not an elevation |
| South-east elevation | 6 | 5 | Indexed-pair budget withheld |
| South-west elevation | 10 | 9 | Vertical-run-group budget withheld |
| North-west elevation | 9 | 7 | Indexed-pair budget withheld |
| North-east elevation | 9 | 7 | 2,520 unverified families |

The local suite passes **1,552 tests**, including 13 new component-inventory tests.
