# Automatic original door-symbol evidence

Inventory v10 adds `door-symbol-evidence.json`, the thirteenth hash-bound output.
It tests original plan leaf and segmented-swing geometry independently of the
elevation width/position comparison. It supplies a source role cue rather than
certifying a physical aperture, scale or generated wall opening.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-door-symbols-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-door-symbols-job.json --output output/door-symbol-audit.json
python -m scripts.render_door_symbol_review \
  --components COMPONENT_PACK --views VIEW_PACK --output output/door-symbol-review.html
```

Area/controller advance to v15/v13. Use a fresh work directory. The example uses
the same three known checksum-pinned official attachments. Actual validation uses
the originals offline. No source document or reference drawing is newly acquired
in this step; original PDFs and artwork remain outside Git.

## Source geometry

The broad geometry extractor's 12-point minimum omits the short segments of a
tessellated swing. This pass reads original line items directly. Each retains
the original path ordinal, item index, paint sequence, endpoints, stroke colour,
width and complete supported clip-ring receipts. It does not lower the broad
extractor's threshold or replace its evidence.

Only opaque, solid, open, straight stroked paths with supported clipping and no
optional layer or compositing group are considered. The whole path's stroke
envelope must fit the page and every active clip. A crossing path is withheld
whole. Curved PDF primitives and unsupported scopes remain excluded; a missing
symbol is not proof that an opening is absent. Later-overpaint visibility remains
unverified.

Every original gap is reviewed. A candidate leaf must begin within half the
gap-corridor depth plus 1.5 PDF points of either original gap endpoint. This
neighbourhood must be no more than 30% of the gap span. Its length must be
65–120% of the gap span and its direction within 15 degrees of perpendicular.
These fixed native-page discovery tests do not establish physical dimensions.

The leaf's original endpoint is the hinge. No least-squares circle, translated
hinge or inferred intersection is used. The graph follows **exact original
endpoint equality**, with no proximity stitching or snapped joints. It follows
same-style/clip edges with monotonic 1–25 degree angular increments and radial
error at most the larger of 0.25 PDF points and 1.5% of the leaf radius. A complete
source arc must terminate after 4–64 segments, sweep 80–100 degrees and end in
the opposite gap-end neighbourhood. An original continuing arc cannot be cut at
a convenient quarter turn. All supported page edges are considered before whole
symbol membership in an automatic view is checked. No curve is cut at a view
boundary to manufacture a complete symbol. Competing candidates are all retained.

## Wicker result

The original floor page supplies **3,675** eligible source line items. Across
**24** plan gaps, **seven** retain one leaf-and-swing candidate each. The NW
candidate uses one original leaf and **eight** original arc segments, with a
90.202-degree sweep. Its maximum radial residual is **0.1061 PDF points**.
Its hinge is the original leaf endpoint `[797.397644, 582.541748]` in native PDF
coordinates; no source coordinate is moved.

The same NW symbol supports all **six** previously compatible forward position
alternatives. They overlap one opening neighbourhood and share this one symbol;
they are not six separate doors. The existing opposite paint-side width failure,
six reverse position failures and all 60 position witnesses remain unchanged.
The earlier 955 broad, 40 reference-scoped and six level-supported alternatives,
two raw extent rejections and peripheral-sheet diagnostics remain available.
The two pre-existing broad raster scans still hit their indexed-pair budget;
their holds remain explicit alongside the retained residual channels. The new
symbol pass does not widen those caps or mark the full inventory complete.

The pass also retains and glyph-screens the literal page wording:
“(Internal Layout shown for illustrative purposes only)”. This is a source-page
caveat, not an independently verified assignment of that note to each component.
The symbol strengthens a door-role hypothesis. Actual exterior/aperture identity,
bottom/floor roles, source construction state and physical scale/application remain
unverified. These three drawings still supply no figured facade dimension that
independently verifies applying the peripheral-text transform to building artwork.
No world blocks or training labels are added; the semantic ranker remains untrained.

The review embeds the original floor crop and overlays each original leaf, full
segmented swing, hinge and gap corridor. Its enlarged panel changes the SVG
viewing window on the same original crop. Select all seven candidates and toggle
overlays to inspect the source. No fabricated, repainted or generated source image
is used.

## Bounds and validation

The stage binds the upstream inventories, whole automatic source views, original
PDF checksums and complete wall-return report. A separate 100,000-check ceiling
counts source paths/items, gap searches and graph expansions. It also bounds
20,000 page edges, 1,000 items per path, 16 clip levels/vertex branches, 64 arc
segments, 128 symbols per gap and 64 wording records per page. Any budget failure
discards all partial pages, view results and correspondence links. The thirteenth
artifact counts toward the existing cumulative 64 MB output cap.

Regressions cover original synthetic PDFs, short source edges, exact connectivity,
missing/partial/wrong-radius/translated swings, continuing arcs, competing leaves,
style/clip/group exclusions, whole-view membership, stale/duplicate/nonfinite
inputs, early/late budget discard and saved-JSON independent audit. The audit
replays discovery and independently decodes original paths and clip rings, checks
the original hinge, all symbol edges, monotonic angles, radial and gap-end tests,
complete source termination, illustrative text and every correspondence link.

Next: obtain independent artwork-scale evidence and resolve the remaining wall,
opening-bottom and construction-state roles before accepting a physical facade.

The final local suite passes **1,642 tests**, including 11 new regressions;
46 focused tests pass. All thirteen artifact hashes match fresh replay. All prior
955/40/6 alternatives, both raw extent rejections, sheet-layout diagnostics and
twelve wall-return position comparisons are preserved against PR #45. Browser
verification exercises seven options/fourteen overlay states, verifies the original
crop and exact hinge/arc coordinates, and reports zero JavaScript errors. Receipts
are under `docs/evidence/door-symbols/`.
