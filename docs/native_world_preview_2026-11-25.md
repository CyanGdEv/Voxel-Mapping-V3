# First evidence-backed native Bedrock preview

A copy of the supplied Alton Towers world now contains twelve scoped block
changes in one chunk. Six lawn-interior columns receive grass at Y=93, and six
unsupported deepslate blocks at Y=95 are removed. This is reviewed-mask and
measured-height integration, not AI model promotion or whole-park reconstruction.

## Evidence and acceptance scope

The 1m reference RGB visibly shows lawn at X=886..888, Z=353..354. Previously
reviewed grass labels survive conservative class coverage, boundary erosion and
an additional two-cell erosion. Native inspection found stone/mossy-stone paving
at Y=93, air at Y=94, and a deepslate layer at Y=95. The native column height was
96, so treating the DTM-level block as the visible surface would have been wrong.

EA survey P_10682 (2022-01-05, OGL-3.0) gives DTM 191.95..192.00m ODN and DSM
191.96..192.02m. DSM-minus-DTM is finite, nonnegative and below 0.05m in the six
selected cells. The roof's block-top elevation was approximately 194m ODN, about
2m above measured surface evidence. The grass replacement's top is 192m ODN.
Mean absolute top-surface residual against DSM changes from 2.016m to 0.023m
for these six selected cells. This is a local consistency result with the input
survey, not independent park-wide accuracy.

Two adjacent cells with negative DSM-minus-DTM were withheld. Roofs, trees,
water and uncertain geometry outside the six selected columns stay untouched.
The source-grid relation is E=406912+X, N=343984-Z at grid edges; block centres
use +0.5 east and -0.5 north. Previous terrain/roof/paving controls and supplied
older-world audit metadata support this relative grid. Shared lineage is not
independent absolute survey validation. DTM and DSM are one survey lineage,
not two independent votes. RGB acquisition date/licensing scope is unknown.

The original registration remains read-only globally. A separate acceptance
record permits only this reviewed six-column preview, with baseline/source
hashes, native block preconditions and measured heights. No current prediction
checkpoint is accepted for block edits.

## Executed native verification

- Original world SHA-256 remains
  `0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
- Preview SHA-256:
  `6e072c25dbe4f1271fbc776a3fed75b2e459689679b4444fe6041582cdf23a70`.
- Twelve changed blocks in chunk (55,22); six heightmap entries change 96→94.
- Exactly two of 63,650 native LevelDB records change: one subchunk and its
  Data3D heightmap. Every other logical record is byte-identical.
- Original native palette/NBT bytes are retained, including block version tags.
  Every other block index in the edited subchunk is checked unchanged. Biome
  payloads, entities, inventory/player data and all non-database assets remain
  unchanged. Physical LevelDB housekeeping files can differ.
- Exported archive was extracted again and its complete logical database matched
  the verified working copy. Amulet independently reopened it and checked all
  twelve resulting blocks. All 8,704 overworld chunks remain present, with the
  original Bedrock 1.21.120 metadata.

No Minecraft client is available here. This is native-format and independent
library verification, not an in-game import/play test. The preview keeps the
original world display name and gameplay settings; its distinct download
filename identifies the copy. Do not replace the preserved original baseline.

## Implementation and reproduction

`voxel_mapper.bedrock_patch` reuses Amulet's existing palette codec and the
installed native Bedrock LevelDB binding. It patches a fresh extracted copy,
preflights every record, changes only requested palette indices and heightmap
entries, verifies all logical records/assets, and publishes a new archive only
after re-extraction and independent reopening. It does not use Amulet's broader
whole-chunk save path and does not implement a duplicate full-world generator.

This first adapter is deliberately bounded to 64 block edits and four chunks.
It supports existing v9 single-storage subchunks and existing stateless native
palette targets. It rejects unsupported formats, missing chunks, block-entity
chunks, stale before-block/height preconditions, invalid final column heights,
unaccepted evidence and model candidates. Current accepted transitions are
scoped stone-paving→grass and unsupported deepslate→air only. Water, fluid layers,
lighting/emissive edits, new palette entries and arbitrary structure edits are
not supported. This limit applies to this first adapter, not the eventual park
cycle size.

Use an isolated Python 3.11/3.12 environment for `.[bedrock]`; its pinned Amulet
runtime uses NumPy <2, separate from the current training environment. The CI
native job installs the compiler/build tools and runs codec/height/precondition
regressions. In the current workspace:

```bash
PYTHONPATH=. /workspace/bedrock-venv/bin/python -m voxel_mapper.bedrock_patch \
  --baseline /workspace/data/downloads/baseline.mcworld \
  --plan docs/courtyard_patch_plan_2026-11-25.json \
  --output output/Alton_Towers_Courtyard_Verified_Preview.mcworld \
  --report output/courtyard-world-result.json
```

Each output path must be fresh. Compression/database housekeeping can change
archive hashes on rerun; exact logical records and block changes are the
validation invariant.

Local regression suite: 55 tests pass with two optional native tests skipped in
the training environment. All four patch tests, including those two codec tests,
pass in the isolated native environment. The real world trial above also passed.
Exact accepted evidence, plan and execution report are committed alongside this
document. World binaries and supplied aerial imagery remain outside Git.

Next: expand reviewed, measured acceptance to a larger area, add conflict checks
for retained geometry, and validate a trained model independently before allowing
AI candidates to produce accepted plans. The twelve-block preview is a working
export bridge and a small actual world correction, not a production model release.
