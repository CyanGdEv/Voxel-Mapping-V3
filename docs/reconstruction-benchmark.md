# Geometric reconstruction benchmark

`voxel_mapper.reconstruction_benchmark` compares supplied predictions with a
frozen set of externally reviewed reference geometries. It measures reconstruction
errors independently of candidate-ranker prediction scores. It does not extract
new geometry, authenticate reviews, accept park placement or train/promote a model.
No completed real-park benchmark or trained real-park checkpoint is supplied.

## Run the included engineering example

```sh
python -m voxel_mapper.reconstruction_benchmark \
  --config examples/desktop/reconstruction-benchmark-synthetic.json \
  --output fresh-synthetic-benchmark
```

The three **synthetic** cases deliberately include an exact reconstruction, a
displaced/wrong-height reconstruction and a missing prediction. The command
finishes successfully when measurement succeeds; that does not mean all geometry
passed. Inspect `summary.all_cases_within_thresholds` and the per-case errors in
`report.json`. Missing predictions remain failed/unassessed, with `null` error
values and explicit aggregate denominators. They never count as perfect zero error.

Each run requires a fresh directory and retains `config.json` and `report.json`.
`run(config, output, model=None)` is the desktop/worker API; `evaluate(config,
model=None)` measures without writing. All work runs on the CPU and is bounded
to 128 cases, 100,000 polygon vertices and 32 openings per case.

## Reference contract

A configuration declares:

- `version: "reconstruction-benchmark-v1"`;
- `dataset_kind: "synthetic"` or `"reviewed_real"`;
- a nonempty `coordinate_frame` name and `units: "metres"`;
- `cases`, each with a stable `id`, `building_id`, complete original
  `source_sha256` set, `reference` and `prediction`;
- `reference_sha256`, the digest of the complete reference contract.

Each `reference` includes `geometry`, a nonempty external `review_reference`
and `review_basis: "independent_review"` or `"source_verified"`. These are
declared provenance pointers, not authenticated evidence. Changing
`dataset_kind` to `reviewed_real` does not establish real-world accuracy.

Core geometry contains:

```json
{
  "footprint_m": [[0, 0], [10, 0], [10, 8], [0, 8]],
  "height_m": 4,
  "position_m": [410000, 345000, 120]
}
```

`footprint_m` is a polygon in shared local plan coordinates. It may instead be
`{"exterior": [...], "holes": [[...]]}`. `position_m` is an XYZ placement in
the declared common metric frame. Footprint IoU measures local shape; placement
error measures the separately supplied XYZ origin. No coordinate conversion,
datum repair, rotation search or translation fitting occurs. The caller must
establish compatible axes, units and datums before measurement. A translated
local footprint is measured as supplied; no alignment is optimized away.

An optional `openings_m` list contains nonoverlapping polygons in one common
local comparison plane. Keep different facade planes in separate cases.
An empty list explicitly declares no openings. Omitting the reference field
leaves opening accuracy unassessed. Omitting the prediction field when an
opening reference exists is an incomplete prediction, even when the reference
list is empty. Opening matching does not certify physical clearance.

References must contain all three core fields. A prediction may be `null` or
incomplete so failed extraction is represented in the report. Present but invalid
geometry rejects the run rather than silently becoming a valid prediction.
Polygons must be finite, valid and nonempty; invalid holes, self-intersections,
overlapping openings, Boolean coordinates and excessive geometry are rejected.

Create the reference pin once, before evaluating predictions:

```python
from voxel_mapper.reconstruction_benchmark import reference_digest
config['reference_sha256'] = reference_digest(config)
```

The digest includes dataset kind, frame, units, reference geometry, source sets,
review pointers and case/building IDs. It excludes predictions, allowing several
versions of predictions to be evaluated against exactly the same references.
The checksum detects changes after freezing; it is not a signature or proof that
the test set was never seen. Keep the frozen reference contract independently.
Repeatedly tuning against one benchmark can overfit it; periodically introduce
new, genuinely untouched references.

## Metrics and proposed initial tolerances

| Metric | Default comparison |
| --- | --- |
| Footprint polygon intersection over union, including holes | At least 0.95 |
| Boundary distance | At most 0.25 m |
| Absolute height error | At most 0.25 m |
| Euclidean XYZ placement error | At most 0.50 m |
| Opening match polygon IoU | At least 0.50 |
| Opening precision and recall | At least 0.95 each |

Boundary distance uses GEOS **discrete** Hausdorff distance on the polygon
boundaries, with quarter-edge densification. This is a sampled comparison,
not a guaranteed continuous maximum-error bound. Openings use a maximum-count
one-to-one matching above the IoU threshold, then maximize total overlap.
Unmatched predicted/reference openings count as false positives/false negatives.
An empty prediction set has precision 1 and a nonempty reference then has recall
0; an empty reference set has recall 1 and extra predictions have precision 0.

These are explicit engineering tolerances, not demonstrated physical accuracy
or suitable tolerances for every architectural detail. Override supported values
through `thresholds`; the exact settings remain in the immutable run config and
report. Per-case reports list failed checks. Aggregate reports retain measured
and unassessed case counts alongside mean/minimum/maximum errors.

## Keep benchmark data outside model development

Use `--model CHECKPOINT.json` to validate a recognized neural/logistic checkpoint
and compare benchmark identities/sources against its stored training **and
evaluation** lineage. Any shared building or original source rejects the run,
including a shared PDF associated with a differently named building.

Alternatively or additionally supply a complete explicit `lineage` object:

```json
{
  "training_buildings": [],
  "evaluation_buildings": [],
  "training_sources": [],
  "evaluation_sources": []
}
```

Populate this with all development exposure, including previous iterations.
Some historical logistic checkpoints omit evaluation source hashes; a trained
checkpoint with incomplete lineage requires the complete explicit declaration.
It cannot silently establish unseen-source status. Supplied declarations are
auditable inputs, not authenticated proof of actual exposure. With no checkpoint
or lineage, the report says `lineage_check.status: "not_assessed"`. A successful
comparison against supplied lineage says `"no_declared_overlap"`; it never
claims independence is proven.

Benchmark runs always report zero generated training labels, zero park blocks,
no model promotion and no physical acceptance authorization. A next real pilot
must first obtain independently checked scale, building identity, geometry,
orientation, geographic placement and finished levels. Existing provisional
Wicker studies do not supply that completed reference set automatically.
