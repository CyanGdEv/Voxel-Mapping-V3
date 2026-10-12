# Data-driven buildings and reviewed learning

The new building-neutral path separates source interpretation, geometry and
learned candidate ranking. `voxel-building-data` (or
`python -m voxel_mapper.building_pipeline`) runs the same generator for different
buildings. It does not yet discover complete building specifications from PDFs.
The existing architectural extraction/review stages need adapters that supply
these specifications, features and verified gate results.

## Shared geometry contract

`building-spec-v1` uses `local_xyz_metres_z_up`, stable building/component IDs,
source hashes, drawing states, evidence references and explicit assumptions.
Existing, proposed and unknown studies can be rendered locally, but states cannot
be mixed within an assembly. Imports retain explicit parent state and use unknown
when it is absent; a proposed study is never relabelled existing. Each
component is a wall, partition, floor, ground, roof, tower or detail. Geometry can be a
polygon extrusion (including protected holes) or a retained triangle mesh.
Extrusions are checked for closed oriented edges and correct volume; meshes are
checked for finite coordinates, valid indices, nondegenerate triangles and any
claimed closed topology. An open source surface can remain an open surface.
Budgets cover component count, whole-building vertices and triangles.

Import an existing study without moving its geometry:

```bash
python -m voxel_mapper.building_pipeline import-study \
  --model courtyard-model.json --building-id mutiny-courtyard \
  --output mutiny-building-spec.json
```

The adapter also handles the Wicker shop's wall/roof/projection mesh layers.
Its parent-file hash is a lineage link, not independent physical verification.
Source SHA declarations in a supplied spec are references; this module does not
retrieve those files or certify their content. Extraction/verification adapters
must establish them upstream. All generated models remain local previews with
zero accepted park blocks; existing registration, terrain and native compiler
checks are still required for park insertion. The shared native surface compiler now supports local spec previews; it does not
fill arbitrary solid interiors or certify a complete connected assembly. Existing
study/world exporters remain available and unchanged. Existing roof meshes retain their slab courses.

## Automatic batch operation

A `building-batch-v1` job contains `buildings`, each with a `building_id` and
`candidates`. A candidate has `id`, `spec`, `features` and `gates`.
The six normalized features are `boundary_support`, `view_agreement`,
`dimension_agreement`, `opening_support`, `topology_quality`, `source_coverage`.
Upstream adapters must compute these from source and geometry diagnostics; users
should not interpret an arbitrary numeric feature as established evidence.

The required local-candidate gates are `source_verified`, `identity_verified`,
`dimensions_verified`, `topology_verified`, each explicitly true. These are
upstream attestations, not tests performed by the ranker. A learned score cannot
turn a failed gate into a pass. A passing candidate still goes through geometry
validation. Invalid preferred geometry is recorded and the next eligible
candidate is tried; a blocked building does not stall other buildings.

```bash
python -m voxel_mapper.building_pipeline batch \
  --job buildings.json --output fresh-building-batch
```

A complete synthetic batch example is in `examples/building-data-fixture-job.json`.
Its source and gate declarations describe the fixture only; they do not establish
real building evidence.

The untrained baseline gives equal scores and uses stable candidate IDs as a
deterministic tie break. It provides no learned correctness estimate. The batch
writes a pinned job/model contract, per-building rankings, specs, models, GLBs,
results and a batch report. Existing output directories are refused; start a new
iteration rather than rewriting dispatched results. This path is sequential and
separate from the ten-worker area controller for now; it is not automatically
enabled by `automatic_reconstruction`.

## Actual learned model

`building-candidate-ranker-v1` is a small supervised logistic model with six
weights and a bias, trained with deterministic regularized batch gradient descent.
It learns to prioritize candidate interpretations. It does not generate geometry,
read pixels, infer missing dimensions or establish physical acceptance. These
scores are not calibrated certainty, and their transfer to unseen drawing styles
has not been measured. No pretrained neural model or training service is required.

Feedback is a `building-feedback-v1` document with `records`. Each record has:

- `id`, `building_id`, and the reviewed `candidate_sha256`;
- `source_sha256`: hashes of every source used by the candidate;
- `features`: the six normalized diagnostic values;
- `outcome`: `accepted` or `rejected`;
- `review_basis`: `independent_review` or `source_verified`.

Duplicate candidate feedback is rejected. Generated scores or successful mesh
exports are never automatically converted into positive training labels. Review
basis is a declared input provenance field; authentication and an actual review
capture/source-verification adapter remain future work. Keep the complete source
set in each record to make leakage checks meaningful.

A separate split file lists `training_buildings` and `evaluation_buildings`.
Every feedback building must belong to exactly one split, both splits require
positive and negative examples, and no source hash may occur in both. Previous
training buildings/sources remain excluded from evaluation during warm starts.
A real benchmark should group all connected source/building records, freeze an
unseen test set and periodically use a new untouched test set: repeated adaptive
use of one holdout can overfit even though the optimizer never sees its labels.

```bash
python -m voxel_mapper.building_pipeline iterate \
  --job buildings.json --feedback reviewed-feedback.json --split split.json \
  --parent previous-iteration/selected-model.json --output next-iteration
```

Omit `--parent` on the first run. One invocation automatically trains a candidate,
evaluates it, retains the last eligible checkpoint if it fails, then builds the
batch with the selected model. It writes candidate/selected checkpoints and the
iteration report. A failed learned candidate can be inspected separately with
`batch --model candidate-model.json --exploratory` but cannot become the normal
iteration parent. Raw `train` is also available for experiments.

Default checkpoint selection requires at least 100 training records, 20 evaluation
records, five training buildings and five evaluation buildings; held-out Brier
error must improve, precision among scores >=0.8 must be at least 95% and not
regress, and at least five evaluation predictions must meet that score threshold.
These are initial engineering gates, not proof of generalization or a guarantee
of improvement at every iteration. A worse iteration is saved but not selected.
Checksums detect checkpoint changes; they are integrity checks, not signatures.

## Verified and still needed

Real compatibility replay preserves the Mutiny V12 study's 934 component meshes
and the Wicker shop's three mesh layers exactly, including coordinates and
triangle indices. Synthetic learning tests cover improvement, failed promotion,
source/building leakage, warm starts, duplicate feedback, model tampering, failed
evidence gates and isolated batch failures. Synthetic labels demonstrate learning
mechanics only. No real trained Alton model is published or activated.

Next: connect extracted view/wall/opening/roof candidates to the shared spec;
compute diagnostic features automatically; capture independently checked feedback;
benchmark untouched buildings; implement general slab-based native compilation
and feed accepted registered results into the existing area workers. A trained
vision/geometry model becomes useful after that real dataset and benchmark exist.


## Retained drawing feed and real review collection

`prepare-feed --config feed.json --output fresh-feed` reads a
`retained-building-feed-v1` configuration with `buildings`. Each entry supplies
`building_id`, `model`, `model_sha256`, optional `diagnostics` entries (`path`,
`sha256`) and `source_directories` containing checksum-named PDFs. Paths resolve
relative to the config. Assets must be exact parent-model inputs or carry a
matching `corrected_model_sha256`; unrelated audits cannot supply scores.

The adapter automatically translates retained study meshes to shared specs,
checks original PDF content hashes, computes diagnostic features and emits
`buildings.json`, `review-queue.json` and `report.json`. Source coverage is the
fraction of required original PDFs whose bytes were verified. Width agreement
uses the retained cross-view difference and sampling bound. Plan-normalization
reviews use their two printed/elevation differences and the existing 0.25 m
comparison rule. Boundary support is perimeter-weighted drawing proximity;
opening support counts unique complete trace refinement candidates. These are
separate: proximity can be high while opening support remains zero. Missing
metrics remain zero and are listed explicitly. Topology quality here means the
shared mesh checks passed, not that open surfaces form a complete closed building.

The feed's identity gate stays false: retained study previews do not establish
independent physical assembly identity. Matching widths alone do not establish
it either. A proposed or unknown study cannot pass the existing-source gate.
Missing PDFs remain reported; corrupt checksum-named PDFs reject that candidate.
One failed building does not prevent the other entries from being prepared.
Run `batch --job fresh-feed/buildings.json` for normal eligibility processing.
This is automatic translation of retained evidence, not automatic discovery of
new outlines from arbitrary PDFs. Retained raster traces still carry their
manual origin.

The queue supplies candidate hashes, computed features and full original source
sets, with empty review outcomes. External review decisions use version
`building-review-decisions-v1`, and each record supplies `building_id`,
`candidate_sha256`, `outcome`, `review_basis` and a nonempty `review_reference`.

```bash
python -m voxel_mapper.building_pipeline collect-feedback \
  --queue fresh-feed/review-queue.json --decisions independent-reviews.json \
  --output reviewed-feedback.json
```

The collector binds decisions to the exact queued candidate and copies its
computed features/source set; it refuses unknown/duplicate candidates, altered
queue content and model-prediction review bases. The resulting feedback feeds
`train`/`iterate` directly. Review references are audit pointers, not authenticated
signatures, and queue integrity hashes do not prevent an authorized producer from
creating a different queue. No successful export, proposed drawing or geometric
consistency check is automatically labelled physically correct.

Real replay now computes features for the Mutiny north-range model and Wicker
shop. Mutiny's three original PDFs are verified; the shop's three referenced PDFs
are absent from the retained Mutiny corpus and remain missing. Its proposed state
is preserved. Both candidates remain ineligible because physical identity is
unresolved. No real training labels or activated model are fabricated. See
`docs/evidence/building-source-feed-validation.json`.


## Shared native surface compiler

`building_native.compile_spec` takes the same building spec as the GLB generator.
It samples non-roof surfaces at half-metre centres using each triangle's dominant
projection, unions the sampled occupancy and chooses native full blocks for walls, partitions, floors and towers.
Slabs are reserved for roofs and detail components whose vertical extent is
strictly below 0.75 m; horizontal wall thickness does not trigger that exception.
Non-roof stairs are disabled. If a full block would occupy protected opening air,
that block is withheld and counted rather than using a partial wall shape. At equal error it prefers retaining source occupancy; a rotated surface
cannot disappear merely because air ties a representable shape. It remains a
surface compiler: thick solid interiors are not filled, and absent rooms/walls
are never inferred. Small details can disappear and sampling/alias counts are
retained in the audit.

Roofs use metre-column centre samples of the highest source face within each
component. Source tops round to half-metre courses with at most 0.25 m rounding
error. Closed components retain their sampled bottom extent; separate overlaid
roof components retain their separate levels. Neighbouring courses within the
same component receive bounded wooden risers. Roof shapes are dark-oak slabs or
planks; no wooden roof stairs or glass are emitted. Non-roof surfaces use stone
brick display blocks; low detail components can use stone slabs. These palettes are illustrative, not recovered materials.

Extrusion holes automatically supply protected air over their native alias
interval. Imports also retain explicit study passage/dormer constraints, planar
opening polygons and level base-opening segments. Their air guards are display
quantization: a one-block alias column can be wider than a narrow source opening.
They do not establish physical clearance. Roof and masonry shape selection cannot
occupy those guarded halves. Masonry takes precedence at mixed-material roof
aliases, and withheld roof cells are counted. This can leave unresolved joins;
it does not certify a connected roof or watertight native shell. Original meshes
are unchanged.

```bash
python -m voxel_mapper.building_pipeline compile-native \
  --spec building-spec.json --output fresh-native-preview --world
```

Without `--world`, the compiler writes native rows and the quality report. With
it, the existing Bedrock composer adds an explicitly artificial platform and
exports `park.mcworld`; its cold readback verifies written blocks and unwritten
air. Extent/work/air budgets refuse oversized geometry before native rows are
published. Existing output directories are never overwritten.

A `building-batch-v1` job can set `native_output` to `cells` or `world` (default
`none`). Normal candidate evidence gates still apply. Eligible selected candidates
then run the shared native compiler automatically, and the normal iteration loop
uses that same job setting. An invalid candidate is not silently published simply
because its learned score is high. Independent `compile-native` is an isolated
preview operation and does not bypass acceptance for a cumulative park world.

Real replay compiles all Mutiny V12 components and the Wicker shop mesh layers
using this one path. Both export verified isolated worlds. These are experimental
surface previews, not replacements for the reviewed building-specific worlds;
aliasing and unresolved joins remain visible in quality reports. See
`docs/evidence/building-native-validation.json`. Full raw-PDF geometry discovery,
source material assignment, stronger native support/closure checks and accepted
park placement remain unfinished.


The v2 native block policy implements full-block walls and ground. Floors extend
below their source top, preserving drawn floor zero and standing air. A 0.75 m
vertical detail uses full blocks; the slab exception is strictly below that value.
Roof slab behaviour is retained. `full_blocks_withheld_for_air` reports masonry
that cannot meet both the full-block rule and an opening guard. This can alter the
voxel silhouette around openings; the source meshes remain unchanged.
