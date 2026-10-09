# Boundary and corner registration

This stage tests the shape/name shortlists against full polygon boundaries. It proposes orientation-preserving similarity transforms (rotation, translation and uniform scale). It fits bounded exterior samples and, where available, sharp simplified corners. Simplification is used for fitting only: overlap and boundary distance are measured against the original polygons, including holes. It never warps an outline to make it agree or replaces the retained drawing geometry.

The best hypothesis retains its matrix, translation, metres per PDF point, rotation, sample residual, original-geometry IoU and Hausdorff boundary error. Corner correspondences remain explicitly unverified. Alternative near-equivalent orientations are retained: a perfect rectangle match can still be ambiguous. Multipart outlines, mismatched hole counts and excessive vertex counts are withheld.

Fits below 0.85 IoU or above 0.05 area-normalized boundary error are flagged. Native printed scale denominators are compared using `denominator * 0.0254 / 72` metres per PDF point. Missing, multiple or disagreeing scale candidates are flagged separately. Text scales may refer to another viewport; even an unflagged boundary hypothesis cannot establish physical identity, placement accuracy, construction state, geometry reuse or elevations.

## Run the review queue

```bash
python -m voxel_mapper.boundary_registration \
  --candidates park-build/footprints/footprint-candidates.jsonl \
  --matching-directory park-build/footprint-matching \
  --references park-polygons.geojson --reference-crs EPSG:4326 \
  --target-crs EPSG:27700 --corpus park-build/corpus \
  --output park-build/boundary-registration --max-fits 10000
```

Input candidates, association receipts, mapped references, original PDFs and current extracted page records are checked. Output consists of streamed `boundary-hypotheses.jsonl` and a completion receipt `boundary-report.json`. Use a fresh directory. Fit budgets defer excess comparisons explicitly; they do not accept unexamined geometry. There are no native-world additions from this stage.

## Independently reviewed registration

Optional `--registration-reviews reviews.json` accepts up to 10,000 review specifications. Each binds `candidate_id`, `document_sha256`, `page`, `reference_id`, `reference_sha256` and `target_crs` to the exact hypothesis. The remaining fields follow the native review specification in [drawing-batch.md](drawing-batch.md): `local_frame: pdf_native_points_y_up`, `landmark_identity_reviewed: true`, `expected_metres_per_pdf_point`, `controls`, `checkpoints`, and optional tolerances.

At least three noncollinear controls and two independently sourced checkpoints are recomputed through the existing registration review. Every pair needs an identity, local/target XY, source ID and SHA256; checkpoints also require `independent: true`. Checkpoint hashes must differ from control, candidate-PDF and boundary-reference hashes; relabelling the same evidence under another source ID does not establish independence. Points must lie within the native crop. The reviewed transform must agree with one boundary orientation within the review tolerance and cover the entire original polygon within its validated control/checkpoint domain.

An accepted `independent_review` can supply the page-bound `horizontal_registration_review` for explicit footprint promotion. It is still horizontal evidence only. Physical identity, existing/as-built state, reuse permission, dimensions, materials and vertical datum remain the separate gates in [drawing-footprints.md](drawing-footprints.md). Boundary fitting creates no reviewed controls or checkpoints automatically.

## Park-job integration

Beside enabled `footprint_extraction` and configured `footprint_matching`, add:

```json
"boundary_registration": {
  "enabled": true,
  "max_fits": 10000
}
```

Add `"reviews": "registration-reviews.json"` when independently reviewed pairs exist. Job resume checks hashes of candidates, associations, reference geometry, canonical review content and outputs, plus version/CRS/budget. Changed reviews require a fresh job. An incomplete output has no completion receipt and must be discarded before retry.

## Actual Alton result

2,070 comparisons were attempted from the 970 shortlisted drawing polygons. 2,031 produced boundary hypotheses and 39 were withheld. Overlapping flags include 1,419 ambiguous orientations, 954 poor boundary matches, 1,688 printed-scale disagreements, 317 missing scales and 26 ambiguous scales. None had both strong boundary agreement and one usable printed scale. No independent Alton review was supplied, no registration was accepted, and world additions remain zero.

Eight new tests cover known rotation/scale recovery, symmetry, hole preservation, printed-scale rejection, exact source binding, independent-evidence rejection, domain extrapolation, and a real-PDF park job that accepts a synthetic checked review, resumes, and rejects altered reviews. This fixture establishes pipeline behavior, not real Alton survey accuracy. Source and validation summaries are retained in `evidence/boundary-registration-validation.json`.

Retained archive recovery, native coordinate origin correction and the expanded anchor audit: [anchor-audit.md](anchor-audit.md).
