# Voxel Mapper V3.1

Automatically acquire public geographic data and generate a **Minecraft Bedrock `.mcworld` at one block per metre**. Start with a park name/address or bounding box. The normal workflow needs no uploaded terrain, manually prepared GeoJSON, dataset URLs or Minecraft world template.

**Scale and accuracy are different.** Export preserves metric scale and terrain relief, but available public evidence limits reconstruction detail. Current worlds are labelled draft/unverified: generic building extrusions and mapped paths are not faithful reconstructions of themed facades, interiors, roofs, or 3D coaster tracks.

## Run on GitHub Actions

Open **Actions → Voxel Mapper 3.1 — Bedrock World → Run workflow**:

- `location`: a specific park name and country/address, such as `Thorpe Park, Chertsey, United Kingdom`.
- `bbox`: optional `west,south,east,north`; overrides the location name. Maximum bounding area is 4 km² per run.
- `strict`: fail the accuracy gate after generating and retaining the draft world if evidence warnings remain.

Download the workflow artifact. Open `park.mcworld` in Minecraft Bedrock to import it. Inspect `quality-report.json` for omitted features, assumed dimensions, terrain coverage and reconstruction limits. `acquisition.json` records provider outcomes. Ambiguous names fail rather than selecting a park silently.

The workflow is manually dispatched, but every supported data acquisition and export step inside it is automatic. Larger regions currently need separate bounding-box runs; seamless tile stitching is future work. This pipeline targets Bedrock 1.21.130 data through pinned Amulet Core; an actual in-game import still needs validation.

## Automatic sources

| Data | Acquisition and evidence handling |
| --- | --- |
| Park location/boundary | Nominatim; polygon boundaries are used when available |
| Buildings, roads, footways, parking, water, mapped attractions | OpenStreetMap/Overpass with retained raw response and source attribution |
| England terrain | Environment Agency native 1 m elevation WCS, with coverage discovered from capabilities |
| Other regions / unavailable EA data | Automatic Open Topo Data Mapzen sampling; coarse mixed-source fallback is flagged |
| Bedrock world | Automatic LevelDB world creation, block composition, read-back validation and `.mcworld` packaging |

Mapzen's approximately 30 m output includes areas derived from lower-resolution data. It does not supply one-metre surveyed accuracy. Provider outages cause failure, or a documented supported fallback; no fabricated terrain is substituted. All extracted raster/input evidence is retained alongside reports. Data provider API limits are respected for the elevation service (100 samples/request and at least one second between requests).

OSM multipolygons preserve courtyard holes. Incomplete relations are reported. Missing widths/heights are reported as assumptions; draft buildings default to 6 m and draft line widths to 2 m. Ground features follow per-column sampled terrain. Bridges, tunnels and nonzero layers without absolute elevation evidence are omitted with errors; OSM layer numbers never become guessed heights. Their elevations are not currently acquired from another automatic source.

Planning drawing acquisition, independent surveyed control-point validation, building meshes and 3D ride geometry are **not implemented**. Capability gaps are included in every report, so strict mode cannot certify a complete accurate park with the current adapters. There is no manual data preparation step hidden behind these capabilities.

## World export

- One voxel maps to one Bedrock block; exports reject other voxel sizes.
- East is Minecraft positive X; north is negative Z. Local projection details are recorded.
- A constant Y offset places the lowest mapped elevation at Y=64 while preserving relative heights. Geographic elevation equals Minecraft Y minus the recorded offset.
- Areas exceeding the supported vertical range fail instead of being resized or cropped.
- Terrain receives four blocks of ground fill. This is not a full geological volume.
- Generic block materials represent feature classes. Overlap is composed deterministically: structures/buildings take precedence over paths, parking, water and terrain.
- Chunk writes are processed one at a time using an on-disk composition database. Every composed block is checked after reopening the Bedrock world before packaging.
- The world name marks it as a draft, and attribution/georeferencing files are included in the `.mcworld`.
- Minecraft can generate unrelated terrain beyond exported chunks; the mapped area is recorded in the configuration.

The voxel budget, scan budget, native raster budget and world block budget bound resource use. The world is structurally verified using Amulet, which is not equivalent to testing import and play inside Minecraft.

## Local execution

Python 3.12 is used in Actions. Native dependencies may require a C/C++ compiler.

```sh
CC=gcc CXX=g++ python -m pip install .
python -m voxel_mapper.cli --location 'Thorpe Park, Chertsey, United Kingdom' --output output
python -m voxel_mapper.cli --bbox=-0.5124,51.4027,-0.5116,51.4033 --output small-area
python -m unittest discover -s tests -v
```

Use an empty output directory per run to prevent stale exports being mistaken for successful new output. `--strict` retains the generated draft and fails if warnings/errors remain.

## Evidence and formats

`voxels.jsonl` retains feature/source identifiers before composition. `input.geojson` is WGS84; `features-local.geojson` uses the local projected CRS recorded in the report and is not RFC 7946 WGS84 GeoJSON. `resolved-config.json` records the automatically selected sources, location and bounds. GeoTIFF checksum, pixel spacing, horizontal CRS and declared vertical datum are reported. EA data uses ODN; fallback Mapzen heights are not asserted to share a verified survey datum. No automatic vertical datum transformation is applied.

Provider documentation:

- [Environment Agency DTM WCS](https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs)
- [Open Topo Data Mapzen data](https://www.opentopodata.org/datasets/mapzen/) and [API limits](https://www.opentopodata.org/)
- [OpenStreetMap attribution/licence](https://www.openstreetmap.org/copyright)
- [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Amulet Core](https://github.com/Amulet-Team/Amulet-Core)
