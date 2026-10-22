# Independent non-target artwork controls

Inventory v11 adds `artwork-scale-controls.json`, the fourteenth hash-bound output.
It discovers matching numbered references in original floor/roof artwork and tests
a uniform content-layout relation independently of Shop dimensions, openings,
corners and peripheral page furniture. It does not verify a physical building scale.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-artwork-controls-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-artwork-controls-job.json --output output/artwork-control-audit.json
python -m scripts.render_artwork_control_review \
  --components COMPONENT_PACK --views VIEW_PACK --output output/artwork-control-review.html
```

Area/controller advance to v16/v14. Use a fresh work directory. The same three
known checksum-pinned official originals are used offline for validation. A live
request to the known official application page returned HTTP 503, so no additional
application document or independent figured facade dimension was obtained. The
attempt is retained separately from the successful original-source replay.

## Original references and exclusions

The pass discovers four-Bezier circular references with an original sheet number
inside and exactly one eligible outside view number. Outside text must have the
same reading direction, avoid the circle box, lie within three marker radii and
print a value from 1 to 99. It does not require a diagonal filled-corner symbol;
orthogonal reference markers can therefore supply layout evidence without an
invented bearing. Circle Beziers, original bounds, paint sequence/path index,
both text trace identities and original-font glyph screens are retained.

The entire circle and both text boxes must fit one unique automatic plan view.
All source-page competitor views participate, including deferred views; their
complete page set is bound to the preceding review. Marker semantics and clipping
remain unverified. Source reference matching does not establish physical view or
building identity.

Every active facade target's `(project, sheet)` key is excluded before roles or
fitting. On Wicker this excludes all four Shop references to sheet 26. All other
common keys are retained for review. Failed glyph screens and distinct repeated
occurrences are excluded before role assignment. Exactly coincident repeat paints
with the same original text occurrences retain every source receipt as one
control; points are never averaged and no paint is selected by residual.

Wicker has eight non-Shop common reference keys. Three fail existing glyph checks:
30/7, 42/10 and 42/11. Their failed receipts remain explicit. The pass does not
widen glyph tolerances or infer missing characters from the matching other page.
The five eligible keys are 30/5, 30/6, 30/8, 42/9 and 42/12, within project 2967.
These keys are discovered, not supplied as a literal control list.

## A constrained model and independent holdouts

The hypothesis is uniform content reduction. Its four parameters are one uniform
scale, one rotation and two translations; shear, anisotropy and reflection cannot
be fitted. This differs from the existing peripheral-text affine diagnostic,
which remains unchanged. Marker references are the only fit inputs.

At least five unique eligible controls from two non-target reference sheets are
required. All control coordinates must be noncollinear. After exclusions, keys
are sorted lexically and roles alternate holdout/fit, starting with holdout.
At least two fit controls and three holdouts are required. The original fit-point
RMS spread must be at least five times the largest fit marker radius. No residual
outlier is removed, and a failed holdout is never reassigned as a fit control.

All fit and held-out residuals must remain within **0.25 PDF points**. Original
font-size and circle-radius ratios must each agree with the fitted scale within
1.5%. Scale is bounded to 0.5–2. The particular two-fit-control Wicker fit has no
redundant fit residual; the three independent holdouts are its validation.

| Wicker check | Result |
| --- | ---: |
| Eligible non-Shop controls | 5 |
| Fit controls, discovered 30/6 and 42/9 | 2 |
| Independent holdouts, discovered 30/5, 30/8 and 42/12 | 3 |
| Apparent subject artwork scale | 0.90909983 |
| Maximum held-out residual | 0.072052 PDF points |
| Original corner-pair span diagnostics | 4 |
| Span comparisons against elevation families | 2 |
| Compatible span comparisons | 1 |
| Target spans outside the hull of all controls | 4 |

The NW marker-facing original vertices span **15.834729 nominal m** under this
separate inverse-layout diagnostic, compared with **15.829751 nominal m** in both
original elevation witnesses. The opposite side spans **15.505408 nominal m** and
still fails the unchanged 0.25 m width gate. This is agreement between drawing
measurements, not a claim of physical millimetre accuracy.

The independent controls support a relation elsewhere in the artwork. Every
target corner span remains outside the convex hull of all five controls, so
application to the Shop still requires extrapolation. No new origin or opening
position is emitted, no source geometry is corrected, and no earlier furniture
or wall-return result is replaced. The prior six overlapping forward alternatives
and six reverse failures remain unchanged, along with the same single NW door
symbol. Physical aperture/wall and opening-bottom roles remain unverified; the
original raster jambs still extend below the printed Shop Level. That line is not
silently treated as a door threshold.

Source construction state, physical scale/application and geographic/vertical
registration remain unresolved. Accepted physical geometry, world blocks and
training labels remain zero; the semantic ranker remains untrained. The two
pre-existing broad raster indexed-pair budget holds also remain explicit.

## Bounds, audit and review

The stage binds the inventory/building/level/scale/return chain, complete original
page views and PDF checksums. It retains at most eight page pairs, 256 marker
records per page and 64 eligible controls per pair. Original text/path/numeric
limits and a separate 100,000-check ceiling apply. A budget hold discards every
partial page, pair and diagnostic. The fourteenth artifact shares the cumulative
64 MB component-output cap.

Regressions cover native synthetic PDFs, pre-fit target exclusions, fixed roles,
displaced holdouts, coincident and distinct duplicate paints, glyph failures,
reflection/shear/ratio failures, collinearity/spread, complete competitor views,
changed PDFs, stale chains, early/late budgets and extrapolation without an origin.
The independent audit decodes original Beziers/text/glyphs, solves the similarity
coefficients through a separate least-squares design, checks every holdout and
recomputes every original corner span and elevation witness.

The interactive review embeds both original source crops, shows fit controls and
held-out controls, retains all seven excluded keys and draws original corner spans
against the control hulls. The holdout toggle exposes the exact fit set.

The final local suite passes **1,653 tests**, including 11 new regressions;
57 focused tests pass. All fourteen artifact hashes reproduce. All previous
955/40/6 alternatives, two raw extent rejections, furniture diagnostics, twelve
wall-return position comparisons, seven symbols and six symbol links survive
against PR #46. Browser verification checks two original crops, exact control
coordinates, both fit/holdout states and all four extrapolations with zero
JavaScript errors. Receipts are under `docs/evidence/artwork-controls/`.

The downstream [unplaced façade preview](automatic-facade-preview.md) checks the
excluded Shop annotations without refitting and investigates the original base
band. The wider source identifies the line through the door as Ride Exit Level;
Shop Level is near the drawn base. Raw jamb ends remain separate evidence.
