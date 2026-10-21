# Automatic peripheral-sheet scale evidence

[Original wall-return corners](automatic-wall-return-corners.md) now provide a
separate corner-based diagnostic. Wicker's marker-facing source vertices yield
conditional width and position agreement; the earlier span mismatches remain.

Inventory v8 investigates independent source-layout evidence after the raw facade
extent review. It writes `sheet-scale-evidence.json`, an eleventh hash-bound output.
No manual title-block box, literal anchor list, fit/holdout selection, dimension,
building corner or elevation-fit target is supplied.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-sheet-scale-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-sheet-scale-job.json --output output/sheet-scale-audit.json
python -m scripts.render_sheet_scale_review \
  --components COMPONENT_PACK --corpus CORPUS --output output/sheet-scale-review.html
```

Area/controller advance to v13/v11. Use a fresh work directory for earlier jobs.
The example acquires the same three checksum-pinned originals. Validation uses
the verified originals offline. Source PDFs and rendered artwork stay outside Git.

## Independent automatic controls

The stage inventories literal original text in the outer 20% band of each page.
The complete label box must fit the page and avoid the inner 60% rectangle. This
is a fixed discovery rule, not verified title-block semantics. View captions,
scale ratios, categorized architectural notes/levels/areas/dimensions and file
paths are excluded. All occurrences of a literal text across the entire page
count when checking uniqueness, including duplicates outside the peripheral band.

Every independent roof-plan page in the selected inventory is a reference
candidate for each subject plan. Standard PDF page units/crop and original-font
visible same-project sheet headers are required. No reference is selected by its
residual or by how well building widths would agree. All candidate pair reviews
are retained, within a fixed eight-pair ceiling.

Common peripheral terms must be unique and pass their original-font glyph screens
on both pages. Exclusions are recorded **before** assigning roles or fitting.
Between 12 and 64 eligible terms are sorted lexically; every third is a holdout.
All other terms fit the existing affine sheet-layout kernel. At least eight fit
and four holdout anchors are required, with no residual outlier removal. Fit and
holdout residuals must each remain within 0.25 PDF points. Original font ratios
must agree with the geometric scale within 1.5%; reflection, excessive anisotropy
and unsupported scale ranges remain withheld.

These controls establish a peripheral-text layout relation. They do not verify
that building artwork or an individual viewport shares that relation. The stage
retains original origins, fonts, trace/character identities, complete glyph
receipts, role assignments and all held-out residuals.

## Dimensions and source geometry

Original explicit-unit length text and bare numeric text are inventoried
separately, with whole automatic-view memberships. No unit is assigned to bare
numbers and no dimension-line/corner association is invented. In particular,
level numbers and a graphic scale's length label are not figured facade dimensions.
All dimension text remains unassociated with physical components.

When subject and reference nominal view units agree, a separate diagnostic channel
projects every original plan extent vertex through the inverse layout matrix.
The transformed source axis is normalized again, and lengths use the reference
nominal units. Original holes, disconnected parts, all raw extents and the earlier
two raw width rejections remain unchanged. New extreme-vertex proofs and explicit
artwork-extrapolation flags accompany the diagnostic intervals. No transformed
source geometry is emitted or substituted for the originals.

Every original surrounding-family threshold width is compared with each new
diagnostic span at the existing 0.25 m tolerance. Even a compatible diagnostic has
`layout_application_verified: false` and cannot authorize an origin, physical
opening, scale correction, world blocks or training labels. Each comparison emits
a machine-readable evidence requirement for independent figured dimensions and
matching exterior wall corners. These requirements do not claim that a suitable
additional drawing has already been found or downloaded.

## Wicker result

The floor/roof sheets supply **14** shared visible terms: **nine fit anchors and
five holdouts**. Their apparent floor-sheet layout scale is **0.909363**; the
maximum held-out residual is **0.1368 PDF points**. These controls are discovered
automatically, without importing the older manually declared furniture review.

| NW source extent | Raw nominal span | Layout diagnostic span | Elevation frame |
| --- | ---: | ---: | ---: |
| Whole Shop-labelled enclosure, seven holes | 18.762735 m | 20.642507 m | 15.829751 m |
| Whole nearby paint, both disconnected parts | 14.110970 m | 15.524630 m | 15.829751 m |

The nearby-paint discrepancy falls from **1.718781 m** to **0.305121 m**. It still
fails the 0.25 m gate. The page-layout relation explains much of the difference,
but does not resolve the corresponding physical corners, extent identity or
artwork scale. All six source extents require extrapolation outside the fit-anchor
hull. No facade origin or opening-position acceptance is added.

The sheets retain one explicit length text, `10 m`, outside the inferred building
views; it belongs to the page's graphic-scale context and is not a facade size.
The previous 955 broad, 40 reference-scoped and six level-supported alternatives,
two raw facade comparisons and all source geometry remain available. SW's missing
narrower width match, NE's inside-marker hold and both broad scan pair caps remain.
Physical floor/aperture roles, state and geographic/vertical registration are still
unresolved; the semantic ranker remains untrained.

## Validation and bounds

The inventory's 32-view and cumulative 64 MB limits include this channel. Each page
retains at most 256 peripheral occurrences and 256 dimension texts, within the
existing trace/character limits. The stage has a separate 100,000-check ceiling;
early or late exhaustion discards every partial page, pair, diagnostic and evidence
requirement. Duplicate/stale source inventories and automatic views fail.

Regressions use original synthetic PDFs and real raster consensus witnesses to
cover deterministic discovery/roles, interior duplicates, hidden text, displaced
holdouts, numeric/level/area separation, project/unit mismatch, raw evidence
preservation, extrapolation, compatible diagnostics remaining unverified, extreme
vertices, budget discard and saved-JSON audit replay. The audit independently
checks original text/glyphs, least-squares coefficients, all fit/holdout residuals,
original extent vertices and every diagnostic threshold width.

The final local suite passes **1,620 tests**, including 11 new regressions.
The focused suite passes 38 tests. All eleven artifact hashes match a fresh replay;
all prior 955/40/6 alternatives and both raw facade comparisons are preserved.
The browser verifies both original sheet renders, all 28 anchor marks and both
anchor-table states with zero JavaScript errors. Audit, browser and local-test
receipts are under `docs/evidence/sheet-scale/`.
