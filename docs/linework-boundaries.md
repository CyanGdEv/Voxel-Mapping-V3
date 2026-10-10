# Exact linework boundary recovery

`linework-boundaries-v1` recovers enclosed network faces from separately painted
solid straight strokes. It nodes exact intersections and polygonizes the actual
source graph. It never snaps endpoints, fills gaps or joins merely nearby lines.
Curved strokes and dashed/unknown paint styles are deferred. Recovered outlines
are unclassified faces, not accepted buildings, path surfaces or water areas.

Nested rings retain holes. Polygonization also retains an inner face separately;
this does not decide whether an inner region is solid, open courtyard or water.
Existing identical polygon candidates are retained rather than duplicated.
Every new face records contributing line/component IDs, raw-parent links,
original paint ordinals, covered boundary lengths and extraction contracts.
A 1e-7 PDF-point epsilon compensates overlay roundoff **only when tracing source
coverage**; it does not enter the network, noding or face geometry. Intersecting
strokes that contribute only a crossing point are excluded from provenance.

```sh
python -m voxel_mapper.linework_boundaries \
  --corpus work/corpus \
  --candidates work/drawing-geometry/geometry-candidates.jsonl \
  --sheets selected-sheets.json --output work/linework-boundaries
```

The parent feed must contain complete grouped retained pages. Original PDF bytes
and exact current parent records are checked. Selection is an optional list of
`["PDF_SHA256", page_number]`; selected runs output only those pages. Without it,
all candidate-bearing pages are processed. Valid reordered records within a page
are canonicalized through retained extraction before recovery.

Outputs are a combined original-component/recovered-face JSONL feed, a polygon
feed, per-page recovery diagnostics and a hash-pinned receipt. Matching redoes
recovery from retained source pages and compares the whole supplied record,
including parent traces and options. Forged geometry or provenance is rejected.
Complete resume rechecks original PDFs, inputs and all output hashes. Use a fresh
output directory after an interrupted recovery or when changing options.

Default limits per page are 20,000 input segments, 100,000 intersection pairs,
200,000 noded points and 4,000 faces. Budgets can be lowered via the API or park
job. Excess networks withhold recovery while retaining original components.
Small faces below 16 native square points, excessive face vertices and parent
provenance above 256 line/paint records are deferred. These are processing
filters, not physical size or family claims. Input/output limits remain 2.5
million records, with 10,000 grouped pages and 10,000 parents per page.

Enable an optional park stage:

```json
"drawing_geometry": {"enabled": true},
"linework_boundaries": {"enabled": true}
```

The pipeline uses recovered feeds for outline review, polygon matching and
provisional placement. Recovered faces are explicitly barred from world export
until linework identity, fill/current state and physical semantics are reviewed.
Generator widths/heights/materials and independently checked registration remain
required. Source labels, stroke widths and loop closure do not supply them.

## Equivalent boundary orientations

Mapped placement v3 now verifies every retained equivalent boundary orientation
against the whole sheet. V2 could choose one of two equally good rectangle
orientations and never try the one agreeing with other landmarks. A real-PDF
fixture with twelve separately painted wall edges now recovers three rectangles
and finds their shared map placement. Orientation trials are counted separately;
a boundary pair has at most twelve retained orientations. Verified registration
and world-export gates are unchanged. V3 requires fresh outputs when upgrading
from v2.

## Retained Alton comparison

The first thirty ranked unplaced sheets supply 47,019 original component
records. Exact recovery produces 2,933 additional faces and a 49,952-record
combined feed. Across these pages it processes 22,220 solid straight lines,
60,791 segments and 57,540 intersection pairs. It defers 8,822 curved lines,
8,606 dashed/unknown lines, 2,514 small faces and sixteen duplicate polygons.
Four pages have no eligible linework; twenty-six are processed without a
network-budget rejection. Many strokes remain open dangles; no gaps are filled.

The controlled placement comparison uses v3 for both runs: original components
versus the combined recovered feed, with the same thirty sheets, references,
thresholds and pair budgets. Both find the same one provisional placement and
position the same 23 original geometry records. Equivalent-orientation checking
adds this candidate relative to v2, but recovered faces add **zero placement
sheets** in this comparison. The source is catalogued proposed; neither a fit
nor its outline faces establishes present construction state. Twenty-nine
selected sheets remain withheld.

All 587 tests pass; the final sixteen focused tests also cover complete parent
validation, preserved holes, tiny gaps, dashed/curved withholding, noded edges,
provenance tampering, reordered-record determinism, real-PDF recovery/placement,
park-job integration and resume. Recovery and both placement runs return
identical receipts on complete resume; all final feed hashes are rechecked.

See `evidence/alton-linework-recovery-validation.json`, per-page diagnostics in
`evidence/alton-linework-page-recovery.jsonl`, both complete comparison feeds and
a six-face source-trace sample. These are review candidates and add no world
blocks. Physical outline identity/current state, dimensions/materials and
independently checked registration remain unverified.
