# Native annotation extraction on real Wicker sheets

The park job now has an optional spatial annotation stage for ordinary native PDF drawings. It extracts actual glyph positions, text direction, page rotation, paint sequence, explicit units, level candidates, material wording, slope ratios and view labels. It supplies evidence for future component matching; it does not supply an accepted feature feed.

Four original PDFs were reacquired from their previously retained official attachment URLs and checked against the repository's SHA256 records. The tested versions are shop elevations (163937), maintenance plans/elevations (163939), existing site sections (160146) and proposed site sections (160147). Source records remain in `evidence/wicker-shop-drawing-sources.json`, `wicker-architectural-extra-sources.json` and `wicker-site-section-sources.json`.

## Actual results

| Evidence | Count |
| --- | ---: |
| Positioned annotation records | 118 |
| Level claims | 13 |
| Material-note claims | 10 |
| Explicit unit-bearing dimension claims | 18 |
| Untyped numeric claims | 55 |
| View labels | 13 |
| Source-state wording | 8 |
| Slope ratios | 1 |
| Area labels | 2 |
| Records withheld by visibility screening | 13 |
| Consistent adjacent level/numeric candidates | 7 |
| Conflicting adjacent level/numeric candidates | 1 |
| Accepted controls / checkpoints / world additions | 0 / 0 / 0 |

Claims can overlap. Explicit lengths include section datum/scale labels; these counts are not measured component dimensions. Areas are printed claims, not verified footprints.

The maintenance sheet contains a bridge label with a candidate height of 185.80 and an adjacent untyped numeric value of 185400. Under a candidate millimetre interpretation, these differ by 0.40 m. The extractor records the conflict and retains both source identities. It chooses neither height and does not certify the numeric units, component association or vertical datum.

The proposed section also retains earlier title text. State words are retained as evidence rather than treated as verified current geometry. Optional layers, invisible text and later filled paint overlapping a text box trigger visibility withholding. No detected overlap is only a screening result: clipping, blend modes, white text and other rendering effects still need a visibility-aware adapter or review.

PDFs may split one label into several native spans. The extractor joins only adjacent collinear fragments with matching font/rendering properties, bounded sequence gaps and close baselines. It retains every original trace index and paint sequence. The slope annotation in the maintenance plan is recovered this way without OCR or manual text rewriting. Adjacent numeric comparisons retain all spatially compatible candidates; ambiguous neighbors are not resolved by selecting the nearest.

The proposed section has 287,666 paint operations. Overlap screening uses bounded NumPy array comparisons, with ceilings of 500,000 paint operations, 10,000 native spans and 500,000 characters per page. Each PDF is bounded to 20 MB and 1,000 pages. Batches allow 1,000 documents and 10,000 pages. These bounds are not whole-park throughput measurements.

## Replay and integration

With the four exact PDFs named `<sha256>.pdf` in a local directory:

```sh
python scripts/replay_wicker_annotations.py \
  --pdf-directory /path/to/pdfs --output /path/to/fresh-review
```

The replay script resolves the four source records from the repository and verifies PDF bytes before extraction. `evidence/wicker-native-annotation-report.json` retains the full output hash. `evidence/wicker-native-annotation-review.json` is a readable projection of all records that omits glyph origins; the replay reproduces those origins and the complete JSONL hash.

For other drawings, a document list contains entries with `file` and `sha256`, plus optional source context. Paths are relative to the list. Run `python -m voxel_mapper.drawing_annotations --documents documents.json --output annotations`.

Add this configuration to an existing park job:

```json
{"drawing_annotations":{"enabled":true,"documents":"documents.json","max_pages":10000}}
```

The reconstruction/compile stage retains the annotation report and pins its inputs and output checksum. It never appends annotation records to geometry feeds. Completed output can be reused only with unchanged pinned bytes and valid output checksums. Interrupted runs require a fresh output directory.

## Placement requirements still unresolved

These four sheets do not establish independently verified survey controls/checkpoints. Page coordinates remain unrotated MuPDF points, not metre coordinates in the park grid. Labels with apparent absolute heights do not establish ODN by themselves. Planning materials and proposals are not automatically verified as-built materials.

The next adapter must bind annotation evidence to identified component outlines/view geometry and resolve contradictory values. Actual placement also requires independent horizontal reference evidence, a verified vertical datum and source-state evidence. No real Wicker world preview is generated by this change.
