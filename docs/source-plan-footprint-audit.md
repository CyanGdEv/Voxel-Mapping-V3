# Original plan footprint and sheet-layout diagnostics

`voxel-building-data audit-plan --config request.json --output fresh-dir`
checks a named component against exact native plan faces and independently
audits the relative layout of two original sheets. It explains apparent scale
conflicts without altering plan geometry or accepting a physical footprint.

Use `version: "building-plan-audit-v1"`, a `building_id`, and `plan` and
`reference_sheet` objects containing original `path`, SHA256, one-based `page`
and `furniture_bounds_pdf_native`. All bounds use original PDF points, Y up,
including on rotated pages. Supply a literal `component_label` and
`component_bounds_pdf_native`. The component region and plan furniture region
must be disjoint. Bounds are declared review scopes, not authenticated physical
view limits.

`furniture_anchors` is a predeclared list of exact `text` and `role` (`fit` or
`holdout`). At least eight fit and four holdout terms are required, up to 64.
The original glyph screen must support exactly one occurrence of every term in
each declared furniture region. Missing, duplicate, hidden and out-of-scope
terms withhold the entire correspondence. The fit does not remove outliers or
choose terms using building dimensions. Label origins, character/trace indexes,
font sizes and original font screening receipts remain in the report.

The affine fit maps reference-sheet native coordinates to plan-sheet native
coordinates. All predeclared fit and holdout residuals must be at most 0.25 PDF
points. Supported scale singular values are 0.5–2, with at most 1.05 anisotropy
and no reflection. Original font-size ratios must agree with the geometric
layout scale within 1.5%. These tests support a **furniture layout relation**,
not physical drawing scale or surveyed registration. Artwork outside the
furniture region requires extrapolation and may have independent viewport
scaling.

Optional `elevation_width_candidates_m` are declared diagnostic targets, not
verified measurements. If both original sheets have the same visible nominal
printed scale, the report retains original edge lengths and hypothetical
inverse-layout length candidates within 0.25 m of each target. The source edge
coordinates stay unchanged. No target width enters the furniture fit, and no
nearest, largest or best-scoring edge is selected. Matching a length does not
establish object identity or a footprint boundary.

## Exact named enclosure audit

The plan audit recomputes solid native straight edges and exact topology. Every
complete face containing the visible component-label centre is retained.
Arbitrary valid polygons, including concave plans and interior rings, are
supported by this audit; there is no rectangular or axis-aligned requirement.
Crossing-scope and competing faces remain explicit. Label containment identifies
a drafting enclosure candidate, not an exterior footprint or as-built building.
The existing `assemble-views` geometry restrictions are unchanged.

When no exact named face exists, the audit reports that fact. It does not snap
source endpoints, use a convex hull, fill openings or reuse old hand-traced
corners. Native clipped-fill recovery and facing-endcap discovery retain source
gap candidates separately. Scoped corridors carry original parent IDs and
native geometry, with `inferred_closure_applied: false`. Door/window roles and
which gaps belong to an exterior boundary remain unverified.

Original GIA text is retained as a printed area claim, with component assignment
unverified. It is not used to manufacture an outline, choose an affine scale or
force an area match.

`report.json`, `source-network.json`, `source-fills.json`,
`source-fill-endcaps.json` and `review-queue.json` retain diagnostic evidence.
The original PDFs are checked before inspection and again before publication.
Existing output directories are rejected. Native text, geometry, intersection,
provenance and endcap budgets apply. No building specs, training labels, review
outcomes or park-world blocks are generated.

## Real Wicker shop result, 14 October 2026

The original floor and roof sheets independently reproduce the apparent floor
page reduction: 11 predeclared fit terms and four held-out terms give a relative
layout scale of approximately **0.9093**. The maximum held-out residual is
approximately **0.083 PDF points**. This run uses original visible text and
font sizes, not the old manual corner traces or saved normalization matrix.

For the approximately 15.804 m side-wall region target, the unmodified floor
plan had zero full-edge matches in the previous facade trial. The hypothetical
inverse-layout comparison now retains three competing source-edge length
candidates. This supports an explanation of the mismatch; it does not authorize
rescaling the shop viewport, identify a wall or establish physical accuracy.

The visible `Shop` label has **zero exact containing native faces**. The source
network retains 99 enclosed drafting faces elsewhere, plus cuts, dangles and
provenance-budget holds. There are 24 page-wide facing-endcap gap candidates,
six within the declared shop region, and a visible `GIA: 170m2` claim. Those
gaps are not closed or classified automatically. An inferred exterior closure
would need explicit source-bound support distinguishing openings from interior
doors, annotation discontinuities and unrelated walls.

The next geometry blocker is therefore source-supported exterior-boundary and
opening-gap interpretation, followed by viewport-specific scale/state/revision
review. Full shop assembly and geographic registration remain unresolved.

The machine-readable receipt is
[`evidence/wicker-source-plan-audit-2026-10-14.json`](evidence/wicker-source-plan-audit-2026-10-14.json).
