# Provisional map-based sheet placement

The verified registration route still needs measured controls, independent
checkpoints and physical-object review. It is separate from the new
`mapped-sheet-placement-v1` route, which positions native planning geometry for
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
outputs and PDF hashes are rechecked on resume; incomplete output is refused.
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
