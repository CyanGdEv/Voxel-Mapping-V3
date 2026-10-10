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

## Clip-aware plan walls and discontinuities

The next source inspection identified a concrete extraction gap: the shop's gray wall strips are painted with large rectangular fills inside **nonrectangular, sometimes multipart clipping paths**. The existing footprint extractor rejects those clipping scopes. The raw fill rectangles are not the wall geometry; treating their bounding boxes as walls would cover the shop interior and its real openings.

`straight-clipped-plan-fills-v1` is now a separate channel in the v3 edge CLI. It intersects exact straight fill polygons with the current nested clip stack and page frame. Native even-odd and nonzero winding rules preserve holes and disjoint pieces. Clip scope ends follow source levels. Curved/invalid clips, optional layers, nonopaque fills and compositing groups remain withheld. Path, point, depth, overlay, candidate and result-vertex budgets bound recovery. Existing accepted-footprint/registration gates are unchanged; these records never enter placement feeds.

The retained replay recovers 98 ground-floor fill candidates, including 62 clipped fills, and 31 roof-plan fill candidates, including 13 clipped fills. These include white masks, symbols and unrelated plan components; they are not 129 walls. A source overlay was visually reviewed: the recovered gray polygons align with the shop's actual wall strips and preserve the visible openings. Later overpainting, physical component identity and material/as-built state remain unverified.

Multipart thin fills also produce bounded **discontinuity candidates** when their parts share an axis and transverse band. Widths use projected source extents and the nominal plan scale. No gap is bridged, and no candidate is classified automatically as a door or window. The ground-floor plan yields six such candidates; one visually associated with the shop's large opening has a nominal width of 4.5410 m. Other candidates belong to other components. Small, offset, nonparallel, background-white and otherwise unsupported pieces are withheld by the recipe. Absence of a candidate does not prove a continuous wall.

`evidence/wicker-shop-clipped-fill-replay.json` retains all recovered fill/clip geometries and source rings, gap recipes, all fourteen plan/elevation region-reference pairs, matched connected runs and their source edges. The focused receipt includes the full CLI replay's SHA256 and byte length; unmatched network records remain reproducible from the pinned PDFs. Twenty-seven focused tests passed, including nested clip intersection/restoration, even-odd holes, disjoint parts, unsupported curves, rotation-independent geometry and gap measurements, background masks and nonparallel parts. The full real replay's fill intersections were independently reconstructed from retained source rings and checked against the candidate polygons.

This fixes missing native plan-wall geometry. It does not establish a complete automatic shop shell or wall heights. The shop's floor/elevation dimensions and GIA discrepancy remain unresolved, as do roof topology, source state, absolute registration and vertical datum. Meshes remain withheld and world additions remain zero. Next: associate recovered wall strips and actual openings with corresponding elevation edges, resolve the dimensional disagreement, then build a consistent local wall/roof model.

## Located wall-gap review

The v4 edge diagnostic retains a source-coordinate corridor and projected endpoint pair for each multipart fill discontinuity. Rotation preserves the measured gap; the endpoints remain geometric projections, not accepted physical attachment points. A spatially indexed, bounded overlap audit records every retained fill intersecting the corridor, including white masks and earlier paints. Boundary-only contact does not count as covered area. The audit does not certify complete visibility: excluded symbols, strokes, images and unsupported paint scopes may still affect the drawing.

The original two plan PDFs reproduce all 129 retained fill records exactly after JSON normalization. Six ground-floor gap candidates are located; one intersects another retained fill and requires visibility review. The 4.5410 m candidate has no retained-fill overlap. None is automatically classified as an opening or submitted as a registration point.

Reproduce from checksum-named original PDFs:

```sh
PYTHONPATH=. python scripts/audit_wicker_fill_gaps.py \
  --pdf-directory /path/to/pdfs \
  --output evidence/wicker-shop-located-fill-gaps.json
```

The script verifies the compressed retained replay and original PDF hashes, reruns native fill extraction and refuses changed extraction before deriving gap coordinates. The receipt is `evidence/wicker-shop-located-fill-gaps.json`. Next, compare these source positions with elevation opening boundaries and resolve the floor/elevation scaling discrepancy. This pass generates zero world blocks.

## Layout-normalized opening correspondence

The first-test diagnostic now reuses the earlier source-layout finding rather than treating the literal floor-sheet scale as unresolved. `scripts/review_wicker_opening_correspondence.py` verifies the original floor/roof/elevation PDFs, reproduces the pinned manual floor trace, recomputes the shared-furniture transform and its four holdouts, replays exact fill extraction, and compares source-coordinate endpoint pairs. The layout reproduction check permits only 1e-9 absolute floating arithmetic variation; source bytes, label strings, roles and review structure remain checked. Building extents never become layout controls.

A fixed 0.25 m **nominal discovery window** retains all qualifying trace pairs, with reversed endpoint order supported and ambiguity explicit. Matching widths at another position does not qualify. Source coordinates are converted to native PDF axes before the directional inverse layout transform is applied. The correction changes derived dimensions without altering native source endpoints or recovering missing walls.

The six gap candidates yield one spatial trace hypothesis: the southwest shop opening. Its raw nominal width is 4.5410 m; layout-normalized width is 4.9927 m. The maximum endpoint discrepancy is 0.1509 m, larger than the manual trace's 0.1260 m per-endpoint sampling bound. It remains flagged and does not establish physical correspondence. The reviewed southwest elevation head height (2.4939 m above drawn floor) is retained **conditionally** on the existing manual plan/view association, without making a new wall panel or accepting an automatically measured elevation opening. The northeast opening and northwest door remain unmatched; five unrelated source gaps remain unassigned.

The normalized floor extents differ from the elevation review by -0.0859 m and +0.0206 m, consistent with the earlier layout study. This resolves the nominal dimension discrepancy for the provisional manual model; it does not prove uniform scaling of every view, current/as-built identity, roof topology, elevation opening widths or geographic registration.

```sh
python scripts/review_wicker_opening_correspondence.py \
  --pdf-directory /path/to/checksum-named-pdfs \
  --output evidence/wicker-shop-opening-correspondence.json
```

The real replay and repeated receipt are byte-identical. Five new tests cover spatial rather than width-only matching, native coordinate conversion, directional scaling, reversed endpoints, sampling-bound flags, ambiguous traces and invalid input rejection. Next: recover the northeast and side-door boundary pairs across separate fill paints, resolve the southwest transverse endpoint discrepancy, and measure elevation opening extents before automatic shell assembly. World additions remain zero.

## Exact facing-endcap recovery

The endcap pass recovers candidates beside the two missing shop openings. The cause was complex multipart wall polygons, not absent source geometry: the northeast wall and northwest door contain short exposed end edges, but their enclosing polygons fail the earlier simple-strip screen.

`exact-fill-endcap-pairs-v1` retains short exterior edges (nominally 0.08–1 m), checks an inward source-polygon containment probe extending one cap width, and considers facing edges on distinct polygon parts with the same fill colour. Different paints may also be paired. Caps must oppose within 0.5 degrees, differ in transverse centre/width by at most one PDF point, and leave a nominal gap of 0.08–8 m. Each source edge, polygon part, parent fill identity, exact endpoints and support probe are retained. A 1e-7-point inset applies only to the containment probe to avoid boundary roundoff; source edges and corridor corners remain unchanged. Source-fill overlap exceeding 1e-9 of corridor area rejects a pair; other retained fills remain visibility-review flags. No source polygon is bridged or changed.

The search inspects 115 supported endcaps and yields 24 unclassified facing pairs. Comparing their positions with the reproduced manual shop traces retains one candidate at each of the three reviewed openings. Other drafting candidates remain unassigned. These positions establish review correspondence hypotheses, not physical openings.

| Reviewed opening | Layout-normalized cap-centre span | Best source-corner endpoint discrepancy | Manual normalized span |
| --- | ---: | ---: | ---: |
| Northeast | 4.9993 m | 0.0156 m | 4.9863 m |
| Southwest | 4.9960 m | 0.0302 m | 5.0210 m |
| Northwest door | 1.0110 m | 0.1345 m | 0.9008 m |

All eight combinations of the two corners on each cap and both endpoint orders are retained. The lowest discrepancies are summaries for review; no physical wall face is selected. The northeast and southwest corner options fall within the manual per-endpoint sampling bound (0.1260 m), explaining much of the earlier cap-centre discrepancy. The northwest door remains outside it and its span differs by about 0.1102 m. Neither discrepancy is repaired by changing endpoints. The associated manually traced elevation head heights remain explicitly conditional; this pass does not measure independent elevation opening widths.

Enable the additional channel without changing the original multipart-strip receipt:

```sh
python scripts/review_wicker_opening_correspondence.py --endcaps \
  --pdf-directory /path/to/checksum-named-pdfs \
  --output evidence/wicker-shop-endcap-correspondence.json
```

Replays reproduce original PDFs/fills, manual floor traces, and layout anchors before comparison. The final new receipt repeats byte-identically; the older default opening receipt remains byte-identical. Budgets cap input fills, inspected vertices, caps, comparison/overlap operations and results. Reordered fill inputs produce identical outputs. Six focused tests cover separate paints, complex multipart returns, rotations, masks/offsets/material differences, budgets/duplicate identities, and retention of all corner alternatives.

Next: review the northwest door's actual reveal/outer-face endpoints and recover elevation opening extents from source geometry. Accepted wall-face identity, complete shell topology, as-built state and geographic placement remain unresolved. Zero world geometry is added.
