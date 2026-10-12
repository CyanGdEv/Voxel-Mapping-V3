# Curved boundaries and open-line extraction

`voxel-drawing-geometry` extends native candidate extraction to cubic Bezier curves, closed polygon boundaries, quadrilaterals and open stroked subpaths. Disconnected subpaths remain separate lines. Filled groups preserve even-odd/nonzero winding and holes; open strokes are not filled or buffered into invented footprints.

Curves use adaptive de Casteljau subdivision. Each retained segment has a control-hull-to-chord distance bound; default tolerance is 0.25 native PDF points. The output retains the requested tolerance, maximum chord bound, cubic count and point count. Actual geometry, PDF/page identity, extraction version/contract and paint/subpath references are retained. Duplicate outlines retain bounded paint provenance and the worst recorded curve error; truncated provenance is explicitly marked and cannot be promoted.

Printed stroke widths and dash patterns are drawing style only. They do not become path widths, fence thicknesses, materials or ride dimensions. Candidates remain unclassified and unregistered, including symbols and annotations that pass geometric filters. No line label proximity or line length establishes a physical object.

## Run the expanded corpus

```bash
python -m voxel_mapper.drawing_geometry \
  --corpus park-build/corpus --output park-build/drawing-geometry \
  --max-pages 10000 --curve-tolerance 0.25
```

Outputs are streamed `geometry-candidates.jsonl`, `polygon-candidates.jsonl` and `line-candidates.jsonl`, plus `geometry-report.json` with hashes. The polygon feed can enter the existing [footprint matcher](footprint-matching.md) and [boundary registration](boundary-registration.md). Matching reads the exact retained geometry page record and rechecks source PDFs, rather than accepting an unrelated legacy extraction.

Per-page defaults: 100,000 raw paint paths, 4,000 candidates and 200,000 retained points. Each paint group allows 10,000 flattened points/100 subpaths; cubic subdivision allows 16 levels. Bounds and candidate budgets are explicit; a budget hit retains a partial queue with a reported deferral. Unknown layers, nonopaque paint, compositing groups, unsupported clips, paths crossing a clip, crop edges, small glyph/symbol candidates and self-crossing open lines remain rejected. Empty clips withhold their scope rather than failing the whole page. Failed page analyses retry on resume; completed pages skip extraction. Source bytes are checksum checked again and corrupt blobs are excluded from output.

PyMuPDF materializes a page's raw paint list before the path-count gate. These page budgets are not a whole-parser memory benchmark or a 2.5-million-feature native export claim.

## Explicit promotion

The existing footprint promoter now accepts these current retained polygon and planar-line records. All physical identity, reuse, existing/as-built state, page-bound registration, independently sourced checkpoints and validated-domain rules still apply.

| Geometry | Additional review |
| --- | --- |
| Curved polygon or line | `curve_approximation_reviewed: true` plus `approximation_verification_reference` |
| Path line | `line_role: centerline` plus `line_role_verification_reference`; separate measured width and surface evidence |
| Wall/fence line | Reviewed `centerline` or `boundary` role plus `line_role_verification_reference`; separate height/material evidence |
| 2D ride line | Not promoted as a ride track; the ride generator requires measured or explicitly estimated 3D route/elevations |

For curved candidates the accepted registration scale converts the chord bound into metres. Curve error plus independent checkpoint maximum error must fit the review tolerance. The complete error envelope must lie in the validated domain. Incomplete paint provenance and altered geometry/error certificates are rejected against the current retained extraction. Polygon-reference overlap cannot verify a line role.

Use the same `voxel_mapper.drawing_footprints` promotion CLI with `--candidates geometry-candidates.jsonl`. Generator checks still withhold missing widths, heights, materials and datums. Promotion writes Feature records; compilation remains a separate decision.

## Park-job integration

```json
"drawing_geometry": {
  "enabled": true,
  "max_pages": 10000,
  "curve_tolerance_points": 0.25
}
```

Optional `feature_reviews` points to the explicit review list. Use one combined extraction review list per job. When this stage is enabled, matching/boundary stages use its polygon feed and promotion uses its combined feed. The example job enables this stage and disables duplicate legacy extraction. Existing legacy jobs still work; changed configuration needs a fresh work directory.

## Actual recovered Alton result

All 818 pages from 309 checksum-valid PDFs were processed. Final extraction retained 211,831 candidates: 38,772 polygons and 173,059 open lines, including 18,602 curved candidates. There are 790 complete candidate pages, 22 pages withheld by the raw-path budget and six partial candidate pages. Seven initially failed pages were recovered after empty-clip handling was corrected. No document errors or accepted world additions are claimed.

The expanded polygon feed was compared against 92 mapped polygon references. These are source/name/shape hypotheses, not confirmed park features; see `evidence/drawing-geometry-validation.json` for final matching counts and hashes. Open-line association with real fences, paths and ride structures remains an explicit review task.

All 101 focused tests and 525 full-suite tests pass. Twelve new tests cover dense-sampled curve accuracy, backtracking/depth limits, hole/rotation preservation, open/disconnected subpaths, clip/opacity rejection, candidate/point budgets, reviewed curve and line gates, current-record matching, source tampering and a real-PDF synthetic park job through promotion, compilation, 42 wall cells, tile export and identical resume. No Alton candidate was promoted or placed into a new native world.
