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
