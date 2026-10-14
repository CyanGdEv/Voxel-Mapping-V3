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

[Automatic source dimension comparisons](source-dimension-feed.md) recompute both feeds in one command and retain every source-linked match and conflict without manual width targets or physical-footprint selection.
