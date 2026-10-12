# Data-driven buildings and reviewed learning

The new building-neutral path separates source interpretation, geometry and
learned candidate ranking. `voxel-building-data` (or
`python -m voxel_mapper.building_pipeline`) runs the same generator for different
buildings. It does not yet discover complete building specifications from PDFs.
The existing architectural extraction/review stages need adapters that supply
these specifications, features and verified gate results.

## Shared geometry contract

`building-spec-v1` uses `local_xyz_metres_z_up`, stable building/component IDs,
existing-source hashes, evidence references and explicit assumptions. Each
component is a wall, partition, floor, roof, tower or detail. Geometry can be a
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
checks are still required for park insertion. Native voxel emission for arbitrary
shared specs is not implemented in this increment. Existing study/world exporters
remain available and unchanged. Existing roof meshes retain their slab courses.

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
