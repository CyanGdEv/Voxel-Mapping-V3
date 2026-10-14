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
