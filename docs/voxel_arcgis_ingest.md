# ArcGIS 3D export workflow for Voxel Mapper V3

This workflow uses **ArcGIS Pro to extract and export evidence** and **ArcGIS
Earth to inspect and compare it**. Earth is not the extraction engine. The
current mapper code has evidence scoring and ground-surface label resolution,
but it does not yet ingest LAS/GeoTIFF/feature layers into a Minecraft world;
the ArcGIS exporter and intake validator below establish the GIS handoff and
report what still needs a world-generation implementation stage.

## Extract in ArcGIS Pro

1. Keep the source imagery, LAS/LAZ and planning files in a projected metric
   coordinate system covering the resort. Record the source date, stated
   horizontal/vertical accuracy, imagery pixel size, CRS and vertical datum.
2. Inspect/classify LAS/LAZ points. Export the classified source and create a
   bare-earth DTM plus a surface DSM. Preserve the original point classes and
   do not flatten the park to a single height surface.
3. Use building footprints with rooftop points/heights to derive footprints
   and building heights/3D geometry. Export path polygons and canopy geometry
   as separate layers so overlap and uncertainty remain auditable.
4. Classify path and ground materials from the aerial imagery using reviewed
   labels from the Alton Towers training set. Export a single-band GeoTIFF
   using the mapper label codes below. Leave uncertain pixels as 255. LiDAR
   ground classification can support terrain and canopy separation; it cannot
   tell brick from stone or grass from mud.
5. Clip large outputs into consistent park tiles if needed. Keep neighboring
   tiles in the same CRS, pixel grid and vertical datum. Do not resample labels
   with bilinear interpolation; use nearest-neighbor for categorical masks.

## Mapper surface label codes

| Code | Label | Minecraft palette suggestion |
|---:|---|---|
| 1 | grass_unspecified | grass block |
| 2 | worn_grass | coarse dirt |
| 3 | dry_soil | dirt |
| 4 | mud | mud |
| 5 | gravel | gravel |
| 6 | stone_paving | stone bricks |
| 7 | brick_paving | bricks |
| 8 | asphalt | gray concrete |
| 9 | paving_unspecified | keep broad until resolved |
| 10 | unknown_ground | unknown / no material placement |
| 255 | ignore_unlabelled | no training vote |

The mapper's existing starter data contains reviewed paving examples for stone,
brick and asphalt, but not reviewed fine labels for worn grass, soil, mud or
gravel. Do not label those classes from appearance alone until examples are
reviewed.

## Bundle and validation

Use the example configuration at `examples/arcgis_export_config.example.json`
as a template. Replace every example provider, URL, license, source date, path
and accuracy with values that describe the actual data. Set
`ground_returns_verified` only after confirming the LAS class 2 returns really
represent ground. Do not run ground classification on the source LAS as part
of this export; the source point cloud is read only.

Run the exporter in ArcGIS Pro's Python environment, where `arcpy` and the
required 3D Analyst license are available:

```sh
python tools/arcgis_pro_export_bundle.py examples/arcgis_export_config.example.json
```

The exporter creates a DTM from ASPRS class 2 points, a DSM using maximum
elevation from valid point classes, optional WGS84 GeoJSON path/building/canopy
layers, and an optional single-band categorical surface-label raster. Output
layers keep their source IDs, CRS, observed date and stated accuracy in the
manifest. The DTM resolution is configurable (default 1 m; 0.1–5 m allowed).
This is data preparation, not a claim that 0.25 m inputs yield 0.25 m accurate
geometry.

The LAS class filter and raster export rely on ArcGIS Pro's [Make LAS Dataset
Layer](https://pro.arcgis.com/en/pro-app/3.6/tool-reference/data-management/make-las-dataset-layer.htm)
and [LAS Dataset To Raster](https://pro.arcgis.com/en/pro-app/3.6/tool-reference/conversion/las-dataset-to-raster.htm)
tools. ArcGIS documents class 2 as bare earth; confirm that the supplied point
cloud is correctly classified before using it to derive the DTM.

The exporter writes a bundle `manifest.json`. For bundles prepared by other
means, the manifest contract is demonstrated here; each layer has a source ID,
CRS and relative path. Accuracy and resolution are in metres.

```json
{
  "schema_version": "voxel-arcgis-extract-v1",
  "park": "Alton Towers",
  "crs": {"horizontal": "EPSG:27700", "vertical_datum": "ODN", "linear_units": "metre"},
  "sources": [{"id": "lidar-2024", "type": "lidar", "provider": "record provider", "observed_date": "2024-06-01"}],
  "layers": [
    {"id": "lidar-ground-and-vegetation", "role": "classified_lidar", "path": "lidar/alton.laz", "source_id": "lidar-2024", "classification_scheme": "ASPRS", "crs": "EPSG:27700", "horizontal_accuracy_m": 0.5, "vertical_accuracy_m": 0.25},
    {"id": "dtm", "role": "terrain_dtm", "path": "terrain/dtm.tif", "source_id": "lidar-2024", "crs": "EPSG:27700", "resolution_m": 1.0},
    {"id": "surface-classes", "role": "surface_labels", "path": "surfaces/classes.tif", "source_id": "lidar-2024", "crs": "EPSG:27700", "class_codes": [1, 6, 7, 8, 9, 255], "labels_reviewed": true}
  ]
}
```

Run the intake validator from the repository root:

```sh
python -m voxel_mapper.arcgis_ingest path/to/alton_arcgis_bundle --report arcgis_qa.json
```

It checks required metadata, source references, paths staying within the
bundle, file types and surface class codes. If `rasterio` is installed, it also
inspects GeoTIFF dimensions, CRS and pixel size. Warnings identify missing
layers or optional metadata. A successful report means the export is
well-formed for a future mapper reader; it does not mean a Minecraft world has
been updated.

## Review in ArcGIS Earth

Load the DTM/DSM, point-cloud or scene layers, footprints, extracted paths,
planning boundaries and OSM overlays into a local 3D scene. Check alignment at
known buildings/ponds, compare elevation profiles across paths and inspect
canopy/building occlusion. Earth is useful for review and measurement; edit or
re-export source geometry in Pro. Preserve the extracted layer and review
corrections as separate evidence instead of silently moving source data.

## Current constraint

This repository change establishes an ArcGIS Pro export and QA handoff. It
does not claim that ArcGIS has delivered new Alton Towers LiDAR or imagery,
does not fetch proprietary/resolution-restricted services, and does not yet
write the imported layers into a `.mcworld`. The next implementation step is a
tile-aware reader that converts validated layer coordinates and raster cells
into the existing evidence and surface-classification records, followed by a
world-export adapter.
