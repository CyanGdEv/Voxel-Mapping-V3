# Shop source geometry: route to the first placed test

The revised shop is the first building target. The pipeline now joins candidate elevation regions to their native captions and nominal scales, and follows explicit numbered plan references to those captions. It still produces evidence, not placed geometry.

## Retained real replay

Six original PDFs were verified against their retained SHA256 values: shop elevations (2967-26), maintenance plans/elevations (2967-42), existing and proposed site sections, revised overall roof plan (2967-48), and revised ground-floor plan (2967-21). All belong to the retained planning evidence; current physical/as-built identity remains unverified.

| Evidence | Result |
| --- | ---: |
| Material anchors | 23 |
| Local-contrast region candidates | 17 |
| Candidates linked to roof / wall callouts | 6 / 11 |
| Mixed material regions withheld | 2 |
| Other contrast regions withheld | 4 |
| Shop candidate regions: roof / wall callouts | 3 / 5 |
| Shop native elevation-caption candidates | 4 |
| Nominally scaled shop region candidates | 8 |
| Unique plan-to-elevation reference candidates | 7 |
| Reference candidate withheld | 1 |
| Accepted controls / checkpoints / world additions | 0 / 0 / 0 |

The ground-floor plan produces four unique shop elevation-reference candidates. The roof plan produces three; the fourth marker retains a glyph-screen hold. The eight marker records are candidate links based on exact drawing/view numbers, not nearest-building or nearest-edge guesses. Duplicate target captions remain ambiguous. The shop captions identify views 1–4 to the S.East, S.West, N.West and N.East; their bearing labels are not verified national-grid axes.

A visual overlay of the shop atlas was reviewed. The long elevations now retain broad roof and timber-wall regions. Some boundaries follow protected first/last hatch strokes, and a gable region is a projected/material-anchor hypothesis whose physical roof/wall role remains unresolved. None establishes complete three-dimensional components. Two regions that joined differently numbered roof/wall anchors were explicitly withheld rather than becoming whole-building faces.

The nominal roof width in opposing long elevation views is 16.6864 m. This is derived from the literal 1:100 caption and PDF points; it is not a checked physical dimension. Neither nominal width agreement nor a unique reference marker establishes the corresponding plan edge, roof depth, complete extent, material state or vertical datum.

The additional plan PDFs also yield 2,040 unclassified enclosed linework shapes across the replay. Hatch cells and incidental drafting shapes may be included. This count is not a count of reconstructed park objects, and none enters geometry feeds.

## Detection and source checks

`local-contrast-boundaries-v1` is a separate channel. The original raw-gray screen and periodic-threshold review remain unchanged. Each bounded artwork crop uses a nine-pixel local maximum, then contrast gains two and three independently. Periodic stroke hypotheses are detected and suppressed under both variants. Endpoints, first/last strokes and perpendicular long edges remain protected.

Both variants must pass the four-threshold region screen, agree by at least 98% IoU, preserve corresponding opening geometry, and have at least 98% outline support in the unmodified source. Shadow/dark-fill checks use only the actual hatch-edit masks: contrast normalization cannot hide original flat dark areas by counting every normalized pixel as removed hatching. Recipes retain source, normalized-pixel and edit-mask hashes. All shapes remain unverified and unplaced.

Native caption assignment uses one artwork window whose displayed extent aligns with the caption in a bounded band. Its adjacent scale must have the same native direction, align at the left edge and be the unique supported scale caption. This is a layout candidate, not verified view extent. Glyph screens apply to the caption and scale. Metre widths, heights and areas are explicitly nominal; depth and height datum remain unverified.

Drawing numbers retain native header candidates, including coherent repeated CAD overprints. Some bold header font resources produce no supported glyph pixels in the current font replay. Those failures remain in the view-page receipt. When the pinned document catalogue supplies a consistent drawing-number claim, it can establish an **unverified reference namespace** without clearing the failed header screen. Conflicting catalogue/native claims are withheld. This does not certify drawing identity, revision or visibility.

The plan-marker adapter retains the original four-Bezier circle, black corner-fill rectangle, outside view-index glyph, sheet-number glyph and paint identities. It only supports this narrow marker pattern. Native coordinate closure and rectangle containment use bounded 0.3-point drafting tolerance; marker semantics and clipping remain unverified. Captions are linked by project, drawing and view index, with all duplicate matches retained. No component position or bearing is inferred from marker proximity.

## Replay

Install the project's `planning` extra and provide the six original PDFs under their SHA256 filenames:

```sh
python scripts/replay_wicker_annotations.py \
  --pdf-directory /path/to/pdfs --include-shop-plans --catalogue-only
python -m voxel_mapper.drawing_faces \
  --documents /path/to/pdfs/wicker-shop-face-documents.json \
  --output /path/to/fresh-shop-face-review
```

The face CLI and existing `drawing_faces` park setting run the contrast and view-reference channels automatically. New outputs are `drawing-view-pages.jsonl` and `view-links.jsonl`; existing associations carry `raster_contrast_boundary_review`, `drawing_view_candidate` and optional nominal measurements. The completed-run contract pins both adapter versions and checksums all five output streams. Records remain excluded from feature feeds.

`evidence/wicker-shop-face-readiness.json` retains the summary and placement holds. `evidence/wicker-shop-face-replay.json` retains the exact output bytes as a SHA256-checked gzip/base64 envelope, including the unclassified linework stream and full report. Each `files` entry decodes with `gzip.decompress(base64.b64decode(entry['gzip_base64']))`; its byte length and SHA256 must match before use. The input catalogue is retained in the same envelope. This preserves the replay without storing repeated large plain-text streams in the branch.

All 67 focused tests pass. They cover faint outlines, original-source preservation, shadow checks after normalization, incompatible material anchors, malformed edit masks, nominal metric conversion, ambiguous view/scale assignments, coherent and conflicting header copies, native marker primitives, duplicate target captions and visibility holds. All real output hashes, candidate polygon validity and zero placement counts were independently checked.

## Remaining first-test gates

1. Resolve actual outer component edges and the held gable view, without treating interior hatch caps or projected silhouettes as complete faces.
2. Select the shop's ground/roof-plan edges, associate them with each elevation, and assemble consistent walls, openings and roof planes with depth and dimensions.
3. Establish independent absolute registration controls/checkpoints, source state and a verified vertical datum.
4. Compile the accepted component geometry and export a small placed world preview for inspection.

The exporter is already exercised with synthetic native world tests. The current stage advances real source interpretation and explicit sheet linkage; it does not create a real park download or resolve absolute placement.
