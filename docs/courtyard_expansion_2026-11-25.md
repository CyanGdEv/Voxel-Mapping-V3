# Expanded courtyard evidence audit and native preview

The second preview adds eighteen block changes in nine reviewed lawn-interior
columns. Together with the retained first preview, it contains thirty block
changes in fifteen columns. This is a partial courtyard repair, not a completed
courtyard, independent model validation or AI model promotion.

## Data and withheld cells

The existing geographically registered eastern sample contains 113 reviewed
lawn cells and 123 generic-paving cells. The planner audits every lawn-labelled
cell, retaining the same extra two-cell erosion and height gates used for the
first preview. Generic paving remains unchanged; no fine material is invented.

| Lawn audit outcome | Cells |
|---|---:|
| Additional qualified/reviewed repairs | 9 |
| First-preview repairs already match | 6 |
| Boundary margin withheld | 68 |
| Measured above-ground geometry retained | 13 |
| Negative DSM-minus-DTM remains unknown | 8 |
| Unverified ground material retained | 5 |
| Unsupported ground support retained | 2 |
| Vertical quantization residual withheld | 2 |

The nine new cells lie within X=884..891, Z=350..356. Direct source-RGB overlay
review confirms lawn interiors. The request derives coordinates from the accepted
1m label affine and the registered native grid, not hand-entered translations.
EA P_10682 (2022-01-05, OGL-3.0) DTM/DSM are one survey lineage. Reviewed labels
and RGB are also one imagery lineage. RGB acquisition date/licensing scope is
unknown. These limitations are preserved in the scoped acceptance record.

## Implemented automation

`tools/plan_surface_repairs.py` has four explicit stages:

1. `prepare`: read the canonical registered grass class; check CRS, aligned 1m
   projected metre grids and matching pixel centres; preserve unknown heights;
   sample DTM/DSM and record hashes and ignored-label counts.
2. `inspect`: read fresh native columns from the supplied world using the existing
   Bedrock palette codec. Cross-check actual highest blocks against heightmap
   metadata, including higher subchunks. Protect unsupported storage and
   block-entity chunks. No world write occurs.
3. `propose`: use the existing ground-surface module to assess reviewed lawn
   interiors. Require finite nonnegative DSM-DTM <=0.05m, terrain block-top
   residual <=0.1m, supported ground and complete native geometry. Preserve
   trees, water, walls and uncertain materials. Proposed edits remain unaccepted.
4. `accept`: require a scoped review bound to the exact proposal-file hash and
   qualified coordinates. Emit a native plan within existing 64-block/four-chunk
   limits. The existing Bedrock patch adapter performs writes and final checks.

The criteria were inherited from the first preview and not relaxed to increase
block counts. Coordinate/material algorithms contain no park-specific constants.
The source sample, survey and scoped review are configuration/evidence data.
No additional source download, training run or independent test area is claimed.

## Executed world changes

Each new column has one supported stone/mossy/cracked-stone ground block changed
to grass and one unsupported deepslate block above it removed. Ground block
positions remain unchanged. Mean absolute native top-surface residual against
input DSM for the nine selected new cells is 2.012m before and 0.041m after.
This is local consistency with the source survey, not independent absolute accuracy.

- Input: first preview, SHA-256
  `6e072c25dbe4f1271fbc776a3fed75b2e459689679b4444fe6041582cdf23a70`.
- Expanded preview: SHA-256
  `56d9ef76df2a3937d01670a5ed39e0f5f9343c1f2ff38164f4b154a6be4f1405`.
- Original archive remains unchanged at SHA-256
  `0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
- Eighteen new blocks and nine heightmap columns change in chunks (55,21)/(55,22).
  Relative to the original: thirty blocks, fifteen height entries, four changed
  records out of 63,650. All other original native records remain identical.
- A separate chain audit reapplies both accepted plans to their original logical
  snapshots and matches each resulting world exactly. It verifies the actual
  cumulative changed block coordinates and height entries against both plans.
  All twelve first-preview edits remain preserved.
- Native palette/NBT and biome payloads remain unchanged. All non-database assets
  remain byte-identical. Re-extraction and Amulet reopening verify every new block;
  all 8,704 overworld chunks and original Bedrock 1.21.120 settings remain present.

The display name is inherited from the supplied world. Native-format checks do
not substitute for a Minecraft client import/play/save test, which is unavailable
here. Both earlier worlds remain intact. The expanded file is a separate preview.

## Reproduction and tests

```bash
python -m tools.plan_surface_repairs prepare \
  --dataset /workspace/data/alton-broad-area-context-v2.zip \
  --sample geographic_299b80e09090_847_348 \
  --registration /workspace/evidence/alton/world-registration.json \
  --dtm /workspace/evidence/alton/ea-2022/ea-national-dtm.tif \
  --dsm /workspace/evidence/alton/ea-2022/ea-national-dsm.tif \
  --output output/requests.json
PYTHONPATH=. /workspace/bedrock-venv/bin/python -m tools.plan_surface_repairs inspect \
  --requests output/requests.json \
  --baseline /workspace/experiments/Alton_Towers_Courtyard_Verified_Preview.mcworld \
  --output output/observations.json
python -m tools.plan_surface_repairs propose \
  --observations output/observations.json --output output/proposals.json
# Review the proposal/RGB/height evidence and bind accepted columns to its SHA-256.
python -m tools.plan_surface_repairs accept \
  --proposals output/proposals.json --review output/review.json --output output/plan.json
PYTHONPATH=. /workspace/bedrock-venv/bin/python -m voxel_mapper.bedrock_patch \
  --baseline /workspace/experiments/Alton_Towers_Courtyard_Verified_Preview.mcworld \
  --plan output/plan.json --output output/expanded.mcworld --report output/result.json
```

Fresh output paths are required. Proposals/observations are hashed; use a fresh
review matching the exact generated proposal if serialization differs. Archive
hashes can differ on rerun because of LevelDB housekeeping/compression, while the
logical changes remain invariant.

Local suite: 60 tests, with three optional native tests skipped in the training
environment. All five Bedrock patch tests pass in the isolated native environment.
Regression coverage includes missing/negative heights, boundaries, retained
vegetation/water/walls, material/support conflicts, stale native heights, pixel
centre shifts, coarse rasters, and review-hash/coordinate mismatches.

Exact public proposals, scoped review, plan and aggregate execution/chain audit
are committed alongside this document. Full requests/native observations, visual
review, chain-audit script and world output are retained in the cycle bundle;
supplied imagery and world binaries are not committed to Git.
