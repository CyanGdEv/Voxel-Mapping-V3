# Wicker Man: support positions, density and separate brace planes

The first fence-grid attempt was rejected by the user for inaccurate positions
and density. Its area filter recovered main-row footing symbols but omitted the
smaller outer-footing family. Pairing every left post with one right post also
lost additional legs. The replacement starts from the accepted solid-step track
world, without importing any of the rejected support blocks.

Both symbol families are recovered from the pinned planning linework: main-row
areas 0.27–0.31 m² with compactness at least 0.8, and outer-brace marks 0.09–0.14 m²
with compactness at least 0.6. These are symbol shapes, not measured footing sizes.
There are 877 eligible marks. Original transverse cross-lines connect 811 marks
into 317 groups; 66 isolated marks remain unresolved. Longitudinal lines are
excluded from grouping so adjacent bents are not merged into a large fence grid.
The report preserves source polygon hashes and native cross-line indices.

The generator retains every feasible leg in each group, including extra outer
rows. Foot XY is quantized to Minecraft metre cells; there is no arbitrary
infill or invented relocation. A footprint may coincide with a raster paving
boundary: an explicit source post is allowed at that boundary while neighbouring
pedestrian columns remain protected. Interior paving, existing buildings, track
and low-clearance locations can still prevent a frame or individual leg from
being constructed. All omissions have receipts; the output is not claimed to be
a complete engineering reconstruction.

The user's reference photo guides the dense trestle pattern. Spruce fences form
uprights; oak fences form straight transverse and longitudinal members. Nether-
brick diagonals occupy a parallel voxel plane, one metre away from the straight
frame. Oriented spruce gates distinguish the brace endpoints; oak trapdoors form
joint plates and caps. The diagonal system cannot overwrite a straight member.
Transverse and longitudinal X-braces use cardinally connected voxel stair steps:
vanilla fence blocks cannot reproduce continuously inclined timber sections.

The delivered world contains 223 constructed frame groups. Beam levels, member
sizes, footings and joint designs remain inferred; the photo and plan are not a
structural design or as-built survey. Offset brace planes and source symbol
interpretation are display choices. Some native fence/gate collision volumes
extend above their block cell; clearance checks account for that extension.

Existing terrain, buildings, corrected roof, track elevations and solid steep
decks remain unchanged. Only support cells in previously empty locations are
added. Native delivery validation compares the entire retained park and checks
source-post continuity, support palettes, oriented gates, track headroom, queue
access, shop landings, archive integrity and saved chunks. Actual client import
and in-game visual fidelity have not been tested.

```sh
python -m voxel_mapper.fence_support_world \
  --base-directory PATH/solid-step-track \
  --markings-path PATH/source-markings.json \
  --pdf-path PATH/original-landscape.pdf \
  --output FRESH-DIRECTORY
```
