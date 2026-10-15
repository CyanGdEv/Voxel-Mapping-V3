# Reproducible small-area world pilot

The pilot exports a draft Bedrock world from retained terrain and geographic
features, with a planning readiness ledger. Pending planning evidence does not
prevent the available geographic world from exporting. It never promotes a
drawing hypothesis, review task or learned score into physical geometry.

After installing `.[planning]`, run from the repository root:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/alton-world-pilot-job.json \
  --output output/alton-world-pilot
```

The installed command is `voxel-world-pilot` with the same arguments. The example
runs offline using files included in the repository. It covers approximately
128 by 62 metres inside the retained Alton terrain crop. It includes the
Environment Agency 5 January 2022 DTM and seven road/footpath candidates retained
from the OpenStreetMap map API on 15 October 2026. Geometry is clipped during
generation. Unspecified path widths and materials remain reported assumptions.
The terrain coordinate operation's advertised accuracy is recorded separately
from voxel size; this trial used a two-metre operation, not independent surveyed
placement. Different PROJ installations can choose different operations.

Three OSM building-tagged volumes were deliberately excluded from the retained
pilot feed. The acquisition receipt also lists rejected/unavailable relation and
ride geometries. No withdrawn Smiler lift reconstruction, guessed ride heights,
excavation, detailed building or coaster geometry is included. The retained
Smiler audit supplies missing-evidence tasks only. This is a new terrain and
paths preview, not a repaired or reinstated ride model.

## Outputs and acceptance

* `park.mcworld`: import into Minecraft Bedrock. World name identifies it as a
  draft. Spawn coordinates are in `README.txt` and `pilot-report.json`.
* `pilot-report.json`: input hashes, actual emitted feature counts, planning
  decisions, pending review tasks, generation errors and output hashes.
* `quality-report.json`: generation warnings, terrain coverage and transform,
  materials/width assumptions, native readback and export metadata.
* `README.txt`: concise scope and missing-evidence checklist.
* `inputs.json`, `resolved-config.json`, `features-local.geojson` and
  `voxels.jsonl`: receipts and geometry for comparison and inspection.

The quality report packaged inside the world contains the planning readiness
ledger. Planning records distinguish `withheld`, `no_voxels` and
`voxelized_for_export`. Passing an adapter check alone is not counted as an
emitted component. Voxel counts describe records supplied to composition;
overlapping features can share or override final blocks. Native readback checks
every written block and unwritten air cell. Minecraft visual inspection and
real-world geometric accuracy remain separate checks.

If no geometry produces voxel records, the pilot publishes a readiness report
with `awaiting_exportable_geometry` and no world archive. Generation errors and
omissions remain visible even when the available geometry can export. An export
failure or changed input cannot publish a completed pilot directory or retain a
world archive in the diagnostic staging directory. Existing output and staging
directories are never overwritten; replay into a fresh output directory.

## Job contract

`version` is `world-pilot-v1`, with a human-readable `name`. `config`, `features`
and `planning_review` each name a file and its SHA256:

```json
{"file": "relative/path.json", "sha256": "64 lowercase hexadecimal characters"}
```

These paths resolve relative to the job. Optional `evidence` is a list of extra
pinned files, such as acquisition receipts. Raster `path` values resolve relative
to the config and require their own `sha256`. All inputs are checked before work
and again before publication. JSON is limited to 16 MB per file, the area to
40,000 m², resolution to one block per metre, voxel and column work to one
million each, and native export to four million attempted blocks. There can be
at most 10,000 geographic features, 1,000 planning records and 1,000 review tasks.
The initial contract supports terrain, surface/fallback and bathymetry rasters;
point-cloud inputs are not supported.

The feature file contains `features` and optional `planning_geometry_records`.
Geographic features require unique string IDs and sources whose `kind` is `osm`
or `geographic`. The `planning/` namespace and planning evidence properties are
reserved for the existing planning adapter. Planning records use the unchanged
[verified geometry contract](../voxel_mapper/planning_geometry.py): registered
source, confirmed reuse/registration/as-built state, document and verification
references, supported polygons and datum-compatible explicit structural levels.
These confirmations are supplied evidence assertions, not independent
certification performed by the pilot. Missing confirmations withhold the record.

The planning review file is a list of pending tasks. Each has a unique `id`,
`title`, nonempty `required_evidence` list and pinned `evidence` files relative to
the review file. These files can be retained audits or original sources. Every
task remains `awaiting_evidence`; it cannot authorize insertion. Update the
reviewed adapter records separately when the required evidence exists, and pin
the changed inputs in a new job.

For replay comparison, compare input hashes, the `voxels.jsonl` hash, feature
counts and readiness decisions across fresh runs. Bedrock archive bytes contain
world/database metadata and can differ. The local runtime selected a two-metre
datum operation; a different runtime operation must be assessed before treating
voxel equality as expected. Training, production model promotion and complete
building verification do not run in this pilot.

The next real-data acceptance milestone is one independently registered,
source-bound planning component in this world. The current retained trial
inserts zero planning components. A synthetic regression test demonstrates the
component-to-world path and reads the emitted block back from the native world;
it does not establish acceptance of a real Alton component.

The [retained validation receipt](evidence/world-pilot/alton-world-pilot-validation-2026-10-15.json)
records the real trial and replay: 7,936 terrain, 178 road and 90 path voxel
records, 32 native chunks, zero reported generation errors and identical voxel
hashes. The full suite passed 1,410 tests. The 213,433 composed blocks include
artificial foundations; they are not a count of reconstructed park objects.

## Explicit OSTN15 placement and saved-world overlay

Use the second retained job to remove dependence on which datum grids happen to
be installed in the runtime:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/alton-world-pilot-ostn15-job.json \
  --output output/alton-world-pilot-v2
```

This job pins a 3,250-byte regional window of the original OSTN15 grid. It retains
the original sample positions, all four bands, units and grid metadata without
resampling. The provenance records the complete upstream grid SHA256, exact
window, sample hash and nine full-grid/crop equivalence checks. The operation is
explicit: local WGS84-based projection to longitude/latitude, inverse horizontal
grid shift, then British National Grid projection. It does not use global PROJ
grid search, silently select a Helmert alternative, or change ODN heights. A
missing/corrupt grid, unsupported raster CRS or point outside the grid fails the
build rather than exporting a fallback world.

The EPSG:7710 WGS84 approximation has advertised one-metre operation accuracy.
This is not independent validation of OSM, planning controls, source epochs or
the resulting park. At the retained sample longitude/latitude, the former
two-metre operation and the explicit grid operation differ horizontally by
about 1.953 m. Sampling different terrain pixels can change generated ground
heights; this is not a vertical datum correction. Independent physical controls
and checkpoints are still required for planning-component acceptance.

Optional job `horizontal_operation` contains `method: ostn15-bng-v1`, plus pinned
`grid` and `provenance` descriptors relative to the job. This operation applies
to every configured elevation raster, which must use EPSG:27700. A raster-level
operation cannot bypass the job's input pinning. Other jobs retain their original
operation selection. The cropped grid is distributed under the retained
[upstream notice and BSD terms](evidence/world-pilot/OSTN15-LICENSE.txt).

To reproduce the grid retention from the original checksum-pinned download:

```sh
PYTHONPATH=. python scripts/retain_alton_ostn15_grid.py \
  --source /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/fresh-grid-output
```

Every exported pilot now also writes `placement-comparison.svg` and
`placement-comparison.json`. The overlay shows projected source boundaries in
blue, saved matching materials in orange and overridden materials in magenta,
over the generated terrain. JSON retains per-feature emitted/material-match
counts and block-centre distances outside projected geometry. Native coordinates
are read with the export's height offset and northing sign convention. Shared
materials do not prove unique feature provenance. Rasterization distances are
not survey residuals, and an overlap under composition is not automatically a
reconstruction fault.

The original Smiler existing/proposed planning PDF requests were checked again
for this iteration. HTTPS returned HTTP 503; the pinned existing-plan HTTP
fallback timed out. The retained source-check receipt and v2 review task record
that failure. No inaccessible PDF, proposed sketch, missing landmark or learned
score was used to authorize a real planning component. The updated world remains
a terrain/path prototype, with the first planning-component placement pending.

The [v2 validation receipt](evidence/world-pilot/alton-pinned-placement-validation-2026-10-15.json)
records 1,416 passing tests, identical source/native comparison and voxel hashes
on a fresh replay, zero missing terrain requests, and the 32-chunk native export.
Of 268 emitted road/path records, 261 match saved materials and seven are
overridden under the existing composition rules. No real planning component or
complete building was added. The SVG overlay was inspected; Minecraft visual
inspection remains outstanding.
