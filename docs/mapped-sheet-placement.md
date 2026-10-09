# Provisional map-based sheet placement

The verified registration route still needs measured controls, independent
checkpoints and physical-object review. It is separate from the new
`mapped-sheet-placement-v2` route, which positions native planning geometry for
inspection using explicitly estimated map agreement.

The previous descriptor-only search retained three aspect/fill matches and only
64 verification objects. Correct irregular landmarks could be absent before a
fit was tried. This route prioritises up to 64 large distinctive seed outlines,
compares their full boundaries against up to eight descriptor alternatives, and
checks each seed transform against **all** retained polygon objects on the page
using spatial reference neighbours. At least three nonoverlapping, distinct,
noncollinear outline correspondences must survive centroid refitting. Duplicate
paints and nested polygons cannot inflate support. Different map locations
remain competing alternatives; no positioned feed is emitted for ambiguous
sheets.

Map agreement thresholds default to 70% outline IoU and 10 m maximum centroid
error. These are **review search thresholds**, not tolerances for accepted survey
registration. RMS and maximum centroid errors, individual overlap scores,
reference identities and source hashes accompany every proposal. No fit accepts
materials, construction state, elevation or physical semantics.

```sh
python -m voxel_mapper.mapped_sheet_placement \
  --corpus work/corpus \
  --candidates work/drawing-components/component-candidates.jsonl \
  --references work/physical-references/physical-references.geojson \
  --reference-crs EPSG:4326 --target-crs '<retained projected park CRS>' \
  --sheets selected-sheets.json --output work/mapped-placement
```

Selection is an optional JSON list of `["PDF_SHA256", page_number]` pairs.
Without selection, candidate-bearing pages are processed in disk-backed groups.
The CLI uses 512 seed fits per page; maximum is 2,000. All input records are bound
to current retained extraction and original PDF bytes. Limits are 2.5 million
input records, 20,000 records per page, 5,000 references and 10,000 selected
sheets. This is a bounded search, not an exhaustive-placement guarantee.

Outputs:

* `sheet-placements.jsonl`: estimated transforms and matched-outline diagnostics.
* `placed-review-geometry.jsonl`: source-linked GeoJSON Features in the target
  CRS, including holes and lines, wholly inside the convex envelope of matched
  outlines. Crossing geometry is withheld rather than clipped. This envelope is
  **unverified**, and is not an accepted registration domain.
* `placement-report.json`: source/input/output hashes, budgets and counts.

These review Features are not reconstruction `Feature` records and do not enter
the block generator. Every record retains `registration_verified: false`,
`physical_identity_verified: false` and zero world additions. Generic lines may
still represent hatching, labels or symbols. No automatic physical-object
classification or world generation is implied by positioning them.

A park job can enable `mapped_placement` independently of descriptor matching:

```json
"mapped_placement": {
  "enabled": true,
  "references": "physical-references.geojson",
  "reference_crs": "EPSG:4326",
  "target_crs": "<retained projected park CRS>",
  "sheets": "selected-sheets.json"
}
```

The stage requires retained drawing geometry or footprint extraction. Completed
outputs and PDF hashes are rechecked on resume. Interrupted jobs revalidate and
reindex original candidate records, then reuse committed per-sheet fits from a
WAL SQLite checkpoint. The checkpoint binds job inputs, per-page candidate hashes
and cached result hashes. Changed inputs, damaged results and failed SQLite
integrity checks are refused. Output feeds are rebuilt and published only when
the full run completes. A progress callback can report completed/cached sheets.
Centroid-distance spatial queries now discard distant reference comparisons
before transforming full outlines, and shape descriptors are computed once.
Independent verification remains the next step for any proposed transform:
identify control attachment points and separately sourced checkpoint evidence,
review current physical objects and dimensions, then use the existing checked
registration/promotion route. Mapped outline centroids cannot be relabelled as
independent survey checkpoints.

## Retained Alton replay

The first ten ranked sheets supplied 23,586 source-checked geometry records.
Four sheets produced provisional placements; they form two identical-fit pairs,
not four independent controls. Supports per fit are 21 or 22 distinct outlines;
centroid RMS is 1.30 or 2.07 m, with maximum error 2.71 or 7.72 m. Six sheets
remain withheld. The stage positioned 3,407 review records (524 polygons and
2,883 lines) and withheld 4,169 records crossing/outside the matched envelopes.
These counts are drawing records, not confirmed physical park objects.

The original verified route found no qualifying fit; its thresholds and gates
are unchanged. The new result fixes search and review placement, while making
map generalisation and missing independent verification explicit. Source/output
hashes and identical resume were rechecked. All 578 repository tests pass,
including nine new tests.

Receipts: `evidence/alton-mapped-placement-validation.json`; complete sheet
proposals: `evidence/alton-mapped-sheet-placements.jsonl`; traceable 22-outline
sample: `evidence/alton-mapped-placement-sample.geojson`; comparison preview:
`evidence/alton-mapped-placement-preview.svg`. Use the receipts' sheet selection,
thresholds, candidate/reference hashes and projected CRS to reproduce the full
review feed from retained component candidates and park-domain references.

The earlier ten-sheet receipts use v1. V2 needs a fresh output directory when
upgrading; run-bound placement IDs change with the version even when fitted
geometry is identical.

## Whole-corpus replay and failure triage

V2 checked all 212,104 component records on 353 candidate-bearing sheets against
246 retained park-domain comparison polygons. It tried 50,711 full-boundary
seeds. Seven sheets have one provisional placement, three have competing
placements and emit no positioned geometry, and 343 are withheld. The single
placements form four exact transform groups, not seven independent checks.
There are 3,747 positioned review records: 546 polygons and 3,201 lines. Another
13,395 records cross or lie outside the matched envelopes and are withheld.

Of the 343 unplaced sheets, 48 have fewer than three polygon objects and 295
have no shared outline agreement under this search. These are diagnostic
categories, not explanations of every underlying source problem. Source title
hints flag 36 pages for floor-plan/elevation/section review; source state is not
confirmed existing on 307 pages. Those flags overlap the search outcomes and
do not establish present construction state.

```sh
python -m voxel_mapper.placement_diagnostics \
  --placement-directory work/mapped-placement \
  --queue evidence/alton-outline-alignment-queue.jsonl \
  --output work/placement-triage
```

The triage queue retains rank, original application/attachment links, polygon
and seed counts, hypotheses/supports/residuals and pending review flags. Its
input receipt and full feed hashes are checked; unknown or duplicate pages are
refused. All 353 page fits are checkpointed with a clean integrity check.
Completed resume and final output hashes pass. The earlier ten-sheet proposal
results remain exactly equal. All 580 tests pass, including interrupted-fit reuse
with identical output feeds and rejection of altered cached results.

See `evidence/alton-whole-placement-validation.json`,
`evidence/alton-whole-sheet-placements.jsonl` and
`evidence/alton-whole-placement-triage.jsonl`. Placement and physical identity
remain unverified; this replay adds no world blocks. The next review should
verify the strong, distinct landmark sets and inspect closed-outline recovery
or landmark correspondences for the highest-priority unmatched plans.
