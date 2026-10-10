# Park-wide planning paths, plazas and material palettes

This paving pass copies the clean park world and updates ground surfaces. It
recovers missing paving polygons from retained park planning drawings, patterns
mapped pedestrian surfaces, and transfers explicit planning materials to closely
matching OSM paving. It emits no replacement ride layouts.

## Geometry recovery

Only catalogue entries identifying Alton Towers on Farley Lane are inspected.
PDF bytes must match their recovered document hashes. Up to eight pages per eligible
PDF are inspected, including drawings titled Landscape/Paving/Surfacing. Explicitly
superseded sheets are retained as source evidence but excluded from geometry. Each
page has separate controls, face cache and provenance; an aligned cover does not
automatically register other pages. Native survey identifiers
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

Material-label containment uses a spatial index and exact polygon predicates; it
preserves the smallest enclosing face and the existing edge-clearance threshold.
Reviewed source/page/face exclusions in `data/alton-paving-face-exclusions.json`
withhold scale bars, legend swatches, title blocks, building/roof ambiguities and
historical ride platforms. Reasons and source hashes are retained.

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
park-local metres, not latitude/longitude. Polygons with explicit floor material labels or a separately recorded user
material assignment may donate a material. Generic paving hatches never establish
brick composition. The user's Wicker Man correction assigns brick to complete new
paving and labelled plaza footprints, preserving this provenance separately.

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
| Brick paving | Terracotta 55%, mud bricks 20%, oak planks 20%, granite 5% | User sample IMG_6639; visual approximation |
| Tarmac / asphalt | Grey concrete | User sample IMG_6639 |
| Concrete | Light grey concrete and occasional stone | Slab colour variation |
| Block paving | Stone bricks 45%, stone 35%, cobblestone 20% | User stone sample; constituent unspecified |
| Stone paving | Stone bricks 45%, stone 35%, cobblestone 20% | User sample IMG_6639 |
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
structure/roof/water cells are protected. The three known legacy Wicker ground
paving features are repaintable despite their old `structure` classification;
ride and air cells remain protected. Bridges, tunnels and nonzero-layer
OSM pedestrian features are excluded from ground repainting. Unsupported
planning alignments remain in the audit with no world geometry.

The copied-world exporter checks every cell of touched chunk sections after
Bedrock readback, including unchanged cells and air, plus total chunk coverage
and spawn metadata. Untouched chunks retain the baseline verification. Outputs
include `park.mcworld`, per-feature material/proximity decisions, provenance,
novel planning cell counts, the composed paving JSONL, and palette JSON/PNG.

## Additional CBeebies corridors and coverage

`data/alton-paving-extensions.geojson` retains four reviewed corridor boundaries
from SMD/2013/1047, Proposed Site Plan 2813-102F (ImageName 51142). Native PDF
vertices, source hashes, download URLs and the similarity pose remain in each
feature or acquisition audit. The pose fits the existing mapped boat-canal
boundary, with about 1.53 m boundary RMS. This is not an independent accuracy
measurement: bank-edge/centreline differences, historical geometry and OSM
accuracy limit the result. Floor composition is unspecified and uses the user
stone palette. No ride, water or performance-green geometry is generated.

SMD/2024/0579 was inspected but withheld: a building-corner fit had an 11.14 m
withheld residual and its cross-sheet boundary was open. Do not interpret the
historical corridors as a complete present-day CBeebies reconstruction. The
main entrance plaza (OSM relation 7673661) was already mapped; this pass repaints
and verifies it rather than inventing new entrance geometry. Park coverage
remains incomplete.

The V2 world has 77,394 paving records, including 3,031 planning cells absent
from retained mapped ground paving. CBeebies accounts for 1,585 new cells; 4,290
main entrance cells are repainted. Both labelled Wicker plaza footprints are
fully brick: 218/218 and 274/274 cells, with no missing or wrong-material cells.
Whole-world brick-palette coverage rises from 13 to 2,085 cells. All 291 tests
pass, including actual Bedrock readback of every palette block. The exported
world verifies all cells in 1,247 touched chunks and total chunk coverage.

## Expanded application corpus: V3

The address-search and download supplement is documented in `alton-planning.md`.
It expands the source set to 60 retained PDF attachments (50 distinct files) and
96 attachment-discovery seeds. The extractor inspects 72 plan documents and
provisionally aligns 30. After withholding scale-bar annotation faces, 114 paving
polygons remain. They are not 114 new surfaces: many overlap existing mapped
paving or other plan revisions.

V3 adds 482 horizontal paving cells beyond V2 and removes 253 annotation-created
cells, for a net 229-cell increase. It contains 77,623 paving records, including
3,260 planning cells absent from retained mapped ground paving. Both labelled
Wicker plaza footprints remain fully brick. All 297 tests pass and Bedrock
readback verifies all touched sections in 1,264 chunks and total chunk coverage.
Entrance/admissions, Katanga, X-Sector and Forbidden Valley sources remain
available for registration work; acquiring them does not establish new
world geometry. No replacement ride layout is emitted.

## Further expansion: V4

The 2026-10-08 second acquisition pass retains 68 additional PDF attachments
(61 distinct hashes), bringing the catalogue to 275 entries. Extraction inspected
115 documents / 134 pages and provisionally aligned 51 documents.
After explicit visual-review exclusions, 129 plan polygons remain.
The V4 export has 78,972 paving records and adds 1,351
horizontal paving cells over V3, removes 2, and changes material in 30
previously paved cells. New cell composition is recorded in
`evidence/park-paving-v4-validation.json`. All 298 tests pass and 1,294
touched chunks pass full-section Bedrock readback. Ride layouts are unchanged.
Historical and proposed source geometry remains provisional; this is not full
present-day path coverage.
