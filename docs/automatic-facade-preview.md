# Automatic unplaced façade preview

A downstream review command turns the automatic source evidence into an orbitable
NW Shop façade context. It uses no manual trace, opening rectangle, control-key
list, threshold, wing recipe or placement seed. The existing extraction stage and
all fourteen artifacts remain unchanged. This preview adds no accepted physical
component, world block or training label.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-artwork-controls-job.json --stage extract
python -m scripts.build_automatic_facade_preview \
  --components COMPONENT_PACK --views VIEW_PACK --corpus CORPUS \
  --output output/facade-previews
python -m scripts.audit_automatic_facade_preview \
  --components COMPONENT_PACK --views VIEW_PACK --corpus CORPUS \
  --preview PREVIEW_PACK --output output/facade-preview-audit.json
python -m scripts.render_automatic_facade_preview \
  --components COMPONENT_PACK --views VIEW_PACK --preview PREVIEW_PACK \
  --output output/facade-preview.html
```

`COMPONENT_PACK` and `VIEW_PACK` are the hash-named directories reported by the
area extraction run. `CORPUS` is the run's corpus root, containing `files/SHA.pdf`.
The build command reports `PREVIEW_PACK`, containing `facade-preview.json` and
seven checksum-bound original-PDF crops. The HTML embeds the source images and
needs no network connection. The angle slider rotates a zero-thickness display
plane; the alternative selector keeps every distinct observed opening outline.

## Fixed target checks and new position diagnostics

The five non-Shop references, two fit points, three holdouts and four-parameter
similarity from PR #47 stay fixed. Shop sheet 26 never enters the fit. The new
pass checks each common target annotation against that fixed relation, requiring
unique original occurrences and both existing glyph/whole-view screens. Exactly
coincident repeat paints keep all receipts; distinct repeats stay ambiguous.
It retains failed checks without dropping them or refitting the model.

| Target reference | Fixed-fit residual, PDF points | Result |
| --- | ---: | --- |
| 2967 / 26 / 1 | 0.034743 | Annotation agrees |
| 2967 / 26 / 2 | 0.074448 | Annotation agrees |
| 2967 / 26 / 3, NW | 0.068084 | Annotation agrees |
| 2967 / 26 / 4 | Withheld | Roof marker fails the existing source screen |

The unchanged limits are 0.25 PDF points for position and 1.5% for font/radius
ratios relative to the fitted scale. No residual is emitted for the held marker.
Agreement concerns annotation positions, not physical scale or marker semantics.
Every retained wall corner span is still outside the non-target control hull.

For a target with a passing check and an independently compatible original
corner span, the pass projects the original gap endpoints through the fixed
inverse similarity. The origin is the first original return-corner vertex; the
axis is the transformed original façade axis. It maps the original parent raster
left edge to each end of that span in two separate parity checks. Neither origin
nor scale is fitted to the opening. All parent/child witnesses participate.
Only previously source-symbol-linked alternatives enter this bounded preview.

Wicker retains **12 new position comparisons**: six forward agreements and six
reverse failures. The maximum endpoint residual among the compatible witnesses
is **0.071843 nominal m**, within the unchanged 0.25 m discovery limit. These are
new, separate diagnostics; the earlier furniture-based positions are preserved.
The six overlapping families produce **30 source witness combinations**, with
**seven distinct opening outlines** in one doorway neighbourhood. They are not
seven independent doors. Physical correspondence remains unverified.

## What the door-bottom investigation resolves

The original wider drawing corrects an earlier close-up reading: the line through
the door is **Ride Exit Level +183.42**, at display y=1101.238037 PDF points.
**Shop Level +182.50** is at y=1127.397339, near the drawn base. Earlier commentary
confused those two lines. The extracted level identities and their source
receipts were already correct; no prior level, glyph, jamb or scale artifact is
rewritten.

The raw jamb candidates extend into the shaded ground band. Their common bottom
is **-0.983629 nominal m** relative to Shop Level, so that lower endpoint cannot
serve as an automatically accepted doorstep. A new original-PDF detail crop is
derived from each distinct witness rectangle, with half its width of horizontal
context, one quarter of its height above and half below, rendered at four pixels
per PDF point. No hand-selected source crop supplies extraction coordinates.

A separate diagnostic searches the lower half of the original jamb height through
0.25 nominal m below its end. It tests every row across the central 60% of the
opening at dark thresholds 96 and 128. Every contiguous band with at least 80%
dark support is retained. A candidate is reported only if each threshold has
exactly one band, neither touches the search boundary and their intervals overlap.
Missing, multiple, partial, boundary-touching or crop-crossing results remain
unresolved; no best band is selected.

All seven Wicker crops expose the same source base-band candidate. Its envelope
is display **y=1126.75–1128.25**, or **-0.030080 to +0.022837 nominal m** relative
to Shop Level. This supports a drawn base near that printed level. It does not
establish a physical threshold, finished-floor role or a measured as-built height.
The original head remains **2.146881 nominal m** above Shop Level. The preview
keeps the raw lower endpoint and the separate base-band interval visible.

## Geometry and remaining limits

The mesh is a zero-thickness rectangle matching the original enclosing raster
parent, with an opening outline from each original child witness. It is display
context, not a selected exterior-wall boundary. The roof, actual wall silhouette,
wall thickness, physical opening height and physical bottom remain unset. There
are no carved aperture triangles, inferred sill, filled gaps or repaired joints.
The drawing's printed construction-state claim remains `unspecified`.

Before autonomous Shop building generation, resolve exterior/roof boundaries,
source construction state and physical wall/aperture/floor roles, then establish
independent geographic and vertical registration. Extend source correspondence
to the remaining façades before assembling the complete building. Paths/plazas
and other park components remain subsequent work. The semantic ranker is still
untrained. Planning portal access remains an upstream limitation; this step uses
the same three retained verified originals and claims no new acquisition.

## Reproducibility and bounds

Input reports, all referenced artifacts, original view records, the complete page
view sets, the review dependency chain and original PDF hashes are checked before
and after the build. Every referenced input must appear in its report hash map.
The preview contract pins implementation/dependency hashes, renderer versions,
source reports and the work limit. Deterministic reuse verifies JSON and every
crop; altered saved output is rejected. At most 256 source witness alternatives,
two million pixels per crop, 100,000 work checks and 64 MB total output are allowed.
A work/crop/alternative budget hold discards all partial checks, geometry and crops.

The independent audit replays the preview, rerenders all original crops, verifies
the original target circles, recomputes fixed-marker and position residuals,
checks every mesh coordinate and derives every dark-row run separately from the
original-render pixels. Regression tests cover displaced/hidden/missing/duplicate
targets, font/radius disagreement, base-band ambiguity/boundaries, unknown physical
roles, both parities, deterministic reuse, stale sources and early/late budgets.

The final suite passes **1,663 tests**, including ten new regressions.
All fourteen upstream artifacts reproduce. The independent preview audit checks
eight original circles, three fixed target checks, 60 position witnesses, seven
original crops, 30 mesh alternatives and 14 base-band witnesses. Browser checks
cover 28 interaction states and eight original image hashes with zero JavaScript
errors. Receipts are in `docs/evidence/facade-preview/`.

The downstream [wall and roof profile pass](automatic-facade-profile.md) now
replaces this rectangular context with exact source-cell projection meshes for
the main NW façade. It preserves this preview and its original opening/base-band
evidence, retains both thresholds and leaves physical surface roles unresolved.
