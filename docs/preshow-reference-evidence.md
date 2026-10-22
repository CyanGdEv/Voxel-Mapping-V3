# Preshow source references and cardinal elevations

This increment recovers the dedicated elevations for the secondary roof candidate
from the [roof topology review](roof-source-topology.md). It fixes source parsing
and view layout before deriving further geometry from neighbouring shop views.
No physical building identity, new mesh or world placement is accepted.

## Original source recovered

The repository already records **2967-30 Preshow Elevations P1 FINAL**, attachment
163938, in `evidence/wicker-architectural-extra-sources.json`. The recorded
same-resource HTTP URL returned 516,394 bytes on 22 October 2026 with the exact
previously retained SHA-256:

`253b79f214ab673f5ff868d0be5e9d306770ea29089f1dccf012e3a797f4668f`

The corresponding HTTPS request returned HTTP 503. No attachment ID was guessed,
no new checksum was substituted and no changed source was accepted. The new
catalogue preserves both the canonical HTTPS URL and pinned recorded transport.
Acquisition receipts are under `docs/evidence/preshow-reference-evidence/`.

The numbers 26, 30 and 42 in the roof's circular references identify drawing
sheets. They are **not roof pitches**. The recovered sheet has four numbered
captions: 5 South, 6 East, 7 North and 8 West, each with its own 1:100 scale claim.

## Parser and layout fixes

The shared numbered-caption grammar now supports cardinal directions as well
as the existing N.East/N.West/S.East/S.West forms. Exact caption matching,
original glyph screens, adjacent-scale uniqueness and source sheet identity
remain required. Prose, standalone numbers and invalid scales do not become
captions, directions or pitch measurements. Both view-discovery and component
cache contracts pin the new grammar's source code.

The preshow's north and west captions have staggered baselines. The old layout
placed the west caption in a separate shallow band, retaining its title while
omitting the artwork. The new row helper checks disjoint caption columns against
the original composited raster. It excludes the normal blank caption margin
(two original caption heights) before looking for an eight-PDF-point white
horizontal corridor. A genuine corridor keeps rows separate. Without one,
disjoint columns form a staggered-row hypothesis; captions in the same column
are never merged by this rule. Original pixel windows, every white run, source
scale and grouping decision are retained. Padding below a merged row uses actual
caption height rather than the total stagger distance.

This remains a layout heuristic. Crops and paper scale claims do not establish
physical scope or surveyed scale. Whole source objects retain their coordinates;
crossing objects are not clipped into a view. The four new crops retain 67, 79,
63 and 42 whole original source objects respectively, including the west artwork.

## Original side-arrow references

The complementary reference pass finds an original four-cubic circular outline
and both whole straight strokes of an outward V head. Each arm's base must lie
within 0.3 PDF point of the circle radius, the tips must meet within 0.25 point,
and the original numeric index must lie beyond that head with the same reading
direction as the sheet number. Exact duplicate strokes share geometry but retain
every original path witness. Competing heads/indices, missing identity and
failed glyph screens remain held. Clipped fill rectangles are not treated as
arrow shapes. Marker clipping and physical semantics remain unverified.

All thirteen circle/head candidates remain. Six have exact available
project/sheet/view targets: three shop views and **three additional preshow
views (5, 6 and 8)**. The north reference to 30/7 remains held by the original
glyph screen. Two visible references to sheet 42 lack loaded targets. Five
reference visibility/identity holds remain overall. Missing/duplicate target
keys never select a nearby or similarly named view.

All 28 source-connected plan candidates are checked against all thirteen heads:
364 diagnostics. The finite diagnostic line runs from the circle centre through
the original tip, with two symbol radii of explicit extra reach, and is tested
against an assumed whole-rail envelope. It is not an extended source stroke,
physical footprint or accepted assignment. Visible preshow references 5 and 8
overlap the previously position-consistent candidate; held reference 7 also
overlaps other competing line templates and remains held. No residual ranking
or visibility override turns these diagnostics into physical identity.

## Remaining geometry work

The dedicated source is now available for extracting eaves and ridges. It
contains a split **Preshow Top Level +183.30** label which the current single-line
level grammar does not bind to its marker. The source also shows Undercroft,
Shop and Ride Exit levels. Their presence does not establish the secondary
roof's floor role or a vertical datum. The next extraction must retain the
separate glyph lines, bind their own marker and compare source heights before
constructing a mesh. The 0.50376 m rail tails and full-depth/transition geometry
from the previous review remain unresolved. The old binary/SW holds and main
roof are unchanged. World blocks, accepted physical components and training
labels added: zero; semantic ranker remains untrained.

## Reproduce and inspect

Restore the previous three originals and the fourth PDF at its pinned recorded
URL. The existing evidence-acquisition adapter can use the added catalogue's
canonical URL, expected checksum and same-resource transport. Build offline:

```bash
python -m scripts.build_roof_reference_evidence \
  --topology TOPOLOGY --components COMPONENTS --views VIEWS --corpus ORIGINALS \
  --source-catalogue examples/wicker-preshow-reference-catalogue.json \
  --additional-pdfs ADDITIONAL_PDFS --output OUTPUT
python -m scripts.audit_roof_reference_evidence \
  --evidence EVIDENCE --topology TOPOLOGY --components COMPONENTS \
  --views VIEWS --corpus ORIGINALS \
  --source-catalogue examples/wicker-preshow-reference-catalogue.json \
  --additional-pdfs ADDITIONAL_PDFS --output audit.json
python -m scripts.render_roof_reference_evidence \
  --evidence EVIDENCE --views VIEWS --corpus ORIGINALS --output review.html
python -m unittest tests.test_roof_reference_evidence \
  tests.test_drawing_view_candidates tests.test_drawing_views \
  tests.test_architectural_view_layout -q
```

The offline HTML embeds the original roof crop, all four additional source
crops and full evidence in lossless gzip. Inspect every source marker, connected
plan candidate, failed/missing target and glyph hold. The dashed aim line is
explicitly diagnostic. Selecting an unmatched additional view is labelled as
inspection, not a reference match. JSON export returns the original bytes.

The builder replays the complete original plan topology and checks its source
pack. Every original/new PDF and input artifact is pinned before and after use.
Integer native trace-map keys are normalized into the public JSON model before
cache comparisons. Bounds: four distinct additional documents, four pages total,
20 MB per PDF, existing 10,000 parent/20,000 view-source limits, 128 side-reference
candidates, 100,000 charged checks (56,602 in this case), and 32 MB compact JSON.
A source/work overflow discards all candidate views, links, diagnostics and crop
pins. Original crop renders remain unchanged; source PDF bytes are not bundled.

The independent auditor freshly rebuilds the evidence and verifies original
circle curves, all 60 arm-paint witnesses, thirteen heads, four caption traces,
the staggered-row raster window, all thirteen exact-key joins, all 364 diagnostic
intersections with separate convex clipping arithmetic, and eight crop artifacts.
The preceding topology audit is rerun separately to preserve its source digest
and unresolved geometry. Validation receipts and the compressed full-suite log
are under `docs/evidence/preshow-reference-evidence/`.

Validation: **1,737 full-suite tests pass** in 327.349s.
The focused suite passes 41 checks, including fifteen new regressions. Both
original-source audits pass. Browser verification covers 371 interaction states,
all 364 marker/candidate combinations, all four additional views, five unchanged
source-image hashes, exact source strokes, all five visibility holds and
exact-byte export, with zero JavaScript errors.
