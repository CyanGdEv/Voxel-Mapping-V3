# Mixed-source footprint enclosure hypotheses

`voxel-building-data propose-footprint --config request.json --output fresh-dir`
recomputes original plan evidence and combines exact solid strokes with supported
clipped-fill boundaries. It then enumerates explicit source-endcap corridor
alternatives. These are drafting enclosure candidates, not accepted exterior
footprints, physical opening labels or complete buildings.

The request uses `version: "source-footprint-hypotheses-v1"` and an embedded
`plan_audit` request in the [existing plan audit format](source-plan-footprint-audit.md).
It accepts optional `options` which can only reduce the default budgets.
Original source files, visible labels, printed scale and furniture correspondence
are recomputed; historical hand-traced shop outlines are not imported.

## Source-only and inferred topology

The previous named-face audit used exact native stroked lines. The new channel
also uses opaque, supported straight native fill boundaries, including retained
clip intersections. White fills are excluded from this channel because they can
be text masks or overpaint. This exclusion and the source primitives outside the
declared scope remain explicit. No source geometry is clipped to fit the scope.
Paint visibility, physical wall role and completeness remain unverified.

Each baseline enclosure keeps source edge IDs or source fill IDs, polygon/ring/
segment indexes, paint sequence and clip-source indexes. Boundary intervals
retain their source support. A 1e-7 PDF-point epsilon compensates provenance
overlay only; it never enters network construction. Source vertices are never
moved, snapped or fitted to a rectangle.

Every scoped gap corridor must use the exact four original cap endpoints, with
both caps supported by their retained parent fill boundaries. Corridors are
**inferred alternative edges**, not repairs applied to the source. The baseline
and every permitted gap subset are polygonized separately. Competing polygons,
interior rings, active gap sets and boundary gap dependencies remain explicit.
Identical shapes from different trials retain their trial sets.

`gap_effects` compares each single-corridor trial with the baseline. Effects are
`creates_named_enclosure`, `changes_existing_named_enclosure` or
`no_named_enclosure_change`. These topology observations do not distinguish an
exterior opening from an interior door, annotation or unrelated fill region.
No automatic door/window label or physical footprint selection is made.

Limits are six scoped gaps, 64 trials, 10,000 source segments, 500,000 work checks,
4,000 faces per trial, 2,048 boundary provenance links per candidate and 128
distinct candidates. Source polygon/ring vertex and noded-network budgets also
apply. A budget or incomplete-provenance hold discards the entire hypothesis
list. Staged output is limited to 128 MB. Source changes prevent publication of
the final directory; diagnostic `.partial` directories remain separate.

## Measurements and previews

`hypotheses.json` preserves the original unrotated source frame and native PDF
geometry, Y up. Raw area and extent dimensions use the nominal printed scale.
Minimum rotated rectangles are diagnostic extent measurements only; they never
replace a candidate outline.

Inverse furniture-layout extents are reported only when both sheets have the
same supported nominal printed scale. Matches to the declared elevation-width
targets remain hypotheses, not physical accuracy or identity checks. Neither
the furniture transform nor the target widths change source geometry. All
competing matches are retained; none is chosen by closest width or GIA.

No-corridor baseline candidates can produce standalone planar `building-spec-v1`
and GLB previews using the generic `detail` role, unknown source state, nominal
scale and arbitrary local zero. Original interior rings are retained. These are
source drafting-enclosure previews, not floor plates or assembled buildings.

The preview mesh explicitly audits numerical sliver omissions required by the
existing mesh validator. Only triangles at or below its 1e-20 squared cross-
product threshold can be omitted, with at most 1e-8 m² total omitted area. Their
indexes and total area remain in `preview_mesh_numerical_review`. The source
polygon is not modified, and such a preview is marked as not an exact polygon
mesh. The real trial omitted one triangle with approximately 1.44e-12 m² area.

The source review queue is hash-bound to the complete hypotheses. Its outcome
is `null`; closed topology and successful preview export are not correctness
labels. No candidates enter the ranker as accepted physical buildings.

## Wicker original-source result

Adding supported fill boundaries to the stroked-line channel produces one
source-only closed drafting enclosure containing the visible `Shop` label.
It has 247 exterior coordinates, seven unclassified interior rings and 436
boundary provenance links. Its nominal area is about 151.262 m².

The six scoped endcap corridors produce 64 trials and **48 distinct named
enclosure candidates**. All six single-corridor trials change the existing
enclosure rather than create a missing one. Physical gap roles remain
unclassified. This demonstrates why adding all six corridors cannot establish
a unique exterior footprint.

The source-only enclosure's nominal diagnostic extents are approximately
18.767 × 10.436 m; the inverse-layout hypotheses are approximately
20.648 × 11.471 m. Its long extent conflicts with the known elevation-region
targets. A closed drafting enclosure can therefore include context or attached
geometry and cannot be promoted to the shop footprint just because it contains
the label. All alternatives and their dimension checks remain available for
source-bound exterior-boundary review.

Six alternatives match both diagnostic extent axes against the declared target
width list. Their IDs are retained separately in the report. These matches use
the unverified inverse-layout relation and do not establish which material/view
each width represents. They are not automatically selected or accepted.

The trial produces one standalone source-enclosure GLB, **zero selected physical
footprints, zero complete building specs, zero training labels and zero park
blocks**. The next blocker is exterior-boundary/void interpretation and matching
the resulting candidate to the elevation evidence, with viewport-specific scale,
state and revision review still required.

The original-source receipt is
[`evidence/wicker-footprint-hypotheses-2026-10-14.json`](evidence/wicker-footprint-hypotheses-2026-10-14.json).

[Automatic source dimension comparisons](source-dimension-feed.md) recompute both feeds in one command and retain every source-linked match and conflict without manual width targets or physical-footprint selection.
