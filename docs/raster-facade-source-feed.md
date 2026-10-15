# Source-bound facade region discovery

[The original plan audit](source-plan-footprint-audit.md) now diagnoses the
floor-sheet reduction from held-out page furniture and retains exact named
enclosure and gap evidence. Its hypothetical corrected lengths do not rescale
source geometry or authorize facade assembly.

`voxel-building-data discover-facades` connects the existing original-PDF
material-anchor, contrast-boundary and numbered-view reference extractors to
independent local elevation-region studies. It also scans the original
composited view artwork for unseeded jamb/head correspondences. It does not
assemble an accepted building or import the historical hand-built shop model.

## Request

```json
{
  "version": "building-facade-feed-v1",
  "buildings": [{
    "building_id": "shop",
    "revision_scope": "Declared revised separate-building drawing set",
    "sources": [{
      "path": "original-elevations.pdf",
      "sha256": "<64 lowercase hex characters>",
      "drawing_number": "2967-26"
    }]
  }]
}
```

Run with `--config request.json --output fresh-dir`. Paths are relative to the
request file unless absolute. The declared drawing-number and revision scope
are hypotheses, not authenticated correspondence or per-view drawing state.
Conflicting native drawing headers remain withheld by the reference extractor.
Distinct sheets must have the same claimed project prefix. Different revision
sets must use separate building entries; physical identity across them is not
inferred. Do not include old combined-building sheets in the revised shop set.

Limits are eight building entries, eight source PDFs per entry, four pages per
PDF, 20 MB per original, 4,000 material-anchor records, 256 plan/region reference
pairs, 100,000 dimensional correspondence candidates and 128 MB staged output
per entry. Original hashes are verified before extraction and again before
publishing previews. Invalid buildings are isolated. Failed staged `.partial`
directories are diagnostic only; the final building directory is not published.
Existing output directories are never overwritten.

## Evidence and previews

The `faces` outputs retain every original material-anchor association and all
raw-gray, periodic-stroke and local-contrast screening results. Mixed material
anchors, unsupported source outlines and hatch/threshold disagreement stay
withheld. Accepted contrast-screen results remain **unverified raster regions**.
The adapter never joins their polygons to manufacture a complete facade.

`regions.json` converts supported original regions to native PDF points, Y up,
retaining source record hashes and coordinate transforms. Ring coordinates are
not simplified, snapped or clipped. Interior rings are unclassified raster
regions. Zero rings do not establish that a facade has no physical openings.

Separate `region-view-*` directories contain `building-spec-v1` specs, model
JSON and GLBs for the supported regions in one original elevation view. Each
component uses the generic `detail` role and inferred evidence. The source state
is `unknown`; the nominal paper scale and arbitrary display origin are explicit
assumptions. Roof-surface labels are projected drawing regions, not 3D roof
geometry. All physical, state, dimension, topology and placement gates remain
false. These are separate flat review surfaces, not a closed or assembled shop.
The report distinguishes `region_preview_specs_generated` from
`complete_building_specs_generated`.

`plan-correspondence.json` retains all exact native edge and connected-run
length candidates within the existing 0.25 m discovery window. It retains
missing and competing matches. The window is not a survey accuracy claim;
matching lengths do not prove a footprint edge. The source plan is not stretched
or normalized to fit the elevation. Closed non-rectangular plan correspondence,
depth and vertical datum remain unresolved.

## Unseeded opening scan

Original material anchors and numbered captions identify candidate artwork
windows. The opening scan renders those regions from the **original composited
PDF**, using the checksum-bound raster review transform. It does not read the
historical manual vertical endpoint annotations or opening traces.

RGB is converted to grayscale with NumPy rounding of
`0.299 R + 0.587 G + 0.114 B`. At thresholds 220 and 235 the scanner retains
continuous vertical dark runs, merging only adjacent columns with identical
run endpoints. It pairs compatible runs within two pixels and requires a
horizontal head with at least 90% dark support. Spatial endpoint buckets skip
incompatible pairs without choosing the nearest or largest candidate.

Candidates must agree across thresholds within two pixels. Default discovery
limits are 24–700 pixels of jamb run, 20–600 pixels of inner jamb span, 512 run
groups, 512 candidates and 100,000 pair/consensus checks. Inputs are bounded
uint8 grayscale arrays, at most six million pixels and 3,000 pixels per side.
Budget failure withholds the entire scan, not a truncated candidate list.
No image gaps are closed and no jamb endpoints are manually supplied.

Every candidate retains both threshold checks, original PNG and grayscale
hashes, native-page geometry and pixel sampling bounds. Nominal measurements
are drawing-scale hypotheses; sampling intervals are not physical accuracy
bounds. Rails, cladding and unrelated rectangles can pass these checks. The
scanner does not establish opening type, jamb role, sill, floor datum or reveal
depth, and it does not subtract candidates from a facade automatically.

## Real revised Wicker shop trial

The three original checksum-pinned revised sheets yield 12 material anchors,
eight contrast regions and seven unique **unverified** numbered reference
correspondences. Two regions merge different material anchors and two fail
hatch/region checks; all four remain withheld. The eight supported regions
produce three independent elevation-region specs and GLBs for southeast,
northwest and northeast views. The southwest material-region extraction is
still withheld.

There are 14 plan/region reference pairs. The main side-wall region widths have
no compatible full native edge or connected-run matches on the floor plan at
the printed scales. Some roof-plan length candidates agree, but neither that
agreement nor unrelated short drafting edges establish shop identity. No
rescaling or historical floor-normalization review is used to hide the mismatch.

The opening scan retains competing jamb/head candidates for source-bound review;
they are not accepted doors/windows. Source receipts record scan counts and
budget failures per view. **Complete building specs, training labels and park
world additions remain zero.** Next work must review the material-region and
opening roles, resolve the rejected southwest regions, establish a closed
non-rectangular footprint and cross-view dimensions, and bind per-view state,
scale and revision before assembly.

The original-source trial receipt is
[`evidence/wicker-facade-source-feed-2026-10-13.json`](evidence/wicker-facade-source-feed-2026-10-13.json).

The v2 opening scan adds a separate `adjacent_bay_review_scan` to each rendered
view. The original `scan` remains the all-pairs channel, including its original
budget-withheld outcome. The new channel considers only the nearest compatible
right-hand jamb group (all ties retained), with endpoint agreement within two
pixels. Adjacency is checked before the minimum-width filter: a narrow
intervening bay cannot be skipped to create a larger span. No pixels, jambs or
head thresholds are changed. The same group, pair, consensus and work limits
apply; adjacency-search comparisons also charge the work budget.

These candidates describe atomic drafting bays. They exclude spans across
intermediate compatible jambs, so they cannot replace the all-pairs inventory
or establish full physical opening extent. Both channels retain independent
statuses and candidates with original PNG hashes, native geometry and nominal
scale diagnostics. Existing plan correspondence reads only the original
`scan`; adjacent bays are not silently used as door/window matches.

A fresh original-PDF render of the retained northeast artwork window reproduced
the previous PNG hash. The all-pairs scan still withheld after exceeding 512
supported pairs. The adjacent channel completed with 13,199 checks and one
23-by-45-pixel candidate. This small bay does not resolve the large plan gap
or establish a physical opening. Original source, scope, render and scan hashes
are recorded in `evidence/wicker-ne-adjacent-bays-2026-10-15.json`.

Mixed-material regions now receive a separate source-stroke restoration review.
For every interior stroke box already identified by the contrast suppression
recipe, one trial restores the original contrast pixels inside that box in
both gain variants. The trial adds no ink and makes no gap closure. Boxes from
either variant are retained, with exact variant/family/stroke references; no
nearest separator is selected. Each trial must pass the existing two-gain,
four-threshold, original-outline, dark-fill and hole checks for every conflicting
anchor, and its regions must exclude differently numbered anchors.

The review retains all passing alternatives. The original mixed-material
withholding remains in force, and these alternatives never enter normalized
facade regions, preview meshes or plan/elevation matching. The facade feed
exports them separately in `material-boundary-alternatives.json`, using
unrotated MuPDF page points with y down and the original document/page binding.
The raster review contract advances to v4 to invalidate old cached outputs.

Limits are 32 anchors, 128 distinct source-stroke boxes, 768 million charged
pixel-work units, and 100,000 output geometry coordinates per review. Exhaustion
withholds the whole alternative inventory. The charged work is an explicit
processing bound, not a runtime or physical-accuracy claim.

The original southwest source trial reproduced the native leader chains and
anchor tips, assembled the original image atlas, and tested 113 source-stroke
restorations. Thirteen alternatives passed for the conflicting roof/wall
anchors. They are competing source-supported cuts, including hatch lines;
passing the pixel checks does not identify which line is a physical material
boundary. No southwest facade was accepted and no complete building or
training labels were generated. See the source receipt in
`evidence/wicker-sw-material-restoration-2026-10-15.json`.

Restoration v2 adds neighboring stroke and periodic-family witnesses to every
alternative, alongside exact anchor-linked view/scale width summaries. The
raster contract is now v5. Cross-view width comparisons and ambiguity reports
are documented in `plan-elevation-correspondence.md`; they do not promote the
alternatives into ordinary facade regions or opening matches.
