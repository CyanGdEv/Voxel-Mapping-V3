# Preshow printed levels and partial roof geometry

The dedicated preshow elevation now supplies its own printed-level bindings,
ridge intersections and candidate fascia ends. A separate, opt-in pass combines
these with original roof-plan cap junctions to produce **32 conditional,
unplaced roof patches**. They are alternatives for one source proposal, with
16 variants in each of two printed-level reference frames, not 32 buildings.
This advances the [source reference review](preshow-reference-evidence.md)
without accepting a complete building or changing earlier source holds.

## Split original level labels

The original `Preshow Top Level` and `+183.30` are separate native text
fragments. The complementary parser preserves their original traces, character
indices, glyph origins, bounds and glyph-screen receipts. Following-line pairs
must share font, size, reading direction and rendering style, with a gap of zero
to two font sizes and a left or right alignment within 0.25 font size. Every
compatible pair remains; proximity does not select among competitors.

A separate visible `183300` is consistent only under an explicit, unverified
millimetre interpretation. Conflicting or competing numeric duplicates hold a
pair. A supported binding needs one label candidate, one original datum leader,
one whole-source view scope and consistent source glyphs. Original marker
records and their previous unresolved statuses remain unchanged.

The source produces three split pairs and nine supported source-marker
bindings across views 5/6/7/8. Six printed-level difference checks agree with
nominal drawing scale within the fixed 0.01 m tolerance; the largest residual is
0.00284635 m. Preshow Top Level 183.30 and Undercroft Level 178.00 differ by
5.30 m. These checks establish neither a physical floor nor a surveyed datum.

## Own-source roof measurements

Only an exact available source-view link with a positive retained aim diagnostic
and direction within five degrees of the original plan ridge can propose a
face-on gable context. Orthographic projection and physical correspondence
remain assumptions. View 8 West provides one conditional context; view 5 is
retained as side/oblique and held. The held north sheet reference stays held.

The unchanged original raster slope recipes run at ink thresholds 220 and 235.
All 39 gable intersections remain, including the taller roof behind the front
gable. Original even-column fit pixels and odd-column check pixels are retained.
The separate fascia recipe groups literal original ink columns before predicting
roof corners: at least 16 pixels, a span of 16 to less than 64 pixels, and no row
gap greater than two pixels. It records every pixel and gap without filling or
interpolating them. This handles a single-pixel stroke whose centre can have
zero binary Sobel response without changing the preceding slope extractor.

Both original rail orientations are checked. Every fascia-column combination
within four horizontal pixels of predicted corners remains, including vertical
failures. Conditional support requires all corner-coordinate residuals within
four pixels and apparent left/right pitch difference at most two degrees.
The column tops remain separate measurements; symmetry is not imposed.

The 46 preceding source-supported partial gables are compared using their
original printed Shop Level 182.50. The equation is:

```
own ridge height above selected source level + own printed level
  - old ridge height above Shop Level - printed Shop Level
```

An absolute residual at most 0.25 nominal metre supports this diagnostic. A
shared printed datum between sheets is explicitly assumed. These are related
project drawings, not independent survey controls. Of 3,588 retained height
comparisons, 1,196 agree. The taller roof fails this comparison and gains no mesh.
Of 298 endcap comparisons, 32 agree; endcap agreement alone cannot produce a mesh.

## Patch extent and retained uncertainty

Six horizontal vertices come directly from original ridge and cap endpoints.
Both cap-to-ridge and cap-to-rail gaps must be at most 0.000001 PDF point. No
source point is snapped, repaired or moved. The patch is approximately
8.01792145 m long and 7.84432955 m wide in nominal source units. The original
8.52168484 m rails retain approximately **0.50376339 m tails beyond the caps**;
these tails remain in the evidence and are left unmeshed.

Each alternative has six vertices and four triangles. Continuous planes and
physical roof/fascia roles are assumed. Relative to the printed Preshow Top
Level, ridge candidates are 5.07349–5.08377 m high and fascia-end candidates are
2.81325–2.83489 m high. The Undercroft variants express the same proposal from a
lower printed reference, not an extra storey or separate building. All 48
cross-threshold comparisons agree within four source pixels; shared pixels
are explicitly not independent controls. Both threshold and rail-orientation
alternatives remain in the output.

No complete wing, wall assembly, watertight building, accepted physical
component, world block or training label is generated. The semantic ranker
remains untrained. Earlier binary/SW holds and the existing main-roof model are
unchanged. Physical identity, source state, rail-tail closure, roof joins,
wall roles, geographic alignment and survey datum still require evidence.

## Replay and review

Restore the same four checksum-verified source PDFs and preceding source packs
documented in the parent reviews. No new source acquisition was needed. The
builder freshly replays the preceding reference pass, pins crops, source PDFs,
catalogue, gradient/topology chain and original level context, and checks source
pins again before saving. Its default work budget is 100,000 charged checks;
the original fixture uses 97,889. Overflow clears every partial level review,
context, measurement and mesh. Raster, cap-combination, column, mesh and output
size bounds also apply. Existing cached output must match a fresh result.

```sh
python -m scripts.build_preshow_level_geometry \
  --references /path/to/reference-review \
  --topology /path/to/topology-review --gradient /path/to/gradient-review \
  --components /path/to/components --views /path/to/views \
  --corpus /path/to/original-corpus \
  --source-catalogue examples/wicker-preshow-reference-catalogue.json \
  --additional-pdfs /path/to/preshow-originals --output /path/to/output
```

`python -m scripts.audit_preshow_level_geometry` accepts the same source arguments
with `--evidence` instead of the builder output and `--output` as a receipt path.
It freshly replays the pass, then separately checks original glyphs, marker paths,
relative-level arithmetic, whole Hough groups and source pixels, complete literal
fascia columns, slope intersections, native plan vertices, all endcap/height
comparisons, all meshes and all threshold comparisons. The preceding reference
auditor also passes with the unchanged source digest.

```sh
python -m scripts.export_preshow_roof_patches \
  --evidence /path/to/output/contract-hash --output /path/to/obj
python -m scripts.render_preshow_level_geometry \
  --evidence /path/to/output/contract-hash --references /path/to/reference-review \
  --objs /path/to/obj --additional-pdfs /path/to/preshow-originals \
  --output /path/to/review.html
```

OBJ files use unplaced nominal metres, Z up. Their 17-digit vertex formatting
round-trips exactly to the retained arrays. The offline HTML embeds four original
source crops, the exact evidence JSON and all 32 OBJ exports. It exposes all
source levels and competing gables, original separate fragment bounds, source
pixels, failed checks and a rotatable partial mesh. Browser verification covers
127 states, all 78 gable/level combinations, 32 exact OBJ downloads, four source
PNG hashes, five rotations, control toggles and exact JSON export, with no
JavaScript errors. Independent audit and validation receipts are under
`docs/evidence/preshow-level-geometry/`.

Validation: **1,753 full-suite tests pass** in 539.031s;
all sixteen new focused regressions pass.
