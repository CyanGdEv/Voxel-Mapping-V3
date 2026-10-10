# Wicker Man retained-area pipeline test

This bounded replay selects the retained original SW8 application
(SMD/2016/0315) and woodland-path amendment (SMD/2017/0111). Selection uses
application identity and checksum-valid downloaded blobs, rather than a title
keyword or invented area boundary. The application sheets can include wider
context; record counts do not measure physical objects inside the ride area.

```sh
python scripts/replay_wicker_area.py \
  --corpus work/viewport-corpus \
  --candidates work/corpus-outline-geometry/geometry-candidates.jsonl \
  --references work/physical-references/physical-references.geojson \
  --reference-report work/physical-references/reference-report.json \
  --output work/wicker-area-replay
```

The script checks source PDF hashes, selects all candidate-bearing application
pages, recovers exact straight-stroke faces, runs the current map comparison
placement, probes unreviewed raw candidate promotion and checks identical
completed resume. It does not invent feature reviews or independently sourced
checkpoints. The EPSG:27700 argument in the negative promotion probe is never
used for transformation: missing identity or line-role evidence rejects each
record first. Actual map comparison uses the retained park CRS.

## Result

Eleven distinct PDFs supplied 43 candidate-bearing pages and 15,360 raw drawing
records (2,245 polygons and 13,115 lines). Recovery added 906 enclosed faces,
giving 16,266 combined records. Only five pages contained eligible line networks;
38 contained no eligible solid straight linework. Curved and dashed linework
remains outside this exact-face recovery method.

Placement checked all combined records, trying 4,333 boundary pairs and 13,116
orientations. All 43 sheets were withheld: no qualifying shared-outline
placement emerged. Completed recovery and placement resume were identical;
source and output checksums were rechecked. Twenty-four focused tests passed
for Wicker registration/reconstruction, placement and boundary recovery.

This does not demonstrate world generation. Zero physical features were
approved and zero world blocks were added. The pipeline stops before compilation
and world export because there is no accepted registration or physical review.

## Next evidence work

The inventory includes two pre-construction existing plans, the proposed
woodland path, landscape/planting sheets and supporting impact/arboricultural
assessments. It is not a complete set of current ride engineering drawings.
Previous locally reconstructed Wicker previews are not independent verification
for these application sheets.

1. Retrieve and cross-reference retained detailed ride/site drawing sources,
   separating original proposals from amendments and current physical state.
2. Identify exact shared physical landmarks on a useful site plan and obtain
   independent checkpoint measurements with known CRS and source provenance.
3. Review physical paths, buildings, walls and fences with measured dimensions,
   materials and terrain levels; reconstruct ride geometry only with supported
   3D route/elevation evidence.
4. Promote accepted records, compile a bounded test, then check saved world
   blocks against the accepted input geometry.

The receipt and complete page outcomes are in
`evidence/wicker-area-pipeline-validation.json` and
`evidence/wicker-area-sheet-placements.jsonl`. Recovery outcomes are in
`evidence/wicker-area-page-recovery.jsonl`. These files retain failed outcomes,
not just successful samples.
