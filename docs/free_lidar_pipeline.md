# Free and open-data workflow for Alton Towers

This route uses **Environment Agency open LiDAR**, **OpenStreetMap**, and the
free/open-source tools **PDAL**, **GDAL** and **QGIS**. QGIS is for review and
editing; PDAL/GDAL handle point-cloud and raster processing.

## Data we can use

- **Environment Agency survey LiDAR:** downloadable LAZ point-cloud tiles are
  classified into ground and vegetation classes for the published survey
  products. Coverage, point density, survey date and delivered resolution vary
  by tile. Some surveys have 25 cm or 50 cm products; check the tile index
  instead of assuming every park tile has that resolution. The source data is
  published under the Open Government Licence. The EA composite DTM and DSM
  are available as 1 m GeoTIFF tiles. A raster pixel size is not the same as
  the original LiDAR point spacing. [EA survey catalogue](https://environment.data.gov.uk/dataset/2e8d0733-4f43-48b4-9e51-631c25d1b0a9) · [EA 1 m DTM](https://www.data.gov.uk/dataset/01b3ee39-da3f-47b6-83da-dc98e73a461f/lidar-composite-digital-terrain-model-dtm-1m) · [EA 1 m DSM](https://www.data.gov.uk/dataset/cf3f1137-c12b-44a1-a835-e80fe4a60b92/lidar-composite-dsm-2022-1m)
- **OpenStreetMap:** use its paths and building footprints as alignment and gap-fill evidence, retaining ODbL attribution. Treat park paths as incomplete where the imagery, LiDAR or plans show more detail.
- **Planning drawings:** use only documents whose terms permit the intended reuse. Publicly viewable does not automatically mean open-licensed.
- **Aerial imagery:** only use imagery with explicit reuse rights. Do not train or republish extracts from a free-to-view basemap unless its terms allow that use.

## Processing the LiDAR

Install free PDAL and GDAL packages, download the relevant EA LAZ survey tiles,
and edit `examples/free_lidar_export_config.example.json`. Verify the LAS
classification and replace the example date, tile paths and source metadata.
Set `classification_verified` to `true` only after checking that class 2 is
ground and classes 3–5 represent vegetation in those specific files.
The exporter requires a source URL and a recognized open license declaration
(such as OGL, ODbL, CC0 or CC BY); do not include a dataset whose terms do not
permit the intended use.

Run from the repository root:

```sh
python tools/free_lidar_export_bundle.py examples/free_lidar_export_config.example.json
python -m voxel_mapper.geospatial_ingest output/alton_towers_open_lidar --report output/alton_towers_open_lidar/qa.json
```

The PDAL pipeline leaves the original LAZ untouched and produces:

- `terrain_dtm.tif` from verified class 2 ground returns.
- `surface_dsm.tif` using the maximum elevation from configured valid classes.
- `vegetation_points.laz` with the configured vegetation classes retained for
  later canopy reconstruction.
- `manifest.json` with CRS, resolution, source, date and licence provenance.

Raster cells without input points remain NoData. This preserves gaps instead
of inventing vegetation or terrain. For continuous adjacent tiles, use the
same projected CRS, resolution and grid origin/bounds in the config. The
validator then checks the bundle's files, CRS declarations, data roles and
lineage.

## What this does not infer

LiDAR supports terrain height and canopy shape; it does not identify brick,
stone, asphalt, grass or mud. Paving-material labels still need reviewed
imagery with reuse rights or explicitly licensed user-provided imagery. The
current mapper also does not yet turn these exported rasters and point clouds
into a Minecraft world. This step prepares open data for that reader and keeps
the evidence provenance intact.

## Free tool references

- [QGIS](https://qgis.org/) is a free and open-source GIS for inspecting and
  editing the exported layers.
- [PDAL](https://pdal.org/en/stable/) processes LAS/LAZ point clouds and can
  write raster surfaces.
- [GDAL](https://gdal.org/) inspects and converts raster/vector formats.
