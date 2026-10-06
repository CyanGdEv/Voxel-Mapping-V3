# Voxel Mapper V3.1

Evidence-backed real-world voxel mapping, runnable in GitHub Actions. This initial implementation uses a local metric projection and a default voxel size of one metre. It is a foundation, **not yet a complete high-detail theme park reconstruction system**.

## Run in Actions

Open Actions → Voxel Mapper 3.1 → Run workflow. Supply a committed JSON configuration path and optionally a committed GeoJSON input path. Without GeoJSON, the workflow requests public OpenStreetMap geometry from Overpass. Download the resulting artifact and inspect `quality-report.json` before using the map.

`examples/area.json` is a small demonstration bounding box, not a surveyed theme park boundary. Strict mode deliberately fails when features contain assumptions, invalid geometries, skipped relations, or no usable features. Artifacts are retained on strict failure so evidence can be reviewed. Disable strict only to generate an explicitly approximate draft.

## Local execution

```sh
python -m pip install .
voxel-mapper --config examples/area.json --output output
python -m unittest discover -s tests -v
```

For curated data, add `--features path/to/features.geojson`. GeoJSON coordinates must be WGS84 longitude, latitude. Register every feature's `source_id` in the configuration's `sources` array with an `id`, `url`, and `license`. Optional source metadata such as survey date, positional accuracy, and vertical datum is preserved in the report. These declarations are attribution records, not independent verification of the source's truth or licence permissions.

Feature properties:

| Property | Purpose |
| --- | --- |
| `source_id` | Required registered evidence source |
| `kind` | Building, path, parking, water, attraction, or structure |
| `height_m` | Extrusion height in metres |
| `base_elevation_m` | Base altitude in a common user-selected vertical datum |
| `width_m` | Width for line geometry |

Missing height, elevation, and line width produce warnings. OSM height tags are accepted when numeric. A building footprint alone cannot establish roof shape, windows, interiors, or themed facades. Bridges require explicit base elevations and heights; generic OSM geometry alone cannot establish deck clearance. Planning proposals must not be treated as evidence of as-built conditions.

## Outputs and limits

- `voxels.jsonl`: streamed feature-attributed voxel records; x east, y up, z north. Coordinates describe voxel grid indices; multiply by `voxel_size_m` for metres. Overlapping features remain separate records for downstream composition.
- `features-local.geojson`: clipped geometry in the local projected CRS, which is recorded in the report. This is not RFC 7946 WGS84 GeoJSON.
- `quality-report.json`: assumptions, invalid features, skipped OSM relations, source records, CRS, counts, and voxel file checksum.
- `input.geojson` and `osm-raw.json` when applicable: retained input evidence.

The implementation extrudes footprints and buffered lines. It does not yet create a Minecraft world, reconstruct meshes or coaster track, ingest raster terrain/LiDAR, discover planning applications, or independently compare multiple datasets. It does not guarantee all real-world features are present. Strict success establishes the implemented checks passed; it does not certify survey accuracy or completeness. Projection distortion and voxel quantisation limit accuracy, and feature edges are sampled at voxel centres.

Area and voxel budgets limit Actions resource consumption. Large locations should be divided into smaller areas. Input antimeridian areas must be split. Network outages fail the run rather than silently substituting fabricated geometry.

## Required next stages for accurate theme parks

1. Regional terrain adapters with explicit horizontal/vertical CRS, nodata and coverage checks; LiDAR ground classification where available.
2. Full multipolygon assembly, bridge deck and tunnel modelling, layered paths, parking markings and measured building roofs.
3. CityGML, mesh and point-cloud ingestion with licensing and acquisition metadata.
4. Planning drawing discovery, scale extraction and georeferencing against surveyed control points; distinguish proposed, approved and as-built data.
5. Theme park attraction geometry and custom structures from measured evidence; uncertainty masks for unavailable features.
6. Independent validation against control points, coverage and positional error thresholds, and dated source conflict resolution.
7. Tiled Minecraft export and end-to-end comparison against an independently surveyed pilot park.

Public availability varies by jurisdiction. A system can support arbitrary locations while honestly reporting unavailable evidence; it cannot guarantee equally detailed reconstruction everywhere.
