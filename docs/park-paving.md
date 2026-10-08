# Park-wide planning paths, plazas and material palettes

This paving pass copies the clean park world and updates ground surfaces. It
recovers missing paving polygons from retained park planning drawings, patterns
mapped pedestrian surfaces, and transfers explicit planning materials to closely
matching OSM paving. It emits no replacement ride layouts.

## Geometry recovery

Only catalogue entries identifying Alton Towers on Farley Lane are inspected.
PDF bytes must match their recovered document hashes. Native survey identifiers
and unique spot-level labels link sheets to the retained Wicker Man shop/track
alignment. Similarity fits allow uniform scale, translation and rotation;
reflection, shear and anisotropic stretching are rejected. Fits require a
spatially distributed consensus, withheld-label checks and agreement between
available parent sheets. The anchor chain and residuals remain in the audit.

This is **provisional registration**. Matching text origins checks consistency
between drawings; it does not establish independent survey accuracy or that
proposed/historical paving exists today. Verified planning-geometry gates remain
unchanged. PDF renderer coordinates are unrotated native page coordinates for
both text and strokes, including sheets displayed with page rotation.

Paving extraction nodes visible solid black/grey linework, including curves
flattened to a maximum 0.05 m chord tolerance at the fitted scale. It preserves
closed faces and holes without snapping gaps or inventing connectors. A native
floor/paving label must lie inside the face. Ambiguous constituent materials,
contained grass/water/building labels, hidden layers and unsupported clipping
are withheld. The world clips surfaces to the mapped park boundary and excludes
mapped buildings and water. Wicker Man's retained filled/pattern paving polygons
are also included; generic paving patterns do not establish their constituent
material.

## Material matching

The default proximity is **2 m**, configurable from 0 to 10 m. Coordinates are
park-local metres, not latitude/longitude. Only polygons with explicit floor
material labels may donate a material.

A whole OSM polygon inherits when its area is between 0.5 and 2 times the
planning polygon's area, at least 75% is covered by its buffered footprint,
and their Hausdorff distance is within the configured proximity. Otherwise
inheritance is restricted to nearby cells of the OSM surface. Long paths retain
their own surface away from the planning polygon. Equally close conflicting
materials stay unresolved. Every transfer records its drawing hash, donor
feature and distance; whole-footprint matches also record coverage and boundary
distance. An inherited material is an estimate rather than construction proof.

| Application or mapped surface | Palette | Interpretation |
| --- | --- | --- |
| Brick paving | Bricks, occasional red terracotta | Brick blocks provide built-in fine running-bond texture |
| Tarmac / asphalt | Black and occasional grey concrete | Asphalt appearance approximation |
| Concrete | Light grey concrete and occasional stone | Slab colour variation |
| Block paving | Stone bricks and occasional stone | Constituent unspecified; does not imply clay brick |
| Stone paving | Stone and stone bricks | Irregular stone approximation |
| Setts / cobblestone | Cobblestone and stone | Small stone units |
| Gravel | Gravel and occasional coarse dirt | Grain variation |
| Compacted ground | Coarse dirt and occasional gravel | Natural path surface |
| Timber decking | Oak and dark oak planks | Board variation |
| Sand | Sand | Single-block material |

The code chooses blocks deterministically from global voxel coordinates. Adjacent
polygons and chunks share a stable pattern origin. Existing vanilla block
textures supply fine detail; colour, constituent size, joints and laying direction
are approximations unless independently specified. Unspecified paving uses a
recorded generic stone palette. No custom resource pack is required.

## Run

Extract the planning paving first:

```bash
python -m voxel_mapper.park_paving_plans \
  --planning-cache /absolute/path/planning-prefetch-selected \
  --wicker-output /absolute/path/alton-full-park \
  --park-output /absolute/path/alton-full-park \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/park-paving-plans
```

Then apply it to a clean retained world:

```bash
python -m voxel_mapper.park_paving \
  --source-output /absolute/path/oblivion-one-block-track \
  --park-output /absolute/path/alton-full-park \
  --planning-output /absolute/path/park-paving-plans \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --proximity-m 2 \
  --output /absolute/path/park-paving-world
```

The source world and new output are separate. Ground elevations come from the
retained terrain and use the original world vertical offset. No clearance or
excavation is generated. Existing ride physical/clearance cells and retained
structure/roof/water cells are protected. Bridges, tunnels and nonzero-layer
OSM pedestrian features are excluded from ground repainting. Unsupported
planning alignments remain in the audit with no world geometry.

The copied-world exporter checks every cell of touched chunk sections after
Bedrock readback, including unchanged cells and air, plus total chunk coverage
and spawn metadata. Untouched chunks retain the baseline verification. Outputs
include `park.mcworld`, per-feature material/proximity decisions, provenance,
novel planning cell counts, the composed paving JSONL, and palette JSON/PNG.
