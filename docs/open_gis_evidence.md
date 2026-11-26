# Open GIS evidence integration

This branch adds token-free feature service acquisition to the existing mapper CLI. It does not require ArcGIS Pro or a paid basemap.

## Run
```sh
python -m pip install '.[gis]'
voxel-mapper --config examples/alton_gis.json --output output/alton-gis
```

Alternatively use `--gis` with an existing GB config. GIS collection is opt-in for backwards compatibility; no extra UK network calls are made for international parks unless explicitly requested. The example bbox is an approximate Alton Towers pilot area, not a surveyed boundary. GIS failures are reported independently; set `gis.required=true` to fail a run if any requested source returns partial/unavailable evidence.

| Source | Role | Placement policy |
|---|---|---|
| OS OpenMap Local buildings | Building footprint | Compare intersection-over-union against existing buildings; isolated footprints are review candidates |
| OS Open Rivers | Watercourse centreline | Context only; no width, water level or bed depth inferred |
| Living England Phase 4 | Habitat | Keep original habitat attributes, not per-block training labels |
| NFI GB 2024 | Woodland/open-area type | Context only; no tree counts or individual canopy geometry inferred |
| NHLE points/polygons/gardens | Heritage location and designation | Context only; designation boundaries are not wall outlines |

`gis-evidence.geojson` is clipped WGS84 evidence; `gis-report.json` records source metadata, lineage, query counts and per-source failures; the existing quality report includes the GIS summary. Existing feature geometry is preserved and annotated with building footprint agreement. Opt-in `gis.promote_missing_footprints=true` permits isolated OS footprints to enter the existing approximate extruder; strict mode rejects this option. No measured height or base elevation is supplied. Do not use these draft blocks as surveyed building shells.

## Other identified open datasets

The following are not yet automatically downloaded or used by this branch: OS OpenMap Local water and woodland polygons, Environment Agency intensity/DTM/DSM/point-cloud tile downloads, Sentinel-2 multispectral imagery, Overture and Microsoft footprints, WRI canopy height, flood/soil/geology data. Use the existing geospatial bundle intake for supported local exports until their acquisition and downstream adapters are implemented. See [free LiDAR pipeline](free_lidar_pipeline.md).

The evidence registry retains provider URLs and attribution. Preserve those records with any derivative output. Living England and NFI have shared imagery/OS lineage; multiple layers do not constitute independent validation. The query uses a fixed source registry, not arbitrary premium ArcGIS endpoints. Empty intersections do not prove absence. Source availability and positional accuracy still need a live Alton Towers pilot.

## Validation
```sh
python -m unittest discover -s tests -v
```
Mock tests cover complete ID batching, AOI clipping, missing results, feature budgets, building overlap and no extrusion of context layers.

## Global raster and local intensity evidence

The Alton and Magic Kingdom profiles now enable `landcover: {enabled: true, year: 2025, required: false}`. The public Sentinel-2 land-cover ImageServer exports one categorical TIFF at its nominal 10 m product scale on a snapped EPSG:3857 grid, with the year explicitly selected. The mapper checks band count, data type, CRS, grid, class codes, byte/pixel budgets and usable fraction; it writes a SHA-256 and provenance to `landcover-report.json`. This is coarse context, not a fine material or tree-location target. EPSG:3857 grid units are projected metres, not exact ground metres. Classes and year are based on the published service directory; a successful mock export is not proof of live availability.

For existing classified LAZ data, set `export_ground_intensity: true` with explicit grid or bounds in the free PDAL/GDAL export configuration. This adds mean class-2 intensity as `ground_intensity.tif` and registers the `lidar_intensity` role. It is not calibrated reflectance and must not be converted to a paving label without training/validation. Actual PDAL execution and live tile downloads remain unverified.

CI: GIS evidence checks installs the optional raster dependencies and runs unit tests. A manual workflow dispatch with `live_pilot=true` queries the Alton vector and land-cover sources without needing Overpass or world export. Reports are uploaded even on a failed acquisition. Workflow dispatch is subject to GitHub availability/default-branch workflow rules; use the documented local CLI as an alternative.


## Metric context and geometry review

Both pilot profiles now enable `gis_context`. This writes `gis-context.npz` (uint8 [channel,row,column], AOI mask) and `gis-context.json` (CRS, affine, channel semantics, hash). Default cells are 5 m; this does not increase the resolution of a 10 m satellite product. Each source has a separate channel: 1 mapped, 0 not mapped (not confirmed absent), 255 unknown. Partial sources only mark positive mapped cells; missing sources remain unknown. Sentinel-2 preserves its class codes with cloud/no-data marked unknown. Source roles and lineage should be read from the GIS report. Context tensors are inputs for future georeferenced chip preparation; the existing RGB trainer is unchanged.

`gis-geometry-review.json` compares exact source polygons with current non-draft mapped polygons in local metres: coverage fraction, unmatched area, IoU, centroid offset and boundary Hausdorff distance. These are agreement metrics, not accuracy against survey truth. `gis-gap-candidates.geojson` contains review-only unmatched polygon parts, never directly voxelized. Paths under woodland are retained, water overlaps are marked for crossing/disagreement review, and overlaps are included in the feature properties. Heritage designations and river centrelines are never promoted to outlines.

OS OpenMap Local is available for free download in GeoPackage/Shapefile format from https://www.ordnancesurvey.co.uk/products/os-open-map-local . Export its SurfaceWater (area) and Woodland polygons as RFC 7946 WGS84 GeoJSON. Supply them in the config relative to the config file:

```json
{"gis_context":{"enabled":true,"cell_m":5,"min_gap_m2":4,"local_polygons":[
 {"id":"os-water","role":"water_polygon","path":"water.geojson","crs":"EPSG:4326","license":"OGL-3.0","url":"https://www.ordnancesurvey.co.uk/products/os-open-map-local","attribution":"Contains OS data © Crown copyright and database right","lineage_family":"ordnance-survey"},
 {"id":"os-woodland","role":"woodland_polygon","path":"woodland.geojson","crs":"EPSG:4326","license":"OGL-3.0","url":"https://www.ordnancesurvey.co.uk/products/os-open-map-local","attribution":"Contains OS data © Crown copyright and database right","lineage_family":"ordnance-survey"}
]}}
```

This is a local export adapter, not automatic national tile downloading. No actual OS water/woodland export has been loaded for the pilot yet. The existing voxel writer still lacks full Minecraft world export, and no network or training benchmark has been verified.
