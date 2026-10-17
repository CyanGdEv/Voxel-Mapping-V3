# Drawing text and repeated-stroke context

Automatic component inventory v2 adds original-glyph context for native cycles
and a residual raster search after repeated narrow-stroke screening. It addresses
two observed Wicker problems: level/callout text backgrounds were presented as
unclassified rectangle cycles, and repetitive hatch strokes exhausted broad
jamb-pair searches. This is deterministic drawing-context screening, without a
trained semantic model or accepted physical building/aperture classification.

## Running and reviewing

The existing opt-in `drawing_view_components` stage enables the context passes.
No new hand-entered crop, trace or exclusion list is needed:

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-stroke-context-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-stroke-context-job.json --output output/stroke-context-audit.json
```

Area/controller contracts advance to v7/v5. Use a fresh output directory for
older area jobs. The example includes the earlier checksum-pinned acquisition
catalogue; the retained real-source test used verified originals offline.
Per-view component JSON retains the raw scan and adds `repeated_stroke_context`,
`residual_raster_scan`, `residual_raster_hypotheses` and
`native_cycle_text_context`. The area summary exposes each residual/text status,
counts and withheld passes. Inputs, implementations, runtime dependencies and
all output files remain hash-bound and checked on cached replay.

## Native text context

Whole original native labels are checked against the original-font glyph screen.
Exact bounded grammars identify numeric labels, level captions and W/D opening
references. Each label retains its original text, trace and character indices,
font/glyph screen, native box, every intersecting cycle and box overlap fractions.
Hidden glyphs cannot support a context link. A complete label must lie inside
the source-view candidate; its whole text is screened even when its native box
crosses a cycle.

Font metric boxes can extend beyond their white background polygons. The adapter
records `whole_label_box_contained` and `label_box_crosses_cycle` separately;
it does not move either geometry or claim that crossing metrics prove enclosure.
Visible numeric/level text overlap identifies drafting context, rather than an
opening type. A real opening can also contain a printed reference. All original
cycles, overlapping alternatives and source-side proofs remain; none is selected
or deleted by this context pass.

## Repeated strokes and the residual search

The original broad scan still runs under its existing 512-group, 8,192-pair and
100,000-check limits. Its successful results and whole-pass withholding remain
unchanged. A separate bounded context pass inventories complete original vertical
runs at thresholds 220 and 235, with at most 4,096 groups per threshold. It does
not form all jamb pairs.

The layout heuristic looks for at least six narrow strokes, each at most three
pixels wide and 24–700 pixels high. Consecutive start pitches are 2–16 pixels,
within one pixel of the sequence's first pitch; strokes have at least one blank
column between their extents. Nine overlapping integer endpoint partitions retain
at most two pixels of top/bottom spread, without transitive clustering, snapping
or moved endpoints. All detected sequences and their source-group indices remain.
The pass is bounded by 100,000 checks and 4,096 sequences per threshold; exhaustion
discards every partial variant and prevents residual screening from using it.

These are threshold-specific layout hypotheses. Repeated mullions and other real
structural details can satisfy them. No cladding, hatch material or physical role
is accepted, and no training labels are created. Excluded groups remain in the
original group tables and lattice proofs.

The residual scanner excludes those complete groups only as jamb proposals.
Before using an exclusion, it verifies the original dark run, both light endpoints
and the full adjacent-column group extent. Forged, cropped, partial-width or
duplicate groups reject the search. Head support always uses the original pixels;
there is no whitening, line removal, interpolation or gap repair. The indexed
scanner retains all supported threshold-pair alternatives among the remaining
jamb groups, using its original budgets.

Residual results declare `search_scope: residual_jamb_groups_only` and
`complete_unscreened_inventory: false`. They cannot stand in for a complete broad
scan, and excluded patterns must be revisited when evaluating repeated real
openings. Native/pixel/nominal transforms and crossing statuses remain explicit.

## Retained Wicker results

| Elevation | Broad scan | Residual families | Residual status | Text-context cycles |
| --- | --- | ---: | --- | ---: |
| South-east | Pair budget withheld | 18 | Completed in residual scope | 5 |
| South-west | Run-group budget withheld | — | Run-group budget withheld | 9 |
| North-west | Pair budget withheld | 192 | Completed in residual scope | 7 |
| North-east | 2,520 families | 29 | Completed in residual scope | 7 |

The new pass retains 2,477 original threshold-specific stroke groups and identifies
865 group occurrences for residual exclusion. All 28 native rectangle cycles have
visible numeric/level glyph context, through 30 original-glyph links. This prevents
their bare rectangle counts being mistaken for an identified opening inventory;
their physical roles remain unresolved.

Across three completed residual scans, all 239 family transforms reproduce from
their original pixel bounds. The south-west scan remains withheld. The three broad
passes retain their previous withheld statuses, so `all_requested_passes_completed`
stays false. Every original component, region geometry, wall band, native rectangle
and broad raster result matches the PR #37 baseline (apart from scanner version).
All six new inventory files match a fresh independent replay.

Receipts are under `docs/evidence/stroke-context/`. The audit can additionally
compare a prior pack with `--baseline /path/to/pr37/component-pack`. Original PDFs,
full component proofs and original-source crops remain outside Git and are included
or referenced by the separate review bundle.

Next: resolve the remaining south-west raster complexity, distinguish real repeated
openings from texture and assign physical boundary roles with independent evidence.
Cross-view dimensions/state, registration and datum still gate park reconstruction.
This pass produces zero accepted physical components, world blocks or training labels.

The final local suite passes **1,562 tests**, including 10 new context regressions.
The related focused suite passes 30 tests.
