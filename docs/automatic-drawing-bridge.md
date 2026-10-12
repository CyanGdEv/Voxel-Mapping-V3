# Explicit drawing registration bridge

The park pipeline can now batch supported native PDF pages into registered feature records, compile those records and supply the existing progressive world generator. This removes manual corner tracing for the supported annotation contract. It does not provide general interpretation of arbitrary planning drawings.

## Supported inputs

A drawing needs a pinned SHA256, permitted geometry reuse, a projected metre target CRS and verified existing/as-built state. A trusted source manifest must establish the `explicit_object_leader_v1` annotation convention and its identity. These flags represent supplied evidence; the bridge cannot discover or certify them from a PDF.

Each page needs one printed scale, at least three noncollinear `CP:identifier` controls and two separately sourced checkpoints. Labels must connect by unique explicit straight leaders to orthogonal crosshairs. Identifiers join to a trusted survey landmark registry. Checkpoints must not reuse the controls' source IDs or content hashes. Registration retains the existing fit/scale checks, rejects extrapolation beyond the validation hull, and checks reference accuracy plus attachment/fit error against a one-metre tolerance.

Supported object labels identify exactly one straight, closed, unclipped polygon by a leader terminating inside it:

| Label | Required attributes | Output |
| --- | --- | --- |
| `PATH:id` | `surface=asphalt` (or another supported palette value) | Ground-following paving |
| `PLAZA:id` | `surface=...` | Ground-following paving |
| `WALL:id` | `height_m=2 material=stone_bricks` | Boundary wall |
| `ROOF:id` | `elevation_m=4 slope_x=0.5 slope_y=0 thickness_m=0.5 material=stone` | Explicit planar roof surface |

Roof elevation is measured at the leader endpoint. Slopes are rise per metre along drawing-local axes, transformed into the target grid. The source vertical datum must be verified and match compilation. Polygon holes are preserved; roof thickness is quantized to whole blocks. A roof plane supplies no missing openings, walls or support structure.

Raster scans, custom fonts, forms, layered/invisible text, ambiguous nested polygons, unknown attributes, missing dimensions and proposed geometry are withheld. Material acceptance, global conflicts, retained terrain coverage and native export remain separate downstream checks.

## Batch interface

`documents.json` is a list of entries, with file paths relative to that list:

```json
[{"file":"drawings/site.pdf","source_id":"site","pages":[1,2]}]
```

Omit `pages` to examine all pages. `references.json` contains a `landmarks` list:

```json
{"landmarks":[{"id":"A","target":[400000,340000],"source_id":"survey-control","role":"control","accuracy_m":0.1}]}
```

This abbreviated registry is insufficient for registration: supply the required controls and independently sourced checkpoints. Both survey sources need accepted registration, pinned hashes and verified physical landmark identities in the manifest.

```sh
python -m voxel_mapper.drawing_registration_bridge \
  --documents documents.json --manifest manifest.json \
  --references references.json --output registered
```

The output includes streamed `features.jsonl`, page decisions in `pages.jsonl`, an augmented `manifest.json` and a checksum report. Each accepted page receives its own source ID (`original/page-N`); the original source remains unchanged. Completed runs can be reused only when inputs, PDF bytes, budgets and outputs match their recorded hashes. Interrupted batches require a fresh output directory; this adapter does not yet resume midway through a PDF batch.

Bounds: 1,000 documents, 1,000 pages per PDF, 10,000 pages per batch, 2,000 eligible polygons per page and up to 2,500,000 feature records. These are safety ceilings, not a measured 2.5-million-feature performance result.

## Park job configuration

Add this alongside the existing manifest, terrain and base-world configuration:

```json
{"registration_bridge":{"enabled":true,"documents":"documents.json","references":"references.json","max_pages":10000,"max_features":2500000}}
```

`python -m voxel_mapper.park_pipeline --job park-job.json --stage compile` runs the bridge before compilation, uses its page-source manifest and appends accepted bridge records to other configured geometry feeds. No accepted bridge records and no other feeds produces `awaiting_normalized_geometry`, without a geometry database or world export. The compiled database can then be passed to the cycle planner and ten-worker Actions workflow described in `park-generation-cycles.md`.

## Validation and remaining work

The synthetic native-PDF test contains three controls, two independent checkpoints, a path, wall and pitched roof. It exercises automatic correspondence, actual PDF polygon extraction, batch registration, the park compiler, four cumulative chunk cycles and reading a paving block from the final `.mcworld`. Other tests reject reused checkpoint identities/hashes, poor accuracy, wrong CRS, inconsistent scales, missing leaders, invisible/layered content and unverified vertical datums; cached output corruption and changed inputs also fail.

This synthetic evidence does not register the real Wicker drawings. Real accepted controls, independent checkpoints and world additions remain zero in the retained Wicker evidence. Ordinary park drawings still need additional extraction adapters, reliable revision/state evidence, independent registration data and documented component dimensions. Hundreds of applications and complete arbitrary ride/building reconstruction have not been demonstrated by this change.
