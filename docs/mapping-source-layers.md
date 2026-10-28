# Mapping source comparison layers

A new **Compare mapping / survey layers** desktop job produces a standalone
comparison viewer. Four retained study areas share their original aerial grids:
Towers Street / Mutiny Bay, the gardens / lake, Chessington courtyard and the
new tight garden paths. Nothing is automatically registered by fitting one map
to another, accepted as geometry, added to training or promoted as a model.

## Loaded observations and explicit gaps

- OS OpenMap Local building outlines are queried from Esri UK's public mirror.
  Source metadata, selected object IDs and complete geometry pages are retained.
  Generalisation limits small-edge precision. Service editing dates are not
  survey dates. The original OS product is free generalised 1:10,000 mapping.
- Two Wayback releases, 24 September 2026 (`63116`) and 12 December 2019 (`4756`),
  are assembled from their pinned native public tiles. These are publication
  dates, not local capture dates. Centre-point capture/source metadata is
  retained separately and does not describe every pixel in an imagery mosaic.
  The two layers can reuse imagery; they are not two independent votes.
- Historic England vertical and oblique photo catalogue camera locations are
  queried through the public services linked by its Aerial Photo Explorer map.
  Markers are not photo footprints, orthorectified photographs, or proof of
  coverage. A photograph taken outside the queried area can still depict it.
- The existing four aligned one-metre LiDAR context fields are available:
  relative height, terrain slope, roughness and explicit valid-data support.
  Native gaps stay transparent; the validity view makes missing cells visible.
- A previously acquired, hash-pinned raw EA crop near Wicker Man is overlaid
  only where it intersects a view. Its 5 January 2022 survey is P_10682, ODN
  heights, BNG coordinates. The retained crop contains 56,568 source points.
  Withheld/synthetic returns are excluded from display; deterministic source-wide
  sampling caps display at 20,000 points. Source classifications are attributes,
  not newly established tree/building/support labels. No new whole-park raw
  cloud was acquired in this stage.
- Retained GB Topographic water, woodland and road fragments are included for
  Towers Street / Mutiny Bay only. The underlying data is OS Open Zoomstack,
  with June 2026 content reported by the service item. These generalised tile
  fragments are not unique surveyed objects, narrow garden paths, or independent
  corroboration of other OS-derived layers.
- Current draft ground/canopy labels can be compared directly. Unknown labels
  remain transparent. The previously confirmed circular garden structure is in
  the ground labels. These drafts are the subject of review, not validation truth.

| Study area | OS building features in view | Historic England vertical / oblique markers | Displayed raw-return sample |
| --- | ---: | ---: | ---: |
| user-towers-mutiny | 42 | 0 / 0 | 6451 |
| user-gardens-lake | 51 | 0 / 27 | 1564 |
| user-chessington-courtyard | 46 | 13 / 4 | 0 |
| user-tight-gardens | 3 | 0 / 5 | 0 |

Detailed OS / NGD, registered planning geometry and Mapillary locations have
explicit local-import slots and source links. No licensed OS dataset, registered
planning drawing or Mapillary export was supplied in this stage. The new viewer
therefore keeps those slots disabled. Planning vectors can be loaded after a
source drawing is registered; this job does not georeference PDFs itself.

The official Overture release catalogue was available, but the existing bulk
reader failed its S3 connection in this environment. Each area's complete failure
receipt is retained and replays as **unavailable**, never verified empty coverage.
Pinned local Overture GeoJSON is supported, preserving upstream sources such as
OSM. Counts of agreeing OSM and Overture objects must not be treated as independent
measurements when they share a source. Use a fresh cache to retry live discovery.

## Viewer

Open `index.html` in a browser. Choose an area, toggle a layer and adjust its
opacity. Drag to pan, scroll to zoom, and reset to the original extent. Click
vector features or use Details to inspect source records, original dates,
limitations and hashes. The sidebar scrolls independently on desktop screens.

Ground colours are blue paving, red structures, green grass and dark-blue water.
Canopy is amber; labelled non-canopy is teal. Unknown targets are transparent.
Height/slope/roughness run from blue (low) to red (high); their titles state the
normalisation limits. Valid LiDAR is green and missing support grey. Photographs
and return markers have their own layer colour; the inspector retains attributes.

Export comparison notes records the area, visible layers, reference image hash
and current view. Notes explicitly do not approve geometry or add training labels.
The automated export check is not a human review. The viewer needs no external
scripts, map keys, network requests or web server after download.

## Alignment and interpretation

All geometry is clipped to the actual returned aerial extent and displayed in
Web Mercator. Polygon holes are preserved. No path widths are invented by
buffering centre lines. BNG inputs require the best available metre-scale datum
transform and a retained hash-checked OSTN15 grid. The ruler reports **projected**
metres, not ground distance. Raw returns keep their ODN vertical values.

CRS alignment is not surveyed physical registration. The imagery can be shifted,
roofprints can differ from wall footprints, and sources have different epochs.
Fine export pixels do not improve optical or LiDAR source resolution. Layer
absence never becomes a paving, grass, tree or building label. Use stable,
independently measured control points and reserve independent checks before
claiming a precision improvement. This stage adds comparison tools, not a
measured improvement in model accuracy.

## Running and importing data

Extract `mapping-layer-inputs/` and `cache/` from the download. With the full
repository at this revision and its normal dependencies installed:

```sh
python -m voxel_mapper.mapping_layers --config comparison.json --output new-comparison --cache cache
```

The packaged request is offline. To use the repository's desktop example, put
`mapping-layer-inputs/` at the repository root and select
`examples/desktop/compare-mapping-layers.json`. CLI output must be a fresh directory.
The desktop worker uses its persistent application cache; for a new desktop
installation, either copy the packaged cache contents into that web-cache, or
set `offline` to false to retrieve public observations. An offline cache miss is
visible as a gap; it does not fabricate data.

Requests use version `mapping-source-layers-v1`. Each area supplies `image_file`,
`receipt_file` and their `_sha256` fields. The aerial receipt must contain the
original `image_sha256`, actual `width`, `height` and `extent_epsg3857`. Optional
`ground_mask_file`, `canopy_mask_file` and `label_source_image_sha256` keep draft
labels tied to the exact RGB. Optional four-channel `lidar_features_file` and
`lidar_receipt_file` must identify the same image and hashed NPZ bytes.

Public `providers` may contain `os_openmap`, `historic`, `wayback` and `overture`.
At most two exact `wayback_releases` are permitted. The public reader retains
original bytes and SHA receipts, verifies offline reuse, rejects incomplete
feature pages and respects service page limits (one photo service allows only
15 records per page). It limits requests to registered public source hosts,
checks public DNS/redirect destinations, preserves the configured session proxy,
and bounds bytes/time. Its byte counter excludes the separately bounded Overture
SDK, which has its own discovery receipt. Up to eight one-megapixel areas and
24 local imports are supported.

Example of a local vector import:

```json
{"id":"registered-survey","family":"planning","format":"geojson",
 "title":"Existing survey — document and page identified",
 "path":"survey.geojson","path_sha256":"<SHA256 of actual file>",
 "crs":"EPSG:27700",
 "metadata":{"source_url":"https://example.org/source-document",
             "license":"<actual reuse terms>","plan_status":"existing",
             "document_sha256":"<source document SHA256>","page":1,
             "registration_status":"provisional — review required"}}
```

Supported vector CRSs are EPSG:4326, EPSG:3857 and EPSG:27700; a declared GeoJSON
CRS must agree. Raw imports use `format: las` with a bounded native BNG crop and
source/datum metadata. All local imports require original file hashes, source
URLs and licence information. Imported geometry and upstream properties are
retained. Family names describe the source, not the semantic truth of objects.
Specify `areas` on an import to restrict known coverage. Missing datasets are
shown as gaps rather than copied from another park.

## Validation and distribution

37 relevant tests passed: 15 new mapping tests, 12 desktop runtime tests and
10 aerial research regressions. Tests cover clipping and holes, invalid/conflicting
CRSs, source and label pins, transparent unknown/nodata pixels, service truncation,
small-page pagination, cache tampering, exact offline source replay, Wayback date
semantics, retained Overture failures and a real desktop subprocess without training.

The browser exercised all four areas, 45 loaded layer toggles and opacity controls,
36 raster/reference decodes, 25 disabled gap layers, feature inspection, physical
pointer selection, drag/wheel zoom, reset and note export, with no runtime errors
or external requests. All four area payloads reproduce exactly offline, including
rasters, projected features and source metadata. This is software/data validation,
not an independent survey or human review of the outlines.

The download includes the standalone viewer, original inputs, public source cache,
source receipts, comparison report, tests, source changes and hashes. A full repo
checkout is required to run the job; the source patch is not a standalone program.
No model weights or Windows executable are included. No training run, model
promotion, accepted geometry or world changes occurred in this stage.

Imagery: Esri and its imagery providers. OS: Crown copyright/database rights and
applicable OS OpenData attribution. LiDAR: Environment Agency, OGL-UK-3.0.
Historic England photo records: retain record-level rights; catalogue access does
not grant unrestricted reuse of photographs. Imported/licensed datasets retain
their individual terms. Public viewing and permission to train are distinct;
these comparison layers are not automatically training-eligible.
