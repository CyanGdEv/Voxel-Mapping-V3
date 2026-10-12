# Automatic resort area cycles

The controller processes every configured resort area in order. It finishes the
ready area's chunk cycles before advancing, records blocked areas without marking
them complete, and retains verified cumulative native previews. It stops after
one area pass or the publication budget; it does not loop forever on missing
plans or recipes.

## Local execution

`python -m voxel_mapper.area_cycles local --job JOB.json --max-cycles 20`

The maximum counts native chunk cycles, not source scans. Subsequent invocations
resume `auto-cycle-state.json`. All blocked areas can be scanned during one call
without consuming a native cycle. `auto-cycle-summary.md` lists the per-area
statuses. A finished blocked pass does not repeatedly extract the same sources.
Changed jobs, catalogue/supplement pins or recipe files require a fresh work
directory. Start the new pass with the latest verified cumulative native world
as its checksum-pinned initial baseline.

Each area still needs actual planning applications, a source-bound
`reconstruction_job`, accepted `bounds` and `bounds_crs`, `required_families`, and
physical `required_component_ids`. A drawing filename or matching application
name does not supply registration, existing-state review, component identity or
a reconstruction recipe. The controller runs existing compilation/provenance,
1:1, terrain, boundary and worker validation rather than bypassing them.

## Actions execution

`.github/workflows/resort-area-cycles.yml` provides three phases:

1. Prepare acquires/extracts and compiles the next area that can produce a native
   cycle. Source-only areas are checkpointed as blocked and the cursor advances.
2. Ten parallel Actions jobs create exclusive worker payloads for one chunk
   cycle (normally about 150 chunks; existing scheduler maximum is 200).
3. One assembler verifies every worker and publishes a cumulative `.mcworld`.
   The checkpoint is uploaded before the workflow dispatches its successor.

The successor continues the same area if more chunks remain, otherwise it moves
to the next area automatically. Downloads are named
`area-preview-AREA-cycle-NNNN` and include `area-cycle-preview-report.json`.
A completed partial area preview remains partial, but its verified geometry is
carried into later area worlds. Missing components remain in its report.

The initial `resort-area-inputs` artifact must contain a self-contained
`job.json`, pinned native baseline, source catalogues/PDF cache and the actual
recipe dependencies. All original job/recipe paths must be relative and stay
inside the artifact. Work and original inputs are checkpointed together in
`area-cycle-checkpoint`; each runner restores them to `area-cycle-work`.
Absolute paths generated in derived runtime jobs remain stable on the same
Ubuntu Actions checkout layout. The portable-path validator runs before
preparation and rejects outside assets. Baseline and compiled input hashes are
also rechecked by workers and the assembler.

Launch once after the workflow is available on the repository default branch:

```bash
gh workflow run resort-area-cycles.yml --ref voxel-mapper-v3.1 \
  -f source_run_id=RUN_WITH_INPUTS \
  -f source_artifact=resort-area-inputs \
  -f continue_automatically=true \
  -f max_publications=200
```

The first workflow pins the generator commit. Continuations download the last
checkpoint and reuse that SHA. To continue a paused pass, select its checkpoint
run via `continuation_run_id`, preserve `generator_commit` and increase
`max_publications` if needed. A manual stop uses `continue_automatically=false`.
Worker/assembler failures do not advance the cursor or publish a success.
Rerun failed jobs or resume the previous checkpoint. A local interruption after
a verified native publication is recovered before preparing more work.

GitHub's `workflow_dispatch` must be registered on the default branch. Dispatch
from `GITHUB_TOKEN` can create the next run; the assembler has `actions: write`.
See [workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
and [dispatch events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).

## Current Alton Towers inputs

The controller is implemented for all fifteen configured areas. The current
park still has twelve areas awaiting production recipes/alignment/inventories
and three awaiting application associations. Automatically visiting every
area does not make those prerequisites disappear. The real source-only pass
publishes no new world; native cumulative behavior is independently verified
with real two-area Bedrock integration fixtures, including a multi-cycle area,
a missing-worker failure, publication recovery and retained partial geometry.

For areas without hand-written recipes, the optional [automatic element reconstruction](automatic-element-reconstruction.md) mode derives supported recipes and component IDs from registered drawing semantics. It uses this same worker/assembler sequence and keeps discovered-only areas as partial previews.
