# Progressive park generation

The cycle layer schedules roughly 15 spatial sections, targets 150 native chunks per cycle and publishes cumulative Bedrock preview downloads. Ten interchangeable workers own disjoint chunk payloads; one native writer assembles the world. Players can inspect a preview while later cycles continue automatically.

This implementation consumes an **already compiled, accepted geometry snapshot** and a base terrain world. It does not make unregistered drawings acceptable, perform automatic roof/wall interpretation or prove 2.5 million features can be reconstructed end to end. Scraping, automatic registration and semantic reconstruction remain upstream work. The ten workers currently partition and serialize compiled placements, not independently infer geometry from PDFs.

## Scheduling and ownership

- `generation_cycles.py` persists the input contract, spatial sections, cycles, chunk owners and preview checksums in SQLite.
- Sections use balanced recursive spatial splits. A native chunk belongs to exactly one section and cycle. Sections are spatial partitions, not named theme-park areas.
- Cycles balance around the requested target, with a hard 200-chunk maximum. At the default 150 target, large sections produce batches in the 100–200 range; small sections can produce smaller batches.
- Workers are numbered 0–9. Empty workers still publish a receipt, so the assembler can require all ten.
- A one-chunk halo lists neighbouring context without granting write ownership. Full feature records and globally resolved placement rows remain available in the immutable geometry snapshot.
- Native coordinates use `cx = floor(x/16)`, `cz = floor(-z/16)`, matching the existing Bedrock exporter. Negative coordinates are tested.

The plan pins the compiled database, compiled contract, original base package, base quality report, terrain sampling configuration when present, and scheduling settings. Inputs changing during a job require a fresh plan. Compiled features have already passed the existing evidence and global-conflict gates; batching does not weaken them.

## Cumulative native export

`generation_cycle_export.py` presents connection-local SQLite views containing only chunks through the current cycle. Their source database hash stays fixed, allowing the existing native exporter to resume in one persistent output directory.

The exporter retains previous chunk write/readback records, verifies previously touched chunks and writes new ones. Each completed cycle copies a standalone `park.mcworld`, quality report and cycle report into `output/previews/cycle_NNNN/`. Previous downloads stay unchanged. The package includes the base terrain context, which can extend beyond the detail generated so far; reports distinguish scheduled chunks, detail-bearing chunks and unchanged terrain.

If an early cycle contains no accepted placement rows, it can publish an explicitly labelled `base_terrain_preview_only` package. A wholly empty accepted geometry snapshot is rejected at initialization. Empty terrain context must not be reported as reconstructed planning geometry.

Workers export hash-addressed chunk JSONL payloads and scoped provenance. Assembly requires every worker, checks exact chunk ownership and recomputes payload hashes from the accepted canonical snapshot. Missing, duplicate, foreign or changed payloads prevent publication. Native database writes remain single-writer operations.

## Local commands

Prepare geometry using the existing pipeline's new compile-only stage, without exporting the complete detailed world first:

```sh
voxel-park --job park-job.json --stage compile
```

A prepared base world is still required. Then:

```sh
voxel-park-cycles init --plan cycles.sqlite --geometry geometry.sqlite \
  --base-world base-world --sections 15 --batch-chunks 150 --workers 10 \
  --terrain-config terrain-config.json

voxel-park-cycles run --plan cycles.sqlite --geometry geometry.sqlite \
  --base-world base-world --output output --terrain-config terrain-config.json \
  --max-cycles 1

voxel-park-cycles report --plan cycles.sqlite
```

Omit `--terrain-config` only for compilations that did not pin one. If a terrain configuration was used during compilation, supply its exact original bytes. Relative terrain raster paths are resolved against the configuration directory; prepared configurations must use the same sampling location when compiled. Terrain raster checksum and vertical datum checks remain active.

Repeat `run` to continue, or supply a larger `--max-cycles` to process multiple cycles automatically. Local execution uses a ten-thread payload pool. `worker` and `preview` expose the same operations separately for distributed jobs.

## GitHub Actions

`.github/workflows/park-generation-cycles.yml` runs one cycle per workflow:

1. Restore input or the previous checkpoint and select the next cycle.
2. Run a ten-job matrix with `max-parallel: 10`.
3. Require all worker artifacts, assemble and publish `park-preview-cycle-NNNN`.
4. Save `park-cycle-checkpoint` and dispatch the next workflow when enabled.
5. Stop dispatching when all scheduled chunks are complete.

The initial workflow inputs identify a run and artifact containing a portable prepared bundle:

| Bundle path | Required content |
|---|---|
| `geometry.sqlite` | Accepted, globally compiled geometry; checkpoint WAL before uploading |
| `base-world/park.mcworld` | Original terrain/context package |
| `base-world/quality-report.json` | Original matching quality/coordinate contract, with 1 m voxels |
| `base-world/bedrock-world/` | Unpacked matching native base world used for chunk coverage |
| `terrain-config.json` | Exact compilation terrain configuration, when used |
| Terrain raster at its configured relative path | Original checksum-pinned raster, when used |

Continuation pins the generator commit selected by the first run. Whole-workflow concurrency serializes cycles for the same input artifact. Input handoffs/worker artifacts retain seven days; previews and completed checkpoints retain 30 days. Downloads are Actions artifacts, not permanent public hosting.

Checkpoints retain the latest preview and native writer state; older preview packages stay in their respective workflow runs. Reports retain each cycle's checksum, artifact name and workflow run ID. A failed cycle does not advance the manifest; retry its failed job or continue from the last successful checkpoint.

The workflow has been authored and linted, but has not been executed on GitHub. GitHub requires the dispatchable workflow to be available on the default branch. No PR was merged or production park generation launched as part of this change.

## Validation and remaining work

Tests cover a 2,500-chunk schedule across 15 sections, ten-worker disjoint ownership, negative/irregular coordinates, real `.mcworld` readback, cumulative details without future placements, crossing-feature provenance, missing/corrupt workers, export failure recovery, portable checkpoint continuation and input changes.

The native integration fixture is small and synthetic. It verifies the cycle machinery; it is not an Alton Towers reconstruction or a 2.5-million-feature performance benchmark.

Next work is connecting automatic registration/reconstruction output to the prepared bundle and benchmarking real park batches. Targeted feedback regeneration and permanent download hosting are not yet implemented. Full base/database handoffs to all workers and a growing cumulative world make this initial workflow storage-intensive; later optimization should shard immutable payload storage without losing the input and readback checks.
