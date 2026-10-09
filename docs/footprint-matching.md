# Whole-park footprint association and revision review

The matching stage writes review queues, never blocks or accepted identities. It compares each native-sheet polygon with mapped polygon references, retaining three hypotheses at most. Unplaced candidates use scale/rotation-independent aspect and fill ratios: absolute size, position and overlap remain null. Exact native text labels count only when their centres lie strictly inside one retained polygon. Names inside overlapping polygons, holes or outside boundaries do not qualify. Source PDFs are checksum checked and candidates must equal the current retained page extraction. Name/shape disagreement is flagged explicitly.

Once explicitly reviewed polygon Feature records exist in the target projected metre CRS, a separate pass compares location (within 25 m), area ratio, shape and intersection over union. Mapped reference geometry remains comparison evidence; it does not establish independent survey accuracy. Associations must still pass the promotion rules in [drawing-footprints.md](drawing-footprints.md).

A disk-based SQLite R-tree compares registered same-family polygon overlaps. Equal geometry is flagged as a duplicate; overlap above 0.1 IoU enters revision review. Both feature/source/PDF identities and drawing states remain in each decision. Chronology is recorded only with a shared explicit `sheet_key`, canonical ISO `issue_date` values, and `sheet_revision_reference` evidence on both records. Neither date nor revision label selects a winner or proves that a proposal was built. `selected_feature_id` always remains null. Reviewed promotion can retain these fields plus an explicitly reviewed `name` and `revision` label.

## Run a corpus association queue

```bash
python -m voxel_mapper.footprint_matching \
  --candidates park-build/footprints/footprint-candidates.jsonl \
  --references park-polygons.geojson --reference-crs EPSG:4326 \
  --target-crs EPSG:27700 --corpus park-build/corpus \
  --output park-build/footprint-matching
```

Supply `--registered-features reviewed-polygons.jsonl` to also produce geographic associations and revision decisions. These must be reviewed polygon records with matching `metadata.geometry_crs`, `candidate_id` and `physical_verification_reference`; this tool does not approve registration itself. The compiler and footprint promoter remain the acceptance gates. Nonpolygon ride, fence and support geometry require their separate reconstruction generators.

Outputs are `associations.jsonl`, `revision-review.jsonl`, `review-index.sqlite` and `matching-report.json`. Inputs and JSONL outputs have SHA256 receipts. Use a fresh output directory; a failed run has no completion report and must be discarded before retrying. Reference sets are capped at 5,000 objects, record streams at 2,500,000 and individual JSONL lines at 8 MB. A dense spatial neighbourhood above 10,000 comparisons per feature aborts explicitly; partition that review job. The matcher has not been benchmarked at 2.5 million records. The existing compiler ceiling benchmark is separate.

## Include in an acquisition job

Add this optional section beside enabled `footprint_extraction`:

```json
"footprint_matching": {
  "enabled": true,
  "references": "park-polygons.geojson",
  "reference_crs": "EPSG:4326",
  "target_crs": "EPSG:27700",
  "max_records": 2500000
}
```

The park runner generates the unplaced queue after extraction. On resume it checks input hashes, CRS, version, budgets and output hashes before reusing the report. Changed inputs require a fresh job. Registered revision reconciliation runs through the CLI after reviewed polygon records exist; acquisition cannot supply their placement.

## Recovered Alton corpus result

4,193 polygons were compared with 92 mapped polygon references from 144 named mapped features. The other 52 references were nonpolygon or invalid for this comparison. 970 polygons received weak shape/name shortlists. Three contained a unique interior “The Boating Lake” label, but each has a large shape discrepancy (~0.68); all are flagged for name/shape disagreement. These may be enclosing outlines or annotation shapes and are not confirmed lake footprints. No Alton registered records were supplied, so the revision queue is empty and world additions are zero.

67 focused tests pass, including unique/ambiguous real-PDF labels, source tampering, target-frame matching, revision ordering, retained proposal/existing conflicts, checksum-verified park-job resume and sheet provenance retention. Full-suite results are recorded in `evidence/footprint-matching-validation.json`.

Boundary/corner similarity hypotheses and independently checked registration: [boundary-registration.md](boundary-registration.md).
