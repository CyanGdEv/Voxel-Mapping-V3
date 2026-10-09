# Drawing footprints and reviewed reconstruction

The extractor converts supported straight PDF paint groups into **native-sheet polygon candidates**. It does not identify physical park objects automatically. Run:

```
python -m voxel_mapper.drawing_footprints \
  --corpus /path/to/corpus --output /path/to/footprints
```

Park jobs can enable the stage with `footprint_extraction: {"enabled": true, "max_pages": 1000}`. Candidates, page decisions and native PDF provenance are stored in the corpus SQLite database; `footprint-candidates.jsonl` and `footprint-report.json` are streamed exports. Repeating the stage skips identical completed pages. Cached results from a missing or corrupt source PDF are excluded.

## Supported boundaries

The extractor uses native PDF points with Y up, retains crop offsets and supports all four display rotations. Supported straight closed strokes and filled compound paths preserve holes. Even-odd fill uses parity; nonzero fill retains ring orientation rather than assuming every nested ring is a hole. Repeated geometry has one candidate identity with all supporting paint ordinals. Identity hashes include the PDF bytes' SHA256, page number and normalized geometry.

Curves, open strokes, unresolved optional layers, transparency, compositing groups and unsupported clipping are withheld. Rectangular clipping is supported only where it fully contains the candidate; intersected/partial shapes are not silently completed. Small symbols, shapes contained in native text spans, large sheet frames and crop-border shapes are filtered. These filters reduce annotations but do not prove physical identity: legends, title boxes or site boundaries can still resemble object footprints.

Native labels suggesting paths, plazas, buildings or water associate only with a unique strict polygon interior. Labels in holes, on boundaries or inside multiple candidates do not identify an object. Label text, type suggestions and containment remain hypotheses. No family, height, material or existing/as-built state is automatically promoted.

Per-page defaults allow 100,000 native drawing records, 2,000 candidates and 10,000 points per paint group. A page above its path budget is withheld; a candidate-budget stop is marked partial. Native rendering materializes a page's drawing list before those path checks. Unsupported compound topology and other paint-group limits retain explicit rejection reasons.

## Promotion requires checked evidence

Once a component has been reviewed, supply a JSON array of feature reviews and a reconstruction manifest:

```
python -m voxel_mapper.drawing_footprints \
  --corpus /path/to/corpus \
  --candidates /path/to/footprints/footprint-candidates.jsonl \
  --feature-reviews reviewed-components.json \
  --manifest park-manifest.json --output reviewed-features.jsonl
```

A promotion run accepts a bounded review array of up to 10,000 components. Larger checked datasets can be promoted in batches and supplied as streamed Feature JSONL feeds to the whole-park compiler. Each review needs:

| Field | Meaning |
| --- | --- |
| `candidate_id` | Exact current candidate identity |
| `feature_id`, `source_id`, `family` | Unique reconstruction identity, declared source and supported polygon family |
| `physical_identity_verified: true` | Explicit review that the boundary is the physical component |
| `verification_reference` | Nonempty record of the physical identity check |
| `reuse_allowed: true` | Explicit geometry-reuse authorization |
| `drawing_state` | `existing` or `as_built` |
| `state_verification_reference` | Evidence for the selected construction state |
| `parameters` | Existing generator parameters with value/source/evidence status |

Supported promotion families are `path`, `plaza`, `building_shell` and `lake`. Material, height, bed/surface elevations and vertical datum remain gated by the existing generators. For example, a polygon path can supply `surface: {"value":"asphalt", "source":"page-source", "status":"documented"}`; an unplaced OCR material label alone does not establish that association.

The planning/CAD source must pin the PDF SHA256, declare the target projected metre CRS, retain an accepted horizontal registration review and bind it to `metadata.registration_document_sha256` and `metadata.registration_page`. Registration controls/checkpoints retain their source identities/hashes; checkpoints must be explicitly independent and use a different source from fitted controls. The promoter recomputes the fit and checks it against the saved matrix. Its transformed boundary and every hole must lie inside the validated control/checkpoint hull. Source reuse restrictions are enforced. Proposed or unknown construction states remain withheld.

The supplied candidate must exactly match the current retained extraction record, and the source PDF checksum is checked again. Stale page identities, modified geometry, altered paint provenance, duplicate feature IDs and missing candidates are rejected. Promoted records retain PDF/page/candidate identity and both physical/state review references. They enter the existing batch compiler as source-linked Feature JSONL; no world cells are created during promotion itself.

## Associating an independently checked landmark

A review can include `checked_landmark` with `id`, `independently_checked: true`, an independent `source_sha256`, declared target `crs` and a valid polygon `geometry`. The transformed candidate must overlap that checked polygon with intersection-over-union of at least 0.75. Disagreement, mismatched CRS or a reference from the same PDF source is withheld. The resulting feature retains the landmark identity, hash and measured overlap. Reference overlap does not replace the explicit physical identity and construction-state reviews.

## One park job

Set `footprint_extraction.feature_reviews` to the review JSON path. The acquisition stage extracts candidates; reconstruction promotes checked candidates, compiles them and exports through the existing tile/native path. Candidate, review and manifest hashes are retained in a completion receipt. Unchanged jobs resume; changed review inputs require a fresh work directory. Empty or withheld records produce no native world package. A standalone promotion can instead feed the job's `feature_records` setting.

## Measured recovered-corpus result

Across 84 retained PDF blobs and 238 pages, the extractor produced **4,193 polygon candidates**, including **40 with unique interior type-label hypotheses**. Three pages exceeded the path budget. All 238 page records resumed on a repeat pass, and there were no document-level errors. These are unplaced drawing polygons, not 4,193 confirmed park objects.

A synthetic reviewed-footprint fixture follows the full route from an actual PDF/corpus candidate through independent registration, promotion, park-job compilation and tile export, producing 400 paving cells. It resumes without duplicating the feature and rejects changed review inputs. Additional tests cover topology, rotations, source corruption, proposal rejection, changed candidate content, altered alignment matrices, landmark disagreement and extrapolation outside the validated domain.

No recovered Alton candidate has been approved or generated into a new park world by this stage. Curved boundaries, line-based fences/routes, stronger semantic identification and reconciliation of overlapping revisions remain further work.

Footprint association and registered revision review queues: see [footprint-matching.md](footprint-matching.md). Optional reviewed sheet metadata (`sheet_key`, ISO `issue_date`, `revision`) requires a `sheet_revision_reference`; it establishes ordering evidence only.

Boundary/corner similarity hypotheses and independently checked registration: [boundary-registration.md](boundary-registration.md).
