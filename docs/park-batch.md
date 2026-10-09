# Whole-park reconstruction jobs

`voxel-park --job examples/park-job.json` runs acquisition, page indexing, coordinate normalization, disk-backed reconstruction and export as one resumable job. Install the project's planning and native-world dependencies first. The module equivalent is `python -m voxel_mapper.park_pipeline --job examples/park-job.json`.

The supplied example collects the recovered Alton catalogue offline and deliberately stops at `awaiting_normalized_geometry`. Set `offline` to false to attempt official downloads. Alton application discovery is available with acquisition `provider: "alton"`; other parks can supply an attachment catalogue containing URL, applicationReference, title, role, state and optional SHA256. A new portal needs an adapter. Search limits and incomplete coverage remain explicit; this is not proof that every application has been found.

## Acquisition and reconstruction are separate evidence stages

The downloader deduplicates URLs while retaining application links, uses content-addressed PDFs, checks cached bytes on resume, limits concurrency/bytes, and retains failures for retry. Redirects and non-allowlisted hosts are rejected. Inspection inventories every available page within the job budget, including native text and vector counts. A PDF vector path can be a title-box line, annotation or hidden stroke: counting it does not establish a physical object.

Reconstruction consumes source-linked **semantic features**, rather than treating every page stroke as geometry. Feed these through job `geometry_feeds: [{"file":"park.geojsonl", "source":"survey"}]`, or supply already normalized records through `feature_records`. Each GeoJSONL line must be one GeoJSON Feature. Its properties include `reconstruction_family` and `reconstruction_parameters`; parameter values identify their evidence source and documented/measured/estimated status. The existing source adapters also recognize supported mapping tags. See `reconstruction.sources.geojson_adapter` and existing generator contracts for exact parameters.

Supply a real projected metre CRS, park boundary, terrain configuration and terrain SHA256 in the manifest. GeoJSON coordinates are transformed from the declared source CRS; this is not automatic drawing registration. Planning/CAD geometry requires accepted registration, and each feature must be existing or as-built. Proposed or unknown drawing states are withheld. Three-dimensional routes and absolute elevations require a matching vertical datum. Missing dimensions, unsupported primitives and unresolved material conflicts are recorded as withheld decisions. Estimates require an explicit opt-in.

| Park object | Supported reconstruction primitive |
| --- | --- |
| Paths, plazas | Paving footprints or buffered routes with evidenced width/surface |
| Ride layout | Explicit 3D track route; 2D routes do not invent heights |
| Ride supports | Explicit 3D beam members |
| Walls, metal and wooden fences | Wall/fence profiles with evidenced height/material |
| Rockwork | Faceted rock generator by lithology/height, using full blocks, slabs, stairs and walls |
| Lakes | Polygon with holes, explicit bed/surface elevations and bed material |
| Bridges, flat rides, water-ride structures | Supplied architectural component profiles and dimensions |
| Animal enclosures and crossings | Supplied architectural components; no automatic enclosure design |
| Buildings and other structures | Existing roof, tunnel and architectural generators where their contracts are satisfied |

Aliases dispatch to existing primitives. They do not infer an entire ride mechanism, enclosure or bridge from its category name. Automated PDF semantic classification, park-wide registration and reconciliation of drawing revisions remain further work.

## Scale and recovery

The default job feature budget and benchmark ceiling are **2,500,000 features**. A manifest can set `max_features` explicitly. This counts unique committed feature IDs, including withheld decisions; identical IDs resumed from disk do not consume the budget twice. Reaching the budget preserves earlier committed features and rejects the next new feature. The 20-million-cell default and per-feature voxel budgets remain separate: complex geometry can reach its voxel budget before its feature budget. The benchmark still defaults to 150,000; use `--features 2500000` for a full ceiling run. The recorded measurements below are from the 150,000-feature run, not a verified 2.5-million run.

Features arrive as a stream. SQLite stores normalized feature records, decisions, native-chunk cell indices and many-to-many provenance; only one bounded feature is staged in memory. Whole-feature collision decisions span tile boundaries. Per-feature and total voxel budgets prevent unbounded rasterization. Retrying an identical committed feature skips it; changing a feature, manifest, configuration or pinned job input requires a fresh job.

The measured synthetic benchmark compiled **150,000 independent one-cell plaza features** in **32.84 seconds**, resumed all of them in **7.86 seconds**, and used **114.53 MiB peak process RSS**, across 625 native chunks. This proves feature-count scalability for that fixture, not 150,000 interpreted planning components or a complex native park export. From the repository root, reproduce it with `python -m scripts.benchmark_park_batch --help` and the documented options printed there.

Without `base_world`, export writes chunk tiles plus streamed feature/cell provenance and decisions. With `base_world` pointing to a retained world directory containing `park.mcworld`, `quality-report.json` and `bedrock-world`, compilation preflights occupied cells and native export composes one chunk at a time. Export retains coverage, checks existing protected geometry, closes and reopens the native world to verify written sections, checks retained bridge walks when present, and packages only after verification. An empty accepted plan produces no world package. Native jobs retain committed chunk checksums for recovery.

Job paths are relative to the job JSON. Outputs live under its `work_directory`. Keep that directory for resume. To expand or change the job configuration, use a new directory. Acquisition can run separately with `--stage acquire`, and compilation/export with `--stage reconstruct`. PDF cache can be shared through acquisition `cache`, pointing to a directory containing `files/<sha256>.pdf`.

## Validation recorded in this change

The recovered Alton catalogue had 397 URL/application links. Replay recovered 142 records referencing 84 unique PDF blobs and inspected 238 pages without inspection errors. A four-URL live trial returned HTTP 502 on every request; these failures remain retryable and no successful fresh downloads are claimed. Focused tests exercise corpus recovery, byte budgets, evidence gates, global conflicts, tile hashes, native cold-reopen verification and job-input changes. Existing drawing-control test failures are reported separately in the validation record.
