# OSM provisional plan alignment

Area cycles can now use a pinned OSM snapshot to propose an initial geographic
placement, separately from survey qualification and component reconstruction.
This first adapter matches complete polygon outlines: mapped buildings, water,
plazas, parking and closed path areas. Open bridge/path ways and junction matching
remain further work. Point labels do not become polygon controls.

```json
{
  "osm_provisional_alignment": {
    "enabled": true,
    "snapshot": "inputs/park-osm.xml",
    "sha256": "<exact original OSM snapshot SHA256>",
    "target_crs": "+proj=aeqd +lat_0=52.9915 +lon_0=-1.8875 +datum=WGS84 +units=m +no_defs",
    "max_pages": 1000,
    "max_seed_fits": 512
  }
}
```

The stage runs after retained native geometry extraction. It accepts OSM API XML
or complete Overpass JSON, preserving OSM element identities and multipolygon
handling through the existing parser. Snapshots are limited to 32 MB and 100,000
elements; reference polygons to 5,000. It does not download or silently refresh
configured snapshots. In this trial, the official OSM API supplied a retained
snapshot after an Overpass request was rejected.

The target frame must be projected in metres. A preferred, non-ballpark
transformation with declared operation accuracy at most one metre is required.
An unavailable OSTN grid blocks EPSG:27700 conversion rather than permitting a
fallback. A local WGS84 azimuthal-equidistant frame can support a park preview
without declaring UK survey/datum registration. Transformation accuracy is a
property of the projection operation, not an OSM positional accuracy certificate.

Original source PDFs, geometry feeds and OSM snapshots retain checksum pins.
Exact enclosed linework recovery supplies additional outline candidates while
retaining its budget/rejection report. Unique outlines seed bounded matching.
Verified visible scale is required. Area feasibility rejects impossible pairs,
and the seed/refinement transforms fit rotation and translation at the fixed
printed scale: no anisotropic stretching or scale drift is allowed. Other
features verify each candidate transform. Distinct alternative locations and
exhausted seed searches remain unresolved.

The existing held-out map check requires at least five distinct, non-overlapping
polygon correspondences. Every held-out outline is excluded from its centroid
fit, then checked for boundary disagreement, IoU, hole topology and scale. Passing
means consistency with the same OSM dataset; it establishes no independent
absolute accuracy. It cannot qualify a survey frame or serve as training truth.

Only one unambiguous proposal passing those map checks supplies a provisional
GeoJSON overlay. Complete transformed geometries must lie within the supported
outline envelope. Overlay records remain unclassified and physically unverified,
with an unknown absolute error bound. Their held-out disagreement is a map-fit
metric. No heights, materials, drawing state or geographic survey accuracy are
inferred, and the stage emits no Minecraft blocks or accepted recipes.

SQLite evidence memory stores the source snapshot and page proposals as separate
fact kinds. PDF/geometry/OSM/projection/algorithm changes select new facts;
unchanged pages reuse their proposals in another output directory. These facts
are not collected as independently surveyed landmarks by contextual reconstruction.
They preserve candidate frames for later refinement and review.

```bash
python -m voxel_mapper.osm_provisional_alignment \
  --corpus /absolute/path/corpus --geometry /absolute/path/drawing-geometry \
  --osm /absolute/path/park-osm.xml --store /absolute/path/evidence.sqlite \
  --output /absolute/path/alignment --target-crs '<projected metre CRS>'
```

OSM-derived previews must retain OpenStreetMap contributor attribution and the
source licence information. The reproducible source pack includes that notice.
Tests cover fixed scale, five held-out features, XML way identities, partial
snapshot refusal, ambiguity, snapshot/feed changes and cross-output replay.

## Recovered-plan trial

The official OSM API snapshot yielded 843 reference polygons in the selected
park bounds. Whole-page recovery exceeded its intersection budget, so the
adapter retries recovery within the original extraction windows. Each window
uses complete retained primitives, never clipped segments or closed boundary
gaps. Regional recovery retains its per-window outcomes and does not certify
full source coverage.

Each recovered sheet supplied 120 enclosed-face records before overlap
 deduplication. The two scale-verified sheets supplied 426 and 442 unique polygon
candidates; neither produced a shared map correspondence. The third supplied
436 outlines but remains withheld by scale-font visibility. All three results
reuse unchanged in a fresh output directory. No geographic frame, physical
component, overlay record or park block was accepted. The next matching work
should bind landmark labels to outlines and add open-path/bridge topology.
The receipt is `docs/evidence/mutiny-osm-provisional-alignment-validation.json`.

## Automatic acquisition, labels and network diagnostics

An online area cycle now runs from park bounds without a prepared snapshot,
manual seed IDs, label bindings or a hand-written target CRS:

```json
{
  "offline": false,
  "osm_provisional_alignment": {
    "bounds_wgs84": [-1.91, 52.975, -1.865, 53.008]
  }
}
```

Providing bounds or a pinned snapshot enables the stage automatically; an
explicit `enabled: false` disables it. Bounds-only mode requests the fixed
official OSM API once, within a 32 MB/30-second response budget, validates the
complete snapshot, records its observed hash and reuses it on later cycles.
No redirect, arbitrary attachment host or silent snapshot refresh is followed.
The default preview frame is local WGS84 AEQD at the bounds centre. Offline mode
reuses available data or records `awaiting_osm_snapshot`, without network calls.
A configured snapshot retains its explicit hash and target-frame checks.

The context stage matches exact normalized OSM names to native text runs.
Visible labels bind to one containing outline or one explicit endpoint-leader
hint. Coincident glyph/style traces are grouped; distinct repeated labels,
multiple matching outlines and repeated map names remain ambiguous. Named OSM
nodes can supply a hint to a uniquely containing map polygon; this does not
certify that polygon's physical identity. Named pairs and up to 16 priority
outlines enter the bounded search automatically, while geometric feasibility
and fixed-scale fitting remain mandatory. No fuzzy name guessing or nearest
outline selection occurs.

Grey or unsupported-font labels have a bounded raster-name fallback. OCR must
agree exactly with the existing native string at at least 85 minimum word
confidence. The original glyph bounds remain the only source coordinates; OCR
never replaces them or creates survey controls. At most eight crops per page
and sixteen across a run are attempted, with a five-second engine timeout and
one-million-pixel crop ceiling. Unavailable OCR, uncertain recognition, hidden
styles and exhausted budgets remain withheld. Engine/render versions and the
page's deterministic OCR allocation enter the evidence contract. Cached replay
uses the same allocation without repeating recognition.

Once a pose exists, an additional network diagnostic compares unique nearby
junctions with equal degree. Native networks use exact shared vertices: crossing
lines and gaps never create a junction. Map networks preserve OSM node IDs, so
coincident distinct bridge and ground nodes do not connect; explicit shared
nodes do. Missing node IDs use separate coordinate/layer groups. CAD networks
may contain walls, fences or contours, so this diagnostic does not certify
path identity, select an ambiguous pose or qualify a survey frame.

The three-plan automatic-context audit is recorded in
`docs/evidence/mutiny-osm-automatic-context-validation.json`. The complete
bounds-only area test acquires once and replays without any manual landmark
inputs. These stages run automatically, but incomplete evidence still leaves
placement or component generation pending.

Printed-scale seed coverage now screens every retained polygon against all reference polygons for area, hole topology and shape feasibility. The bounded scheduler tries one feasible alternative per outline before ordinary second alternatives, with exact named hints retaining priority. It no longer drops outlines after the first 64 or reference alternatives after the first eight. Only the configured number of fits is retained in the schedule; no unbounded pair list is materialized. The `seed_search` receipt records eligible, scheduled and deferred pairs, attempted outlines and untried outlines. Any deferred feasible pair raises `seed_fit_budget_exhausted`, which prevents a map-consistent overlay even if a hypothesis passes held-out checks. These filters and checks still describe provisional map agreement, not physical identity or independent survey accuracy.

The unscaled mapped-placement workflow retains its existing discovery shortlist; the full eligibility scheduler requires the original visible printed scale. See `docs/evidence/mutiny-osm-seed-coverage-validation.json` for the retained-plan audit.

At the default 512-fit budget, the retained Mutiny audit now tries all 133 and 134 eligible outlines on the two usable-scale revisions and finds one five-outline hypothesis on each. Both remain withheld: held-out boundary errors range from 0.877 to 8.662 m, four of five checks fail, and 1,583 / 1,584 feasible seed pairs remain deferred. Network diagnostics also retain their vertex-budget rejection. The third revision remains withheld by scale visibility. A fresh output reuses all three page facts with identical feed hashes; no overlays, surveyed frames or world blocks are accepted.

The OSM area stage now continues the deterministic seed schedule automatically through up to eight batches by default. `max_seed_fits` bounds each batch (default 512); `max_seed_batches` bounds automatic continuation (1–8, default 8 for OSM). A pair is fitted once per matching pass on a fixed outline inventory. The scheduler retains at most the combined fit budget (hard maximum 16,000 pairs), stops when all feasible pairs have been tried or the combined budget is consumed, and records each batch's actual fit count. Remaining feasible pairs continue to block validation. Generic mapped placement keeps its one-batch default. Completed page facts include both budget settings; changing either produces a new fact. Interrupted incomplete pages are recomputed, while completed pages replay from persistent memory.

Held-out checks now retain centre error, boundary error after diagnostic centroid alignment, diagnostic overlap and the source-to-map area ratio, together with each failed threshold. Diagnostic centroid alignment never replaces the held-out transform or changes acceptance. It helps distinguish displaced centres from incompatible outline shape while retaining the same one-metre boundary and 0.85 overlap thresholds. See `docs/evidence/mutiny-osm-batch-search-validation.json` for the full-search audit.

The retained-plan audit completes all 2,095 / 2,096 eligible pairs in five automatic batches (four batches of 512, then 47 / 48), with zero repeated or deferred pairs and no untried eligible outlines. Both revisions retain one five-outline hypothesis but fail four held-out checks. Two outlines retain 4.293 / 4.593 m boundary disagreement after diagnostic centroid alignment, indicating that a translation correction alone cannot satisfy the checks. The third page is still scale-withheld. All three page facts replay identically in a fresh output; zero overlays, surveyed frames or world blocks are accepted.

Failed held-out outlines now receive a bounded automatic investigation. The exact held-out transform is retained in each check. Under that unchanged transform, the investigator searches nearby retained source polygons and nearby map polygons for compatible alternatives using the existing boundary, overlap, scale and hole-topology thresholds. Each review inspects at most 128 neighbours on either side; at most 64 failed checks are reviewed per page, with withheld neighbour budgets and deferred checks reported explicitly. Up to three compatible alternatives are retained per side, with total counts and ambiguity preserved. An alternative already used in the held-out fit is marked, so it cannot be mistaken for an independent checkpoint. No geometry is snapped, stretched, substituted or promoted by this stage.

The investigation receipt retains native paint ordinals, parent extraction contracts, regional boundary margins, curve approximation and derived-line parents where available. A complete closed native primitive is distinct from a complete verified physical object. OSM element edit timestamp/version metadata is retained from the pinned snapshot, but neither an edit timestamp nor the PDF's existence proves a physical observation date. Drawing/map date differences remain unresolved. See `docs/evidence/mutiny-osm-outline-investigation-validation.json` for the retained-plan audit.

The retained audit reviews all four failed checks on each usable-scale revision without exhausting its review budgets. Every failed source outline is a complete retained native closed polygon, and the nearby searches (1–7 source outlines and 1–3 map outlines per review) find no compatible replacement under the unchanged held-out transform. This narrows the investigation but does not prove complete physical correspondence or complete original-source extraction. All three page facts replay identically; no geometry replacements, overlays, surveyed frames or world blocks are accepted.


An automatic original-source recovery pass now follows failed held-out outline checks. It derives up to eight deterministic native-PDF windows from the failed source outline and inverse-projected map extent, padded by 20 m at the checked fit scale (at most 100 PDF points). The map selects where to inspect; its boundary is never used as recovered source geometry. The original PDF is read once for paint paths, complete primitives are extracted with a 0.25-point minimum line length, and enclosed straight-line faces are recovered under the existing provenance and network limits. Partial extraction windows are withheld. Across all windows, the recovery is capped at 10,000 unique candidates and one million points; overflow withholds the complete targeted result.

Original coordinates, paint ordinals, extraction/recovery contracts and window bounds are retained in persistent page facts. Original closed polygons remain whole; no line snapping or gap repair occurs. If unique new polygons are discovered, the area runner automatically rematches the expanded inventory and reruns held-out checks once, retaining its initial checks and seed-search receipt. Matching budgets apply separately to the initial and expanded passes; no recursive recovery is attempted. New source geometry remains unclassified investigation evidence and cannot become surveyed controls or physical components merely because it matches OSM. See `docs/evidence/mutiny-osm-targeted-recovery-validation.json` for the real-plan audit.

The real audit completes four target windows per usable-scale revision, all within extraction and recovery limits. Each revision retains 6,108 unique targeted records (6,073 lines and 35 polygons, including earlier geometry) and adds five unique enclosed polygons to its matching inventory. The expanded passes complete all 2,132 / 2,133 eligible pairs with zero deferred pairs or untried eligible outlines. Both still fail four held-out checks; no placements are promoted. The third revision remains scale-withheld. All three page facts replay identically in a fresh output, including the retained targeted geometry; zero overlays, surveyed frames or world blocks are accepted.

Source network checks now use a bounded temporary SQLite graph when the in-memory 30,000-vertex budget is exceeded. The fallback scans at most one million vertices and retains at most 500,000 exact nodes, one million distinct original edges and 2,000 junctions. It preserves explicit OSM node identities, coordinate/layer keys and duplicate-edge suppression; conflicting node coordinates remain rejected. Degree is computed from the complete eligible input graph, without clipping windows, snapping gaps or adding crossing intersections. SQLite cache and temporary grouping stay bounded. Exhausted scan, node, edge or junction budgets withhold the diagnostic; no partial graph is returned. The graph is a diagnostic of unclassified retained linework, not confirmation of path identity.

Placement search now keeps distinct candidate/reference correspondence sets even when they imply nearby poses. Equivalent sets may deduplicate, but different sets receive separate held-out checks. At most twelve hypotheses are retained; any overflow sets `hypothesis_budget_exhausted`, which blocks validation. The OSM stage selects a hypothesis only when exactly one correspondence set passes and neither seed nor hypothesis search is incomplete. Several passing sets remain ambiguous. The selected index is explicit and is used for preview export and its uncertainty receipt. Supplied proposal transforms also receive direct full-boundary checks without refitting, so good correspondences cannot approve a different exported pose. Network agreement does not bypass any boundary or independent-source requirement. See `docs/evidence/mutiny-osm-network-correspondence-validation.json` for the real audit.

The real audit clears the former network memory rejection on both usable-scale revisions. Disk graphs scan 38,497 / 38,506 vertices, retain 37,989 / 37,998 exact nodes and 34,389 / 34,397 unique edges, and produce 37 source junctions each. The OSM path graph supplies 268 junctions; each plan retains two unique degree-compatible junction hints at 1.427 and 1.815 m. These hints do not identify paths or approve alignment. Both pages still retain one withheld correspondence hypothesis and fail held-out and supplied-proposal boundary checks. The third remains scale-withheld. All three page facts replay with identical output hashes; no overlays, surveyed frames or world blocks are accepted.

A separate automatic semantic-context stage now retains relevant OSM feature tags and reviews failed source/reference pairs. It checks only exact standalone source role annotations, such as `Roof outline`, `Building footprint` or `Water edge`, with original-font visibility and unique complete-label containment. Sheet titles, names, polygon shape and paint colour cannot provide a source type. Nested containment, hidden text, absent source geometry, conflicting role clues and exhausted screen/review budgets remain explicit. The role clues are unverified annotation context; even equal feature families do not certify the same physical boundary convention. Relevant map tags also do not establish ground-versus-roof outline accuracy or physical object identity.

Semantic observations are separate child facts of the exact completed alignment page. They retain native page hashes, renderer/glyph versions and the map-semantic inventory digest, and can replay without repeating matching or targeted recovery. Adding this diagnostic does not invalidate unchanged geometric alignment facts. The stage reviews at most 64 failed pairs and screens at most 16 role annotations per page; contained named clues retain their original visibility/association status and are never treated as boundary types. Neither conflicts nor compatible-family hints filter matches, qualify components, certify registration or supply training labels. See `docs/evidence/mutiny-osm-semantic-context-validation.json` for the retained audit.

The retained audit reuses all three completed alignment facts and reviews the eight failed pairs across the two usable-scale revisions. Each has three map-tagged building references and one water reference, but all source boundary roles remain unresolved. The contained Congo River Rapids annotation retains its original withheld-visibility status and is not treated as a building, roof or ride-boundary classification. The third revision has no held-out pairs because its scale remains withheld. A fresh output reuses all three semantic child facts with identical semantic and alignment hashes; no placements, physical components or world blocks are approved.
