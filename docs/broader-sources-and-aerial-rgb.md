# Broader public sources and aerial RGB material research

Public research now supports structured APIs as well as HTML/PDF/image pages. The aerial job reads map RGB information, preserves georeferencing and suggests visually similar block palettes for later review. These additions do not train neural weights or accept material assignments automatically.

## More research sites

Set `source_families` on a `web-research-v1` request or its `research` settings inside map/learning-cycle jobs:

```json
{"source_families": ["knowledge", "rides", "archives", "planning_data", "geospatial"]}
```

| Family | Site routes | Reading capability |
| --- | --- | --- |
| knowledge | Wikidata, English Wikipedia, Wikimedia Commons and linked image servers | Entity labels, aliases, referenced claims, image metadata/credits and offered image downloads |
| rides | RCDB, Coasterpedia | Scoped web searches and accessible public HTML/document links |
| archives | Library of Congress, Historic England, National Archives Discovery | Scoped searches, accessible catalogue metadata, drawings and photographs |
| planning_data | Planning Data | Public entity records and declared document URLs; dataset coverage varies and is not a universal planning-application index |
| geospatial | ArcGIS, Environment Agency, NLS maps | Public catalogues, service/layer metadata, GeoJSON/feature attributes and accessible survey/map links |

Selecting a family explicitly adds its registered public hosts to the request scope. It adds at most one public search per family, sharing the existing byte/time/source budgets. Empty subjects do not trigger generic searches. Operator-supplied council hosts and source links remain supported. Public discovery continues to validate new hosts and each fetch; inaccessible/authenticated pages are recorded as gaps.

Documented API routes can be derived from exact offered identifiers: a Wikidata QID gets an entity JSON view, a Commons File reference gets image metadata, an ArcGIS item/service gets its JSON metadata, and a LOC item gets its public JSON view. The optional local reasoning model can select these as exact offered links. This does not execute arbitrary page JavaScript or submit login/search forms.

The structured reader supports Wikidata entities, Commons/MediaWiki image info, Wikipedia summaries, GeoJSON/ArcGIS features, planning entities, public catalogue results, archive resources, ArcGIS item/service/layer metadata and image-export metadata. Original bytes remain SHA-pinned. API error objects, invalid/duplicate/nonfinite JSON, excessive nesting and private URLs are rejected. Returned metadata stays unverified, including coordinates, heights, aliases and external identifiers.

Focused HTML views now read bounded JSON-LD, alternate JSON feeds and embedded iframe/object/embed document URLs. They remain separate from immutable original cache receipts. This enables many document-viewer pages to expose their PDFs without browser automation. Script-generated URLs that never occur in the retained HTML still require another supported source/API.

General web research retains its larger configured source allowance. Planning-document collections preserve their six-source default batches so durable resume and analysis resource bounds stay stable; explicit lower/upper overrides within the existing web limits still apply.

## Aerial RGB job

Choose **Aerial RGB / material research** in the updated desktop source and submit `examples/desktop/wicker-aerial-materials.json`, or run:

```sh
python -m voxel_mapper.aerial_material_research --config request.json --output aerial-run-001 --cache web-cache
```

The public Esri World Imagery export is the working default. It requests a small WGS84 area and uses the **returned Web Mercator extent and actual dimensions**, since a service can expand requested bounds to fit an image's aspect ratio. Image and metadata bytes are checked and retained. An additional point identify request records provider-reported capture dates, resolution and accuracy where available. Point metadata is not silently applied to an entire imagery mosaic.

The output includes the original image, `rgb-preview.png`, an offline `index.html` comparison, `sample-cells.geojson`, and `material-candidates.jsonl`. The GeoJSON polygons are sampling cells, not extracted building/path boundaries. Original imagery and its attribution remain visible. Analysis normally excludes the bottom 32 pixels to avoid footer/attribution pixels influencing colour statistics; the original image is retained in full.

Each cell records median RGB, colour variation, dark/green/blue pixel fractions, and coarse colour clues. Existing user-guided paving palettes are ranked by CIELAB Delta E76 distance. These are visual colour matches, not calibrated confidence scores or a trained material classifier. Similar colours can represent paving, roofs, bare ground, timber or weathered materials. Shadow, vegetation and blue/water-like cells explicitly withhold palette use. All cells retain `material_verified: false` and `training_eligible: false`.

The existing reviewed orthophoto adapter still requires accepted registration, a capture date, reviewed polygons/reviewer, and an independently supplied material/surface. This new research job does not bypass those requirements. No world blocks are changed. Downloaded RGB and the controller's own palette suggestions do not become verified training labels.

The job is capped at 4 million pixels, dimensions of 128–2048, grid sizes of 4–32, 32 MB and 180 seconds. Each requested WGS84 dimension is at most 0.02 degrees. Original image dimensions, transparency/nodata, cancellation and checksum consistency are checked.

## Bing Maps

Every aerial report includes a Bing aerial viewer link for the requested area. The Bing adapter uses the documented Static Map API, requests separate map metadata, and projects the **returned** bbox for pixel georeferencing. It requires `BING_MAPS_KEY` configured locally; the request JSON never contains a key. Credential-bearing URLs do not enter the public receipt cache, and network exceptions are sanitized. Original key-free image/metadata snapshots can be reused offline after their hashes and reconstructed extent are checked.

No Bing key is configured in the validation environment, so its real job reports `awaiting_bing_maps_key` with zero pixels/requests. Bing behaviour was exercised with synthetic metadata/transport fixtures, not a live authenticated Bing image. The Bing website could not be opened by the available web tool. Live RGB results are from **Esri**, not Bing.

Microsoft documents that the Basic Bing Static Map API has retired; eligible Enterprise access continues until 30 June 2028, with Azure Maps as its replacement. An Azure adapter is not implemented here. See [Microsoft Static Map API](https://learn.microsoft.com/en-us/bingmaps/rest-services/imagery/get-a-static-map) and [Static Map metadata](https://learn.microsoft.com/en-us/bingmaps/rest-services/imagery/static-map-data).

## Connect aerial observations to the research cycle

A `public_sites` entry can add `aerial_context` with the provider/bounds/dimensions/grid/offline fields from the standalone example. The updated adaptive example enables aerial sampling for the current Alton area. Up to two aerial areas share the cycle's existing 64 MB / 600 second research budget. Source observations and a candidate-file hash are remembered; the neural checkpoint is reused unless the verified training dataset changes. Map and RGB observations stay separate from geometry/material acceptance.

## Actual validation

The live structured-source run retrieved Wikidata, Commons, Planning Data and ArcGIS JSON, using 34,790 bytes. The requested LOC endpoint returned HTTP 403 and remains unavailable in that run. A separate Commons image-info run downloaded two referenced JPEGs, retained their source image/credit metadata and used 719,720 bytes. RCDB/Coasterpedia and other registered HTML routes are implemented and covered by scoped-routing fixtures; live availability is not asserted for every registered site.

A live 1024×1024 Esri aerial export used 781,436 bytes before the optional point metadata request and produced 256 sample cells. The centre-point metadata included a 27 May 2023 observation, 0.5 m source resolution and 8.47 m provider-reported accuracy, alongside lower-resolution source records. Capture date/accuracy for the entire image and alignment to planning geometry remain unverified. The image's output pixel spacing can be finer than source resolution because the service resamples it.

The replay uses retained, checked bytes with zero network traffic. The detailed test counts, original hashes, image previews, source statuses and checkpoint-reuse checks are in `evidence/broader-sources-aerial-validation.json`. No neural material model was trained, accuracy improvement demonstrated, accepted material assignment created, or Windows EXE rebuilt in this stage.
