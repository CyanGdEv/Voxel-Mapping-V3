# Alton Towers source-assisted landscape update

The new Bedrock draft adds missing source-traced paving interiors and grass
separators to the existing park landscape. Seven pinned clean Esri RGB exports
provide finer sampling around Towers Street, the gardens, The Smiler and
Galactica. Three retained partial ground masks provide explicit paving, grass,
structure and water guidance. Their hashes match the earlier layered training
dataset source masks; fitted model predictions are not used as geometry.

The landscape remains 2,080 × 1,120 metres, with one block per metre in the same
BNG/ODN frame. It retains the matched 5 January 2022 terrain and raw classified
LiDAR, OSM, historical planning surfaces, 249 generic building shells and the
existing detailed Wicker Man build. Other ride tracks are not reconstructed.

## Source composition

`world_surface_layers.py` accepts a checksum-pinned manifest containing clean
images and their actual returned EPSG:3857 extents. Each native metre cell uses
sixteen bilinear RGB subcell samples. The finer export sampling takes precedence
in overlaps, with a three-metre image-edge feather. A coarser source cannot
replace the base image. The 768,542 cells covered by supplemental sources retain
provider georeferencing. Export sampling of 0.18–0.47 m is not a claim of new
optical resolution or independently surveyed boundary accuracy.

Partial source-assisted surface masks use the explicit legend `paving=0`,
`building_structure=1`, `grass_island=2`, `water=3`, `unknown=255`. At least ten
of sixteen subcells must support one class. Unknown pixels, omitted canopy
ground and thin partial slivers do not claim a whole metre cell. Overlapping
source disagreements leave the existing geometry unchanged and screen local
image infill.

The update adds 2,205 paving cells and clears 236 paving cells for grass. There
are 26 conflicting source cells. Buildings, mapped water, protected Wicker
detail and classified elevated roof returns screen new paving. Structure/water
labels also screen image infill but do not invent building heights or replace
mapped lake boundaries. Cleared grass cannot be refilled by the local RGB rule.
Green RGB screens provisional paving additions. Existing mapped paths below
canopy remain intact. Four assistant-traced island footprints follow the user's
confirmed light-purple rock boundaries in the Towers Street reference. These
explicit nonpaving exclusions also cover bare/shaded island ground which colour
alone cannot separate. They screen additions and image infill without inventing
ground materials, heights or rock-wall geometry. Image-to-clean registration,
source hashes and literal reference vertices accompany the projected polygons;
pixel vertices have not received independent human review.

These masks are assistant source-assisted drafts from user guides, without
independent human boundary review. They are used explicitly for this draft
world. No production model pointer is changed. The latest purple/red dotted
example remains sparse supervision: dots are not filled polygons, widths,
heights or new ride geometry.

## Build

Retain the source inputs described in `alton-aligned-world.md`. Supply a manifest
with `version: world-source-surface-layers-v1`, the exact legend above and up to
twelve unique `layers`. Each layer has `id`, `image`, `image_sha256`, `receipt`,
`receipt_sha256` and `role`. Paths resolve relative to the manifest; absolute
retained input paths are also accepted. The receipt pins image dimensions,
image hash and actual returned `extent_epsg3857`.

Use `role: clean_rgb_only` for appearance. A source mask additionally needs
`role: partial_source_assisted_surface_interiors`, `mask`, `mask_sha256`,
`independent_human_review: false` and `inferred_canopy_ground_included: false`.
The importer rejects sparse-trace roles and changed input hashes.
An image layer can also provide `exclusions` and `exclusions_sha256` for a bounded
EPSG:27700 GeoJSON with role
`source_assisted_user_outlined_nonpaving_islands`. These screen additions only;
they preserve existing mapped ground and do not imply observed ground under trees.

```sh
python -m voxel_mapper.alton_aligned_world \
  --work RETAINED_WORLD_INPUTS --wicker RETAINED_WICKER \
  --surface-layers surface-layers.json --output FRESH_OUTPUT
```

The optional argument keeps existing invocations available. Native output is
never overwritten. Original provider RGB imagery is not embedded in the world;
source receipts, attribution, georeferencing and quality reports are included.

## Verification and delivery

Thirty-four relevant tests cover source pins, class coverage, unknown gaps,
conflicting guides, grass/bridge separation, roof/water/detail protection,
sampling precedence, palettes, transport and native Bedrock export. The final
source replay reproduces the RGB and all composition audits exactly. Water and
retained Wicker detail audits match the previous world. Wicker retains 4,383
dark-oak fence support blocks and 13,000 registered detail blocks overall.

All 9,100 chunks are reopened and compared with the final source composition:
53,073,408 envelope cells, every material/state and unwritten-section air. The
world contains 19,156,496 occupied blocks. Creative/peaceful settings, zero random
ticks, displayed coordinates and the solid spawn floor with four air cells are
checked. Spawn is `[418, 154, -787]` at Towers Street.

The downloadable world is `Alton-Towers-World-v2.mcworld`, targeting Bedrock
1.21.130. The bundle adds import instructions, a north-up overview, source-update
preview, palettes, waypoints, source receipts and validation. ZIP CRC and native
file presence are checked. No Minecraft client import or in-game visual test is
claimed. Physical registration, estimated facades/trunks/species, multi-date
sources, winter foliage, artificial foundations and shallow visual lake beds
remain draft limitations.
