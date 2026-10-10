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

### Automatic edge correspondence replay

`python -m voxel_mapper.plan_elevation_edges --documents /path/to/wicker-shop-face-documents.json --faces /path/to/face-review --output /path/to/new-edge-review.json` now checks the catalogue/PDF and replay checksums, screens literal plan-scale claims, and compares full native straight plan segments with nominal elevation-region widths. It retains exact endpoints, path/item identities and paint sequence numbers. Layered, transparent, dashed and curved strokes are excluded. Conflicting plan scales are withheld even if one claim's glyph replay fails. All eligible length matches remain candidates; no nearest edge is selected.

The retained six-PDF replay examined two plan pages and fourteen region/reference pairs. Six pairs have length hypotheses; eight have no eligible full-segment match. There are 74 distinct source-edge candidates across those matches, including 69 incidental short-edge matches for a narrow wall region. This demonstrates why width agreement alone cannot identify a physical component.

The opposing long roof elevations each match four roof-plan segments within the fixed 0.25 m discovery window: 16.4997, 16.8410 (two separate strokes) and 16.8469 m. The last is the native edge previously recorded in the manual roof diagnostic; the new stage found it without loading manual annotations. The nominal elevation width is 16.6864 m, leaving a 0.1605 m residual for that edge. This does not establish its physical correspondence or an accuracy bound. Three wall-region/reference pairs also match a 15.8496 m roof-plan stroke; its physical wall role remains unknown.

No full-length ground-floor segment matches the broad shop elevation regions. Fragmented collinear segments are deliberately not joined by this stage. The next geometric task is to recover source-supported connected outer chains and closed component footprints, then check corner correspondence, baseline and roof topology across views. The replay cannot yet assemble an automatic mesh: all fourteen results retain `mesh: null` and an explicit incomplete-correspondence hold. Absolute registration and datum remain separate gates.

`evidence/wicker-shop-edge-replay.json` retains the complete edge receipt as a SHA256-checked gzip/base64 envelope. Twelve focused edge/view tests passed, covering ambiguous equal-length edges, fragmented lines, dashed/transparent exclusions, rotation-independent source provenance, scale visibility/conflicts and bounded/nonfinite input rejection. This stage is an explicit diagnostic CLI; it is not yet enabled in the park orchestration workflow.

### Connected source network

The v2 edge CLI additionally reconstructs an exact source network. Add `--component-label Shop` to screen that literal label and retain every enclosed drafting face containing its centre. It never assigns the smallest or nearest polygon as the building. The ground-floor replay has a visible shop label but **no recovered enclosed face containing it**. The automatic shop footprint remains unresolved.

`exact-plan-network-v2` nodes only actual intersections and overlaps, then retains degree-two chains, continuous straight runs and enclosed faces with source-edge provenance. Chains stop at branches. A separate straight run may pass through an exact junction when both incident segments have a unique reciprocal opposite collinear continuation; every encountered junction and degree is retained. This recovers continuous strokes crossed by hatching without choosing a turn or certifying boundary topology. No endpoints are snapped and no gaps are filled. A 1e-7 PDF-point epsilon is used only for provenance/collinearity checks, not network construction. Bounded intersection, node, junction, output and provenance checks withhold unsupported or oversized results.

The two plans contain 11,150 eligible source segments. Recovery retains 12,500 degree-two chains, 8,737 continuous straight runs and 2,591 unclassified enclosed faces. These are drafting structures, not reconstructed buildings or feature counts. Fourteen records exceeded vertex/provenance limits and remain withheld. The four long roof hypotheses survive as continuous runs; two contain more than 200 retained hatch junctions. Connected coverage adds roof-plan wall-span hypotheses at 15.8622 m with two or three source segments. Two additional ground-floor region/reference pairs now have length hypotheses (13.2630 and 11.8194 m); neither establishes the long shop wall or a closed footprint.

The focused correspondence receipt is retained in `evidence/wicker-shop-connected-edge-replay.json`, using the same verified gzip/base64 envelope format. It retains all region/reference pairs, matched straight runs and referenced source edges, label screens and network counts. The full CLI output's SHA256 and byte length are included; unmatched network geometry can be regenerated from the pinned PDFs with the CLI. All full-replay polygons/lines were checked for validity and source-reference integrity. All eighteen focused network, edge and view tests passed. Tests check exact fragment joins, a tiny unbridged gap, crossed strokes, closed-face containment, overlapping-source provenance and budget rejection. All mesh fields remain null and world additions remain zero. Next: distinguish wall footprints and door gaps from incidental linework, establish complete corresponding corners and component extents, then assemble walls and roof planes. This diagnostic remains outside production park orchestration.

1. Resolve actual outer component edges and the held gable view, without treating interior hatch caps or projected silhouettes as complete faces.
2. Select the shop's ground/roof-plan edges, associate them with each elevation, and assemble consistent walls, openings and roof planes with depth and dimensions.
3. Establish independent absolute registration controls/checkpoints, source state and a verified vertical datum.
4. Compile the accepted component geometry and export a small placed world preview for inspection.

The exporter is already exercised with synthetic native world tests. The current stage advances real source interpretation and explicit sheet linkage; it does not create a real park download or resolve absolute placement.
