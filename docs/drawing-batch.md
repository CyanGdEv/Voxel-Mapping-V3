# Batch drawing triage and alignment

The park runner now performs drawing analysis after acquisition and page inventory. It writes `drawing-analysis.jsonl` and `drawing-analysis-report.json` under the corpus directory, with resumable page results in `corpus.sqlite`. Run it independently:

```
python -m voxel_mapper.drawing_batch --corpus /path/to/corpus
```

Use `--classification-only` to skip coordinate inspection, `--max-pages` to bound newly analyzed pages per run, and `--reviews reviews.json` for supplied independent registration evidence. Park jobs can set `drawing_analysis` with `enabled`, `registration`, `max_pages` and a relative `reviews` file path. Analysis is enabled by default and can be disabled explicitly.

## What the first pass does

Each page retains its PDF hash, application links, titles and page number. Title matches and bounded native text classify it into site plans, ride layouts, elevations/sections, landscape/paths, structural details, surveys, water/drainage, reports or location plans. Multiple equally ranked categories remain ambiguous; unmatched pages remain unclassified. Titles have stronger weight than text, and multiple categories remain visible. These are heuristic triage labels, not extracted physical objects.

Scale ratios, level labels and materials remain **unplaced candidates**. A scale ratio alone cannot place a drawing. Existing, proposed, as-built and unknown labels are retained separately; conflicting labels produce a mixed candidate. No label is automatically authoritative evidence of the current park.

Alignment inspection checks supported GeoPDF metadata, then explicit leader-connected crosshairs and labelled survey grids when metadata is absent. Internally consistent results remain candidates, with independent accuracy unverified. Missing controls, unsupported page rotation/units and content budgets produce explicit reasons. Display rotations of 0/90/180/270 degrees are inspected in native coordinates without saving changes to the source PDF. Non-default UserUnit values remain unsupported. OCR and named-landmark candidates are described below. Neither a north arrow nor a scale bar alone supplies geographic placement.

Coordinate frames are explicit: the page inventory uses PyMuPDF points with Y down; registration controls use native PDF points with Y up. They must not be interchanged. PDF hashes are rechecked before cached results are exported. Changing catalogue state/titles, analysis options or review inputs invalidates the corresponding cache. Previous analysis versions remain in SQLite.

## Supplying a registration review

The review file is a JSON array. Each entry identifies exactly one PDF hash and one-based page number, and supplies:

| Field | Required evidence |
| --- | --- |
| `document_sha256`, `page` | Exact source PDF and page identity |
| `local_frame` | `pdf_native_points_y_up` |
| `landmark_identity_reviewed` | Explicit true assertion that corresponding landmarks were reviewed |
| `target_crs` | Declared projected metre CRS |
| `expected_metres_per_pdf_point` | Independently established drawing scale |
| `controls` | At least three non-collinear point pairs |
| `checkpoints` | At least two independent point pairs |
| `tolerance_m`, `scale_tolerance` | Optional positive position tolerance and bounded relative scale tolerance |

Each point pair contains `id`, `local: [pdf_x, pdf_y]`, `target: [easting, northing]`, `source_id` and an actual `source_sha256`. Checkpoints also require `independent: true`, distinct identities/coordinates and a source identity/hash different from control sources. Merely duplicating fitted controls as checkpoints is rejected. Local points must lie within the native page crop.

The reviewer recomputes an orientation-preserving similarity fit and checks scale, fitting errors and independent checkpoint errors. An accepted horizontal fit includes its target CRS and the convex hull of validated target points. Existing reconstruction source validation can consume its registration review and reject geometry outside that hull. This stage does not automatically approve construction state, vertical datum or object dimensions, and it does not create world geometry. Landmark identity and survey provenance assertions still need truthful source evidence.

## Original Alton triage result, before OCR and rotation support

The first pass inspected 84 unique PDF blobs / 238 pages. It found 113 reports, 54 unclassified pages, 32 elevations/sections, 13 ambiguous pages, 12 landscape/path pages, 8 location plans, 3 site plans and 3 water/drainage pages. No supported automatic alignment was found: 191 pages need controls; 44 have unsupported rotation/units and 3 exceed the registration content budget. There were no document-level errors. A repeat run reused all 238 results.

That initial pass motivated the rotation, OCR and landmark work below. Physical-object extraction and revision reconciliation remain separate stages. No additional park world has been generated by drawing triage.

## Mixed geometry validation

`python -m scripts.benchmark_park_mixed --output /tmp/park-mixed --features 10000` exercises multi-cell paths, plazas, wooden/metal fences, building shells, rocks, lakes, explicit 3D ride routes/support members and bridge components. The measured fixture compiled 10,000 features into 305,000 cells in 13.46 seconds, resumed them in 0.66 seconds and peaked at 115.00 MiB process RSS. This is synthetic geometry, not architectural accuracy validation against real drawings.

The full-ceiling synthetic test completed and resumed **2,500,000 features**, with 2,500,000 cells/provenance links across 9,800 chunks and 114.38 MiB peak process RSS. It recovered from a disk-full interruption at 1,571,882 committed features; the recovery pass took 310.36 seconds and the final full resume 134.84 seconds. These are plan/compiler checks, not a native world export or real-drawing accuracy result.

## Rotation, OCR and named-landmark pass

The reader removes display rotation from an inspection copy of the native PDF page while retaining its crop box, content coordinates and georeference metadata. It never saves the source PDF. Independently supplied controls still use native PDF points with Y up. OCR rendering respects the displayed page orientation, then converts recognized pixel positions back through display rotation and the original crop offset. Coordinate tests cover all four rotations, including cropped sheets.

OCR runs when native text has fewer than 80 non-whitespace characters. Each page renders in grayscale at no more than 3072 pixels on its longest side and at most 300 DPI. Tesseract receives a bounded timeout and one worker thread. Lines containing a word below 70 confidence are withheld in full. Its labels, materials, levels and scale ratios remain unverified candidates. OCR output does not become geographic coordinate controls or as-built geometry.

Default run budgets allow 50 OCR pages and 180 seconds of OCR work, with a 20-second per-page subprocess timeout. Set `--max-ocr-pages`, `--max-ocr-seconds` or `--no-ocr` on the CLI. The park job's `drawing_analysis` section accepts `ocr`, `max_ocr_pages` and `max_ocr_seconds`. Deferred pages and unavailable/failed OCR attempts are retried within a later run's budget; completed pages retain their hash-bound analysis. Rendering and parsing add some overhead outside the subprocess time limit.

For landmark candidates, supply a named GeoJSON FeatureCollection, its source CRS and a projected metre target CRS:

```
python -m voxel_mapper.drawing_batch --corpus /path/to/corpus \
  --landmarks named-landmarks.geojson --landmark-crs EPSG:4326 \
  --target-crs EPSG:27700
```

The job equivalent uses `drawing_analysis.landmarks`, `landmark_crs` and `target_crs` (or the park manifest's target CRS). The reference feed is hashed and supports up to 5000 named features. Full-line name matching normalizes case, punctuation and a leading “The”. Duplicate labels or reference names remain ambiguous; no nearest-name match is selected. Native and OCR text-box centres are paired with reference geometry centroids as hypotheses. These are not surveyed physical corners. At least three unique names and one scale candidate can produce a similarity hypothesis; missing independent checkpoints prevent approval even when residuals are small. Source independence, landmark identity and positional uncertainty still need review.

The recovered corpus pass used 144 named features from the retained OSM mapping. It normalized 44 rotated sheets and ran OCR on 43 low-text pages. Unclassified pages fell from 54 to 39, and 18 name matches identified Lake View, Mutiny Bay, the Boating Lake, Waste Lane and White Bridge. No page had enough unique names and scale evidence for a named fit; no verified automatic alignment or new world geometry was produced. Four pages remained withheld because their registration content exceeded the budget, and 234 still need controls.

The next stage is available as [native-sheet footprint extraction and reviewed reconstruction](drawing-footprints.md). It preserves supported polygon topology, retains unplaced label hypotheses and can promote explicitly checked candidates into the park job.

Retained archive recovery, native coordinate origin correction and the expanded anchor audit: [anchor-audit.md](anchor-audit.md).
