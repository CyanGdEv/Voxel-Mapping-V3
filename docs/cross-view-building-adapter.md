# Cross-view local building adapter

`voxel-building-data assemble-views` (or `python -m voxel_mapper.building_pipeline
assemble-views`) connects original native PDF discovery to the shared
`building-spec-v1` contract. The first supported case is a rectangular floor-plan
face and four separately scoped, straight-line elevation faces. It generates
local surface hypotheses, not a geographically accepted building.

## Input and source scope

Use `version: "cross-view-building-v1"` and a `buildings` array. Each building has
an ID, original `sources` in the existing raw discovery format (`path`, SHA256
and optional one-based `pages`), and up to five `views`. Missing views produce
an evidence queue without a model. Source discovery recomputes native geometry
from original bytes; it does not import a hand-built study or supplied model.

A view binding has these fields:

| Field | Meaning |
|---|---|
| `id` | Unique view ID, at most 128 characters |
| `document_sha256`, `page` | Exact original PDF and one-based page |
| `kind` | `floor_plan` or `elevation` |
| `side` | Elevations only: `y_min`, `y_max`, `x_min`, `x_max` in the local plan axes |
| `caption_index` | Zero-based index in the discovered page's `caption_layout.view_captions` |
| `bounds_pdf_native` | Reviewed `[xmin,ymin,xmax,ymax]` in native PDF points, Y up |
| `scope_review_reference` | Source-bound external scope review reference |
| `reverse_x` | Explicit local left/right reversal, default false |

Scope references are declared inputs, not authenticated reviews. The bounds
must contain the original caption and lie within the original page. Whole
native faces are retained; no geometry is clipped to fit a scope. A visible
floor-plan caption is required; roof/key plans cannot substitute for a wall
footprint. Elevations need visible elevation captions. Each view must have an
explicit existing/proposed claim and a usable printed scale. Unknown state and
mixed existing/proposed views remain withheld. The inline view scale is used
when printed in the caption; otherwise the original page scale is checked.
Cropped pages and nonstandard PDF UserUnit values are unsupported.

A native caption cannot supply several views, and the same native face cannot
supply several assembly roles. Local facade slots and reversals do not certify
geographic orientation. No source-state, physical-identity or acceptance flag
can be supplied in a view binding to bypass these checks.

## Assembly and limits

The adapter retains complete supported native polygons or complete recovered
straight-line enclosures, with their paint/source references. Partial extraction,
partial line recovery, truncated provenance and curved faces remain withheld.
Native paint provenance is not independent proof of visibility or physical role;
selected faces still need physical interpretation and review.

Each axis-aligned rectangular plan candidate is compared with independently
scaled facade widths. Every side needs exactly one match within the dimension
bound, and exactly one complete plan/facade tuple must survive. The adapter does
not select the largest face or the best-scoring ambiguous match. Width differences
are reported, and source coordinates are not stretched to make them agree.

Facade meshes preserve original polygons and holes at printed scale, translated
into local axes with their bottoms at local zero. The floor is a zero-thickness
local display reference. A roof surface is interpolated only between agreeing
opposing upper silhouettes, with compatible side eaves; either local roof axis
is supported. Roof identity, overhang, material and hidden construction are not
established by this interpolation. Tolerated dimension differences can leave
joins unresolved. All six component surfaces retain inferred evidence and
explicit assumptions; this is not a watertight solid or complete room inventory.

Limits are 32 buildings, five views per building, 256 retained faces per view,
100,000 matching checks, floor dimensions 0.5–100 m and facade heights 0.5–50 m.
`options.dimension_tolerance_m` defaults to 0.25 m and accepts 0.001–0.25 m.
`max_faces_per_view` and `max_checks` may only reduce their limits. The existing
raw discovery page, record and byte budgets apply through `discovery_options`.
Original bytes are checked again before dependent geometry is published. A bad
building is isolated; matching-budget failure discards partial matches.

## Outputs and review/learning integration

Use a fresh output directory:

```bash
python -m voxel_mapper.building_pipeline assemble-views \
  --config cross-view-job.json --output fresh-cross-view
```

Outputs include pinned discovery records, `contract.json`, a per-building
interpretation receipt and, for supported hypotheses, `building-spec.json`,
`model.json` and `model.glb`. `building-batch.json` uses the existing candidate
ranker format. Every source/identity/dimension/topology acceptance gate stays
false; a mesh validity check cannot authorize physical acceptance or native
structural support. Running the normal batch on these inputs selects no model.

`review-queue.json` is the existing hash-bound `building-review-queue-v1`, so
`collect-feedback` can bind externally supplied decisions to exact candidate
hashes, computed features and all original sources. Outcomes begin unset. Review
authentication remains unfinished; a declared review reference is not evidence
of an actual independent review. `source-queue.json` separately retains blocked
buildings and unresolved evidence tasks. Mesh exports and comparison scores never
create training labels. Source consistency diagnostics are not calibrated
correctness probabilities; native topology quality remains unassessed/zero.

A supported synthetic fixture produces one six-component specification and GLB,
preserves its original window hole and proposed state, and remains ineligible
for ranking acceptance or park insertion. Capability fixtures are explicitly
synthetic, not real Alton evidence. Replay is deterministic for unchanged input
bytes and bindings. Tests also cover conflicting dimensions/roofs, ambiguous
plans, source reuse, missing/hidden view evidence, unknown/mixed states, work
budgets, changed originals, view reversal and review-queue tampering.

## Real Wicker replay — 13 October 2026

All three revised shop originals were recovered through their recorded council
HTTP transport and match the existing historical pins: drawing 2967-21 (ground
floor), 2967-26 (shop elevations), and 2967-48 (roof plan). A retained source
bundle preserves them independently of the live council endpoint.

Raw discovery checks all three pages and inventories 12,148 source records.
The adapter emits **zero real building specifications**. No reviewed source view
bindings were supplied. The existing native caption parser finds no supported
floor/elevation view captions; its one roof-plan caption remains visibility/state
unresolved and cannot supply a floor footprint. The elevation page has 85 raster
image placements, so native discovery does not establish complete facade
silhouettes. The source catalogue's proposed-state assertion is not silently
inherited as a visible per-view state.

The next real-source work is source-bound interpretation of the numbered/image
views, appropriate raster geometry evidence where native geometry is absent,
reviewed view scopes, state and scale qualification, and then cross-view dimension
checks. Irregular/multipart plans and complex roofs are outside this first adapter.
Materials, source reuse, as-built identity, opening completeness, native support,
independent geographic registration and vertical datum remain required before
park insertion. No real model, accepted park blocks or training labels were
produced in this trial. The earlier hand-built shop model is not used as automatic
reconstruction evidence.

Source pins, counts, artifact hashes and the trial receipt:
[evidence/wicker-cross-view-building-2026-10-13.json](evidence/wicker-cross-view-building-2026-10-13.json).
Original PDFs, discovery outputs and generated fixture previews stay outside Git.
