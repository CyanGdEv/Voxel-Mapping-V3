# Modular park reconstruction

The new `voxel_mapper.reconstruction` package separates source adapters,
evidence, geometry generators, bounded composition and Bedrock export. Its
algorithms have no park names or ride IDs. The existing automatic acquisition
flow retains its OSM, official planning, Overture, terrain/DSM, classified
building LiDAR and bathymetry providers and now emits a source coverage inventory.
No new provider availability is assumed from a module name.

## Components

| Module | Responsibility |
| --- | --- |
| `model.py` | Sources, geometry references, parameter measurements and explicit estimates |
| `sources.py` | Extensible OSM, GeoJSON and validated planning-record adapters; horizontal CRS transformation; feed hashes |
| `geometry.py` | Shared connected 3D members, connected line rasterization and polygon rasterization |
| `generators.py` | Registered paving, wall, building shell, 3D track/cable/beam and trestle algorithms |
| `engine.py` | Atomic feature staging, occupancy conflicts, material validation, budgets and provenance |
| `inventory.py` | Candidate counts, available provider outcomes and missing evidence per component |
| `cli.py` | Retained-terrain geometry plans or verified overlays on an existing Bedrock world |

Wicker's existing completion generator now imports its geometry primitives from
this package. Its station associations, corrected profile, rider envelope and
special tunnel handling remain separate park-specific code. They are not yet
replaced by a general coaster reconstruction algorithm.

## Inputs

A manifest declares a projected metre CRS, a common vertical datum, a local
park boundary, a source catalogue and either feeds or normalized features.
GeoJSON Z coordinates mean absolute elevation in the declared datum. Output
axes are X east, Y up, Z north, matching the existing world exporter.

Every source has `id`, `kind`, `url`, `license` and `crs`. For 3D geometry it also
needs `vertical_datum`. Planning/CAD/survey geometry needs
`registration_status: accepted`; this is a supplied verification result, not an
automatic registration claim. Optional metadata can retain document identity,
application reference, observation date and verification notes.

Each feature contains `id`, `family`, `geometry`, `geometry_source` and
`parameters`. Each parameter is an object with `value`, `source` and `status`
(`documented`, `measured` or `estimated`). Estimates require explicit opt-in.
Feed records must refer to registered sources. Duplicate feature identities
fail instead of silently losing evidence. For matched cross-source objects,
canonical identities and dimensions should be resolved before planning; the
new engine does not automatically conflate neighbouring ride routes.

Example normalized feature (illustrative coordinates, not surveyed park data):

```json
{
  "id": "ride-a/track",
  "family": "track",
  "geometry": {"type": "LineString", "coordinates": [[0, 0, 110], [5, 0, 113], [5, 5, 110]]},
  "geometry_source": "registered-survey",
  "parameters": {
    "material": {"value": "oak_planks", "source": "registered-survey", "status": "documented"}
  }
}
```

Feeds use `{ "adapter": "osm|geojson|planning_records", "source": "source-id",
"file": "relative-or-absolute-path", "sha256": "optional-expected-digest" }`.
GeoJSON properties can declare `reconstruction_family` and
`reconstruction_parameters`; legacy tagged surface/height/width values are
adapted when present. Planning records reuse the existing document, registration,
reuse, as-built, boundary and datum gates. Their rejected decisions are retained.
Raw PDF strokes and application boundaries are not interpreted as structures.

## Generation and export

```bash
python -m voxel_mapper.reconstruction.cli \
  --manifest park-manifest.json \
  --terrain-config existing-output/resolved-config.json \
  --output new-geometry-plan

python -m voxel_mapper.reconstruction.cli \
  --manifest park-manifest.json \
  --terrain-config existing-output/resolved-config.json \
  --base-world verified-world-directory \
  --output new-composed-world
```

The installed command is `voxel-reconstruct`. Add `--allow-estimates` only when
explicitly annotated provisional parameters are desired. Output directories
must be new. The manifest CRS must match a base world's CRS exactly, and terrain
and 3D source vertical datums must agree. Floor palettes paint whole polygon
rasters, including holes, rather than a few labelled cells.

Unsupported or conflicting features are withheld atomically, with reasons.
Invalid geometry or an oversized feature does not discard valid neighbouring
features. The total budget stops an oversized run. Default limits are 100,000
cells per feature and 2,000,000 total cells. Existing non-air world blocks are
protected except matching material and natural ground at an explicit paving
cell. No geometry plugin carves air implicitly. The world path uses the existing
full touched-section/chunk-coverage export verification.

Add a generator with `engine.register(family, generator)`; it receives feature,
Shapely geometry and context and yields `(x,y,z), material`. Add an adapter with
`adapters.register(name, adapter)`; it returns normalized features and optionally
source decisions. Export, evidence and collision rules remain shared.

## Validation and current limits

The batch regression reconstructs 300 synthetic 3D ride paths with one generator,
checks vertical/inversion members, material provenance, native block identifiers,
atomic collision/budget failures, full brick polygon coverage and deck-bearing
contact. It demonstrates dispatch and geometry scaling, not 300 accurate rides.
All 331 repository tests pass.

A retained Alton OSM/DTM test reads 1,166 physical feature candidates. Thirteen
features with sufficient data produce 13,477 planned cells. The 1,153 withheld
features remain reported: 645 lack line widths, 329 lack heights, 95 transport/
ride routes lack 3D profiles, 12 lack materials, 71 need unsupported semantic
generators and one exceeds the footprint budget. These are plan results; they
are not changes to the V9 world. Summary: `evidence/modular-reconstruction-validation.json`.

The current 3D sweep is a connected one-cell centreline/member. It can preserve
an explicitly supplied inversion/vertical route, but does not infer inversions,
banking, a swept train envelope or engineered coaster cross-sections. General
CAD/BIM and photogrammetric mesh adapters, ride point-cloud classification,
automatic drawing registration, cross-source object conflation and migration
of existing ride-specific profile/clearance algorithms remain future work.
Provider coverage and licence constraints still apply per park. Additional
planning drawings improve geometry only after registration and semantic binding;
more downloaded files alone do not establish accurate dimensions.
