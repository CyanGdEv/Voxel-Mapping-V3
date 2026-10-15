# Specific plan/elevation correspondence audit

`voxel-building-data compare-plan-views --config request.json --output fresh-dir`
recomputes the original footprint hypotheses and facade evidence, then binds the
focused candidates to numbered source elevation references. It does not reuse
the historical manually traced shop model or select a physical footprint.

Use `version: "source-plan-elevation-correspondence-v1"`, an embedded `footprint`
request in the [footprint hypothesis format](footprint-closure-hypotheses.md),
and an embedded `facades` request in the
[facade source-feed format](raster-facade-source-feed.md). Exactly one declared
building ID must agree across both inputs. All original plan/reference/elevation
PDFs are rechecked before final publication. Output is staged in `.partial` and
existing outputs are rejected. The entire evidence package is limited to 128 MB.

## Drawing references and facing-boundary hypotheses

Original native Revit-style reference circles, filled corners and visible view
numbers produce target project/sheet/view keys. The circle and corner centres
are transformed into the original plan's native coordinates, Y up. Their vector
provides a **drawing-direction hypothesis**, not certified camera semantics,
building identity or national-grid bearing.

The auditor retains all isolated outer-boundary ray hits with facing segments
within the configured angular window, default at most five degrees. It does not
choose the nearest wall. Markers inside an enclosure and overlapping/tangential
ray geometry remain withheld. The candidate's original outline is unchanged.

Each facing segment provides a projected extent and local coordinate hypothesis.
Only region evidence with the same project/sheet/view key is compared. Every
material-region width remains separate; roof surfaces, lower wall strips and
main wall regions are not pooled as interchangeable full-facade measurements.
Width matches remain partial region correspondences with complete facade
identity unverified. The default discovery tolerance is at most 0.25 m and is
not a physical accuracy claim.

The provisional inverse furniture-layout relation can enter diagnostic plan
projections only when both original sheets have the same supported nominal
printed scale. It never changes plan or elevation geometry and does not certify
viewport scale application, state or revision correspondence.

## Source paint sidedness

The audit also retains original nonwhite fill boundaries near each ray hit,
with original fill IDs, paint sequence, clip references and geometry. The
neighbourhood is at most 0.25 **PDF points**, a source-paint discovery window
distinct from the metre width tolerance. Actual boundary separation and exact
coincidence status are recorded; no vertex is snapped to paint.

Two 0.1-PDF-point probes test paint on the enclosure's interior and exterior
sides. Exterior-side-only paint supports an inner-paint-edge hypothesis;
interior-side-only paint supports an outer-paint-edge hypothesis. Other patterns
remain ambiguous. These are source topology observations, not physical wall or
clipping/visibility certification. Full parent paint extents are compared with
the specific elevation regions separately; neither the paint polygon nor its
extent is substituted for an exterior footprint.

## Opening positions and voids

Only explicit gap IDs supporting the candidate boundary are projected onto
eligible facing planes. Gap direction and plane-distance discovery checks are
retained. Original unseeded raster jamb/head candidates are transformed from
their source page coordinates into the elevation's original display frame.

For each specific source region, the audit compares opening width **and both
position endpoints**. A width-only match does not pass. Both elevation-X
orientations are retained rather than silently choosing a reversal. Region
coverage, whole-facade width agreement and physical correspondence remain
unverified. Missing, nonunique and budget-withheld opening scans cannot provide
opening matches.

Interior rings are exported as unclassified drafting voids. They are not filled,
converted into doors/windows or assigned a shaft/interior/context role. No
physical or training label is generated from successful geometry checks.

Per-candidate limits are 32 marker candidates, 128 source regions, 32 opening
views, 4,000 gaps/paint fills and 100,000 charged checks. Exceeding the work limit
discards the candidate's whole correspondence list. Tolerances and work limits
can only be reduced through `options`. The upstream source, topology, raster,
candidate and output budgets still apply.

## Original Wicker result

The six pooled-dimension-compatible candidates yield four original plan markers,
36 eligible marker-ray frames and 18 partial region-width matches. Specific
comparisons expose the pooled-width limitation: the main southeast and northwest
wall-region widths differ from the candidate enclosure spans by approximately
0.266 m, outside the 0.25 m window. The pooled matches came from a southeast
lower strip or northeast roof region, not verified main facades.

The southeast source paint span is approximately 15.848 m, compared with the
15.804 m specific wall-region width. The source-sidedness probes support an
inner-paint-edge hypothesis for that candidate boundary. Across the six
candidates there are 12 compatible source-paint/region width comparisons. These
paint extents are still not complete wall or exterior-footprint evidence.

Northwest source-paint widths remain inconsistent. Southwest material regions
remain withheld, and northeast opening scanning is budget-withheld. There are
**zero opening-position matches**, zero selected physical footprints, zero
complete building specs, zero training labels and zero park blocks. This audit
does not prove that the real building lacks openings; its source correspondence
requirements remain unresolved.

Next work must distinguish inner and outer wall traces with source-bound support,
resolve southwest facade regions and northeast opening evidence, and establish
complete view correspondence. Viewport scale, per-view state and revision still
require review before assembly.

The original-source receipt is
[`evidence/wicker-plan-elevation-correspondence-2026-10-14.json`](evidence/wicker-plan-elevation-correspondence-2026-10-14.json).

Source paint boundary tracing now records every original ring segment parallel
(within the existing five-degree bound) to each eligible marker frame. Each
record keeps part, ring and segment indices, unchanged native endpoints,
diagnostic projected interval and signed offset from the frame plane. Both
sides, interior rings and disconnected parts remain separate; there is no
joining, buffering or replacement footprint.

Midpoint probes 0.1 PDF point along the actual segment normal classify paint
as inward, outward or ambiguous relative to the marker-facing plane. These
are source-paint side candidates, not physical inner/outer wall roles. Narrow
paint, overpainting, clipping and unknown drawing semantics still require
review. Segment traversal shares the correspondence work budget; exceeding
it discards the whole candidate's partial views.

The retained original-source extraction replay produced 72 segment records
across six competing candidates: 36 inner-facing and 36 outer-facing. These
counts include repeated witnesses across alternative candidates. The replay
checked the original plan hash and recorded all retained input hashes in
`docs/evidence/wicker-source-paint-tracing-2026-10-14.json`; it did not freshly
extract the facade sources. No complete footprint, wall role, opening match
or training label was promoted. Remaining work is to establish wall continuity
and scope, resolve the northwest width discrepancy, and recover supported
southwest facade and northeast opening evidence.

Exact wall-run continuity review groups traced segments only when they share
identical original endpoints, are exactly collinear, and belong to the same
source part, ring and paint-side candidate. Original segment lists remain
unchanged. Small gaps, bends and separate rings cannot be bridged. Pair checks
and per-region run comparisons charge the existing whole-candidate budget.
Whole-fill width counts remain separate from the new continuous-run counts.

Original retained extraction replay found 72 runs across six alternatives
(12 per candidate), with 36 partial-region width comparisons within the
existing tolerance. The southeast outer-facing run spans approximately
15.842 m and its long inner-facing run 15.822 m. Northwest runs instead expose
13.688/13.694 m long boundaries and separate 0.797 m short boundaries; they
cannot be combined into the 15.804 m main facade by bridging gaps. Some match
the narrower base region, which does not establish complete facade identity.
The northwest main-wall discrepancy remains unresolved. Receipt:
`docs/evidence/wicker-source-wall-runs-2026-10-14.json`.

Restoration alternatives now have a separate numbered-view width audit. Each
review must link every conflicting anchor to exactly one original material
record with the same document, page, number and target point. All linked
records must agree on the numbered view and nominal printed scale. Missing,
duplicate or cross-view associations remain withheld. Source page rotation
maps each unchanged restoration polygon into display coordinates before its
nominal width is measured; the plan furniture transform is never applied to
the elevation.

`compare-plan-views` compares these widths against every eligible marker frame
in the same view, retaining all residuals. It groups compatible alternative IDs
by source review, frame and material number. Multiple compatible alternatives
are explicitly reported as ambiguous. A unique width match still cannot
certify a physical boundary or complete facade. The new comparisons are
separate from original region matches and opening-position matches and charge
the existing whole-candidate correspondence budget.

Restoration v2 also records periodic-family spacing, stroke count, source
indices and neighboring original stroke boxes for each separator. This is
source repetition evidence, not verified hatch identity. Raster contract v5
invalidates cached reviews missing these witnesses. The source facade feed
retains its raw restoration pages and adds `view_scoped_reviews` with source
review and region geometry hashes.

The fresh original-source run retained all 13 southwest alternatives. Every
wall-region span is 11.6416667 m and is compatible with both southwest frames
for each of six competing footprint candidates: 156 width comparisons pass,
but all 12 wall comparison groups remain ambiguous. Each alternative has an
original periodic-family witness. Roof regions have no compatible whole-plan
width in this trial; their potentially partial extent prevents treating that
alone as a physical rejection. No separator, opening, footprint or complete
building was accepted. Source and output hashes are recorded in
`evidence/wicker-restoration-view-ambiguity-2026-10-15.json`.

Indexed opening evidence is queried separately from expanded opening matches.
For every eligible plan gap and same-view source region, the original
pixel/native/display transforms must establish a positive axis-aligned
mapping. Document, page, view, PNG hash and indexed-scan hash bindings must be
present. A width-bin query retains every compatible consensus family; the
existing width and both horizontal-endpoint residual checks then retain both
elevation-X orientations where supported. Query work shares the candidate's
existing whole-candidate budget, with all partial views discarded on exhaustion.
Source family and threshold-pair indices remain in every match. No vertical
sill/head datum or physical door/window identity is inferred.

The fresh original-source run produced 180 indexed width/horizontal-position
matches across six competing footprints, all relative to a roof-class source
region. Expanded opening matches remain zero. These are competing drafting
hypotheses: component identity and independent vertical alignment are still
required before any could become a physical opening. No complete building or
training label was generated. The original-source receipt is
`evidence/wicker-indexed-openings-2026-10-15.json`.
