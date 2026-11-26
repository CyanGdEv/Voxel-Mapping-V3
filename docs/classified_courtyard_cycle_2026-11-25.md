# Classified-return investigation and courtyard preview

The new preview adds eight block changes in four lawn columns, preserving the
previous thirty changes. It now contains thirty-eight cumulative changes in
nineteen lawn columns. The courtyard remains partially repaired; this is not a
production AI reconstruction release.

## Real survey discovery and point observations

Two fresh EA survey catalogue requests returned HTTP 200 and complete 14-entry
responses for the courtyard-buffer and native reference-world extents. Neither
advertises a product finer than 1m. This is a statement about those EA catalogue
queries, not proof that finer data is unavailable from every provider. Exact
query bounds, dates, response hashes and URLs are retained in the discovery JSON.
No 0.5m survey was downloaded or manufactured by resampling.

The existing checksum-verified EPSG:27700 LAS from EA P_10682, acquired 2022-01-05
under OGL-3.0, was scanned: 10,537,336 retained park points examined; 592 returns
intersect the 236 reviewed courtyard cells. The LAS coordinate scale is 0.01m,
which is encoding precision, not certified survey accuracy. Ground classification
establishes terrain support, not grass or paving material.

A new streaming helper in `voxel_mapper.point_cloud` deduplicates XYZ/class/return
observations, handles half-open native cells and flags/noise/invalid return
metadata, and reports classes, first returns, quadrant coverage and height ranges.
Only sixteen cells meet the strict observed-ground criteria:

- At least four first ground returns distributed over all four cell quadrants.
- First-ground spread at least 0.5m in both horizontal axes.
- Only ground/unclassified classes 2/1, no excluded/flagged/noise observations.
- Ground vertical spread <=0.15m and all retained heights within 0.15m of the
  median ground elevation.

These are spatial observation criteria for one survey lineage, not independent
votes, calibrated confidence or a continuous 0.5m surface. Boundary margins,
material conflicts, native structures, vegetation and unsupported volumes remain
protected. A sparse or clustered point set cannot certify an empty roof footprint.

## Resolving raster gaps without rewriting evidence

The planner can read request-hash-bound per-cell return evidence. Original DTM
and DSM values, including negative differences, remain unchanged. Qualified direct
returns are an explicitly recorded alternative geometry basis. They must agree
with finite terrain/raster heights within the conservative conflict tolerance;
positive classified structure/water or elevated-return evidence withholds a cell.
Low vegetation classification alone does not manufacture an overhead structure.

One previously negative-height lawn cell and one low-surface disagreement qualify
through distributed raw ground observations. Native support checks also omitted
`minecraft:dirt_with_roots`, a solid terrain block. Recognizing that existing
support allows two other repairs; the rooted-dirt blocks themselves are retained.
Three of the four accepted columns use direct-return height support; one uses the
existing raster-pair support. These categories overlap: one rooted-dirt case also
has distributed direct returns. Do not count them as four independent sources.

All four proposed footprints were reviewed against the source RGB lawn interior.
Reviewed labels/RGB share imagery lineage; DTM/DSM/raw returns share the EA survey
lineage. RGB acquisition date/licensing scope remains unknown. No source becomes
new material ground truth from its LAS classification. No model was trained or
promoted during this cycle.

## Actual native-world changes and preservation

New cells: (X,Z) = (889,351), (890,351), (888,352), (889,354).
Each receives grass at Y=93 and removal of an unsupported deepslate block at Y=95.
Root blocks below Y=93, paths, all uncertain floating surfaces and underground
geometry remain untouched.

- Parent expanded preview SHA-256:
  `56d9ef76df2a3937d01670a5ed39e0f5f9343c1f2ff38164f4b154a6be4f1405`.
- Classified-LiDAR preview SHA-256:
  `4825dadc4a0e0d4e3874affff1583dba0d631280a79b3e7af1bd9ca4a73f1ae1`.
- Original archive remains
  `0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
- Eight new block indices/four height entries change. Against the original:
  thirty-eight blocks, nineteen height entries, and four changed records of
  63,650. Complete logical chain comparison preserves all prior repairs and all
  other original records. Palette/NBT bytes, biomes and non-database assets remain
  unchanged.
- The exported file was re-extracted; its full logical database matched the
  verified copy. Separate Amulet reopening checks all eight new blocks, all 8,704
  chunks and the original Bedrock 1.21.120 metadata. This is native-format
  verification, not a Minecraft client import/play/save test.

The original display name/settings are retained. The new file is a separate copy.
Ninety-four lawn-labelled cells remain outside accepted coverage, including
boundary margins and protected/unknown material or geometry. Classified evidence
also confirms an existing paving cell without changing its material. These local
observations do not establish whole-courtyard or park-wide accuracy.

## Reproduction and regression coverage

```bash
python -m tools.audit_surface_returns \
  --cloud /workspace/evidence/alton/ea-2022/ea-point-cloud.las \
  --requests /workspace/experiments/courtyard-paving-audit/requests.json \
  --registration /workspace/evidence/alton/world-registration.json \
  --source /workspace/evidence/alton/ea-2022/lidar-evidence.json \
  --output output/cell-returns.json
python -m tools.plan_surface_repairs propose \
  --observations /workspace/experiments/courtyard-paving-audit/observations.json \
  --cell-returns output/cell-returns.json --output output/proposals.json
# Bind a scoped review to the exact proposal hash after inspecting imagery/heights.
python -m tools.plan_surface_repairs accept \
  --proposals output/proposals.json --review output/review.json --output output/plan.json
PYTHONPATH=. /workspace/bedrock-venv/bin/python -m voxel_mapper.bedrock_patch \
  --baseline /workspace/experiments/Alton_Towers_Courtyard_Expanded_Preview.mcworld \
  --plan output/plan.json --output output/classified-preview.mcworld \
  --report output/world-result.json
```

Fresh output paths are required. The isolated native runtime remains separate
from the GIS/training environment. Raw point files and source imagery stay outside
Git; hash-bound reports and scoped plans are retained. Repacking can change an
archive hash while preserving exact logical changes.

Local suite: 63 tests, with three optional native skips. All five isolated Bedrock
patch tests pass. New regressions cover LAS first-return flags, duplicate points,
clustered samples, building/elevated counterevidence, invalid return metadata,
point-cloud identity/scan budgets, preservation of negative raster observations,
material boundaries, rooted terrain and cell-coordinate mismatches.

Next evidence work must address the remaining boundary and structural uncertainties
without inferring subsurface volumes or material from LiDAR alone. An independent
reviewed AI test area and a Minecraft client test remain outstanding.
