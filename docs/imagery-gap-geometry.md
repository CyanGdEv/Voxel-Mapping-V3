# Esri imagery for gaps between planning sources

The imagery geometry job adds a second source of draft 2D outlines where planning coverage is missing. It reads retained Esri aerial RGB and available map context, then extracts visible colour-region polygons. Supplied protected planning coverage is subtracted before and after extraction so this job does not replace that geometry.

Towers Street is a useful starting area: the existing resort registry has no verified application association for it. This records the project's coverage gap, not proof that no public planning application exists.

## Run

Choose **Imagery geometry / planning gaps** in the updated desktop source and submit `examples/desktop/towers-street-imagery-geometry.json`, or:

```sh
python -m voxel_mapper.imagery_geometry_research --config request.json --output street-run-001 --cache web-cache
```

A fresh output directory is required. The existing aerial and map caches retain original bytes and metadata. The standalone job does not require a neural training dataset. An optional `imagery_geometry_context` in a research cycle runs the same workflow; see `examples/desktop/towers-street-imagery-cycle.json`. That cycle example separately needs the existing reviewed intake and registered encoder paths.

The geometry job shares a 64 MB / 600 second budget across the normal aerial acquisition and map snapshot stages. Raster size stays bounded by the aerial job's four-million-pixel limit. Up to 512 in-area map references, 512 requested output features and eight MB of candidate vector data are allowed. Very complex individual polygons are withheld with a reason. Cancellation and source hashes are checked. Missing map data leaves imagery-only regions unclassified.

## What the output means

| Output | Evidence and limits |
| --- | --- |
| Paving polygons | Mapped pedestrian polygons/lines seed bounded RGB region growth. Building, water, parking, vegetation, shadow and protected-coverage masks block it. A connected hard surface is no longer promoted in full merely because it touches one walking reference. Missing/incorrect references and occlusion still cause substantial errors. |
| Building regions | Explicit mapped building polygons seed nearby RGB region growth. Resulting outlines describe visible roof-colour regions, not verified ground footprints, roof heights or complete buildings. Multiple regions can belong to one mapped building. |
| Water regions | Explicit mapped water areas seed RGB boundary extraction. Visible islands/holes are preserved. Colour alone does not establish that an unmapped blue surface is water. |
| Queue lines | Retained explicitly tagged mapped centre lines, clipped around protected coverage, with an RGB visibility-support measurement. Widths and unrecorded switchbacks are not invented. Occluded lines stay marked unsupported. |
| Unclassified surfaces | Hard/blue colour regions without enough semantic context. They remain candidates for later comparison/review. |

Map tags provide class hints, not independent proof. Region growth is constrained to a small neighbourhood of each mapped polygon and compatible RGB colours. The actual image region is vectorized; the reference polygon is not simply relabelled as an extracted outline. Existing map relation/hole parsing is reused without guessing missing closures.

The analysis clips to the requested area using the provider's returned image extent. Aspect-ratio expansion of a static map does not expand the requested extraction area. Nodata/transparent pixels, the configured image footer, vegetation and dark/shadow occlusions are not filled in as paving. Median filtering and bounded polygon simplification reduce pixel noise; outputs remain approximate colour boundaries.

## Protect supplied planning geometry

Optionally provide:

```json
{
  "protected_plan_coverage": {
    "file": "protected-plans.geojson",
    "sha256": "<SHA256 of the original file>",
    "crs": "EPSG:4326"
  }
}
```

The file must be a bounded FeatureCollection of valid 2D polygons. Paths resolve against the request JSON. Its original bytes are retained; map/imagery candidates are excluded by a raster mask and exact final vector difference. Tests verify zero polygon area overlapping the protected coverage. This is an explicitly supplied protection mask, not automatic registration or validation of every planning application. Proposed/historic plan state and alignment still need appropriate source context.

Without a protected file, the report says `protected_coverage_supplied: false`. It does not label the whole area as proven to have no plans. Gaps behind trees, shadows, roofs or image limits remain unresolved; they do not automatically become rocks or paving.

## Review files

- `index.html` and `overlay.png`: source imagery with colour-coded candidate regions.
- `paving-overlay.png`, `paving-mask.png`, `paving-candidates.geojson`: separate blue paving review, raster mask and source-pinned polygons. These map-guided results are separate from the RGB neural predictions.
- `geometry-candidates.geojson`: georeferenced WGS84 polygon candidates, class/boundary roles, reference IDs, source hashes and coverage status.
- `queue-centrelines.geojson`: explicitly mapped queue lines and their RGB support status.
- `protected-coverage.geojson` and, when supplied, `protected-plan-original.geojson`.
- `aerial/`: unchanged source imagery, provider/date/accuracy metadata and the colour/material research outputs.
- `osm.xml`: retained original map reference bytes, when available.

These files are research/draft layers. No surveyed registration, accepted source/material labels, neural accuracy gain, 3D structure, world blocks or Windows EXE rebuild is asserted. The existing reviewed orthophoto acceptance rules remain in place. The desktop remembers candidate counts/hashes, and the research cycle preserves source/candidate provenance without retraining an unchanged neural dataset.

## Original Towers Street run (before paving refinement)

The run produced **58 polygon regions**: five paving regions, 32 roof-colour regions associated with 26 distinct mapped building references, one map-supported water region, and 20 unclassified hard-surface regions. Thirty-seven map references intersected the area. No explicitly tagged queue centre line was found in this snapshot, so the queue output is empty. This does not prove that the area has no queues.

The larger paving colour region covers approximately 24,044 ground square metres under the local scale approximation; it includes connected surfaces and is not a verified pedestrian-only inventory. The source image and a coloured overlay make overgrowth/occlusions visible for review. Protected-plan handling was tested on synthetic coverage polygons; no real protected plan layer was supplied for Towers Street.

The initial imagery job retrieved 783,526 bytes; the subsequent geometry run retrieved 250,110 bytes for the map snapshot while reusing the imagery. Current replay is offline. The real 96-pair research cycle reused its existing checkpoint while storing the geometry result. Detailed checks and source pins are in `evidence/towers-street-imagery-geometry-validation.json`.

Attribution: Esri World Imagery and its imagery providers; © OpenStreetMap contributors, ODbL-1.0. Capture-date, source-resolution and accuracy observations remain in the provider metadata and do not establish exact whole-image accuracy or current conditions.

A separately trained RGB/context model can now add paths/plazas, roof, car-park and landscaped-island proposals. See [Aerial semantic training](aerial-semantic-training.md) for its provisional labels, weak held-out results and saved-checkpoint workflow.

## Paving refinement and transfer limitations

The map-seeded paving pass uses several RGB/Lab prototypes from visible map interiors, then grows connected regions within the configured `max_growth_m` neighbourhood (default 3 metres). Line references add a half-metre seed/search allowance; raster cell edges add quantization uncertainty. This is a search window, not an asserted path width. Small closing operations are constrained again by every barrier and the allowed colour mask. Covered/tunnel references are withheld, and hidden paving is not reconstructed. Polygon holes preserve visible grass/planters; these are not verified planter footprints.

The fixed pass was compared against the existing provisional assistant annotations, without feeding those labels into extraction:

| Existing imagery | Paving IoU | Precision | Recall |
| --- | ---: | ---: | ---: |
| Towers Street | 70.39% | 92.56% | 74.61% |
| Wicker-area image | 15.06% | 29.00% | 23.86% |
| Thorpe entrance | 1.12% | 2.25% | 2.19% |

These are **development/transfer comparisons on sparse provisional labels**, not a blind test or independently surveyed accuracy. Unlabelled pixels are excluded from scoring. Map context is extra evidence unavailable to the RGB-only experiment, so the figures cannot be presented as a neural-training gain. All three previews and pinned evaluation inputs are retained in the paving-review download. Towers Street looks substantially better, while the transfer results show that this method is not a general solution. Map/imagery registration, more reliable roof and pedestrian boundaries, and independently reviewed spatial labels remain necessary. Neural weights and their reported held-out scores are unchanged; no world geometry is accepted.
