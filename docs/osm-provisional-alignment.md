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
