# Open GIS evidence integration

This branch adds token-free feature service acquisition to the existing mapper CLI. It does not require ArcGIS Pro or a paid basemap.

## Run
```sh
python -m pip install .
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

The following are not yet automatically downloaded or used by this branch: OS OpenMap Local water and woodland polygons, Environment Agency intensity/DTM/DSM/point-cloud tiles, Sentinel-2 10m land cover or multispectral imagery, Overture and Microsoft footprints, WRI canopy height, flood/soil/geology data. Use the existing geospatial bundle intake for supported local exports until their acquisition and downstream adapters are implemented. See [free LiDAR pipeline](free_lidar_pipeline.md).

The evidence registry retains provider URLs and attribution. Preserve those records with any derivative output. Living England and NFI have shared imagery/OS lineage; multiple layers do not constitute independent validation. The query uses a fixed source registry, not arbitrary premium ArcGIS endpoints. Empty intersections do not prove absence. Source availability and positional accuracy still need a live Alton Towers pilot.

## Validation
```sh
python -m unittest discover -s tests -v
```
Mock tests cover complete ID batching, AOI clipping, missing results, feature budgets, building overlap and no extrusion of context layers.
