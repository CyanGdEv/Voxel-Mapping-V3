# Automatic original wall-return corners

[Original door-symbol evidence](automatic-door-symbol-evidence.md) now supplies
a separate plan-role cue for the conditionally aligned NW gap. The source symbol
and illustrative-layout wording do not verify physical aperture identity or scale.

Inventory v9 adds `wall-return-corners.json`, the twelfth hash-bound output. It
traces original facing paint and perpendicular returns, then compares original
paint-side vertices with elevation evidence. It does not merge paints, repair
joints, invent line intersections or fit a corner to an elevation/opening.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-wall-returns-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-wall-returns-job.json --output output/wall-return-audit.json
python -m scripts.render_wall_return_review \
  --components COMPONENT_PACK --views VIEW_PACK --output output/wall-return-review.html
```

Area/controller advance to v14/v12. Use a fresh work directory for earlier jobs.
The same three checksum-pinned originals remain the source; actual validation is
offline. Source PDF bytes and artwork stay outside Git.

## Original paint and corner recipes

The preceding near-ray source paint is the facing-strip candidate. Its original
source-axis span must be at least three times its normal span, with nominal raw
thickness between 0.08 and 1 m. All parts and holes are retained. These are
discovery filters and do not certify wall material, visibility or physical role.

Every same-colour, fully opaque original paint within 0.25 PDF points is considered
as a return. Whole geometry must fit the automatic plan view. Return spans must
have the opposite strip proportions and overlap, touch or lie within the same
0.25-point neighbourhood of the facing strip's normal band and one end. All
eligible returns survive; no nearest or best-width return is selected. Original
boundary distance and exact-contact status are explicit. A nonzero source gap
remains nonzero, including the tiny near-contact joint on Wicker's NW return.

Both marker-facing and opposite paint boundaries are reviewed. A corner must be
an original **exterior-ring vertex** in the source end/side neighbourhood. It needs
an adjacent original edge parallel to the frame axis within five degrees, with
both edge endpoints in the side band. Two 0.1-point midpoint probes must establish
paint on the expected side only. Hole vertices cannot become facade corners.
The recipe retains all admissible vertices and chooses the source-axis extremum
before any elevation-width or opening-position comparison. Tied extrema remain
explicit. No bound corner, inferred intersection or averaged point is substituted.

## Conditional extent and position comparison

Raw nominal corner spans remain separate from diagnostics using the preceding
peripheral-text inverse layout relation. Source axes and original gap endpoints
are projected through the same matrix. No source geometry or gap is rewritten.
Every original surrounding-family threshold width must pass the existing 0.25 m
tolerance before a corner pair supplies a conditional origin.

The parent left pixel edge maps to either source-corner end, retaining both
directions. Every original parent/child witness combination then checks both
opening endpoints against the independently projected original plan gap. Width
agreement alone is insufficient. No translation or scale is fitted to the gap.
The complete original below-level jamb runs and all competing families survive.

## Wicker result

Four original facing-frame reviews produce two facing-paint reviews, four
perpendicular-return links and four original paint-side corner pairs. SE retains
its source corners without a narrower level-supported opening comparison. SW
still lacks the earlier narrower width match; NE retains its inside-marker hold.

| NW paint-side corner recipe | Layout diagnostic span | Elevation frame | Result |
| --- | ---: | ---: | --- |
| Marker-facing original vertices | 15.837297 m | 15.829751 m | Both threshold widths agree |
| Opposite original vertices | 15.507922 m | 15.829751 m | Width mismatch retained |

The marker-facing diagnostic differs by about **0.00755 m**. This is drawing
agreement, not a claim of physical millimetre accuracy. All six overlapping child
alternatives pass the forward position check in every witness. Their maximum
endpoint residual is **0.07227 m**; all six reverse comparisons fail. The twelve
direction comparisons retain **60** original parent/child witness combinations.
These are six alternatives in one opening neighbourhood, not six physical openings.

This provides a first conditional NW facade origin/position correspondence from
original source corners. It remains conditional on the perimeter/return roles,
printed marker semantics and extrapolation of peripheral-text layout to artwork.
The right source joint is near-contact only, with its actual distance retained.
Actual exterior/aperture identity, construction state, floor/bottom roles, physical
scale and independent geographic/vertical registration are unverified. No physical
facade/opening acceptance, world blocks or training labels are added; the semantic
ranker remains untrained.

The previous 955 broad, 40 reference-scoped and six level-supported alternatives,
both raw extent rejections and prior layout diagnostics remain unchanged. No
tolerance is widened and no original source point moves.

## Validation and bounds

The stage binds the full upstream source-review chain, at most 32 unique source
inventories, 4,000 source paints, 64 return candidates and 128 paint-side corner
pairs per facing paint. A separate configurable 100,000-check ceiling counts
original vertices, source candidates, corner tests and correspondence witnesses.
Exhaustion discards all partial frame and diagnostic output. The twelfth artifact
counts toward the cumulative 64 MB component-output limit.

Regressions cover original PDF rings/holes, real raster consensus witnesses,
both paint sides and position directions, proximity without snapping, competing
returns, missing/style/direction/distance/crossing exclusions, required original
edge/side support, threshold disagreement, stale/duplicate/nonfinite sources and
early/late/candidate budget holds. The independent audit verifies original fill
and clip receipts, all 116 source vertices and edge probes, all eligible returns,
eight side-corner choices, four extent witnesses and all 60 position witnesses.

The final local suite passes **1,631 tests**, including 11 new regressions.
The focused suite passes 46 tests. All twelve artifact hashes match a fresh replay;
all prior 955/40/6 alternatives, both raw extent rejections and prior layout
diagnostics are preserved against PR #44. Browser verification exercises four
frames and twelve paint-side/direction states, verifies four original crop hashes
and exact corner coordinates, and reports zero JavaScript errors. Audit, browser
and local-test receipts are under `docs/evidence/wall-returns/`.
