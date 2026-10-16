# Connected doorway review

The new Wicker review jobs cut the declared narrow opening through both columns
of its angled display wall and generate a separate exterior approach for each
opening. These are still provisional scenes using the existing manual study,
estimated orientation and unverified 184 m floor. Successful access checks do
not establish accepted planning geometry, real-world placement, an as-built
building or a trained model.

Restore the three originals described in [the component guide](provisional-component-review.md),
install `.[planning]`, then use fresh output directories:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/wicker-doorway-review-a-job.json \
  --output output/wicker-doorway-a

python -m voxel_mapper.world_pilot \
  --job examples/wicker-doorway-review-b-job.json \
  --output output/wicker-doorway-b
```

Open `park.mcworld` in Minecraft Bedrock. The supported spawn remains native
`[11, 69, 3]`. `access-review.svg` shows all proposed exterior routes and the
primary route profile. `access-review.json` records the reopened native checks;
the same result is embedded in the world's quality report. The voxel data,
component report, reports and diagram support fresh replay. Package bytes need
not be identical between exports.

## What changed in the opening cut

The old mask sampled one dominant grid axis along the opening line. For the
narrow doorway, this cleared `(3, 8)` in hypothesis A and `(-4, -9)` in B. The
angled native wall also occupied the adjacent interior column, leaving two
spruce wall blocks across the passage. A clear sample column did not establish
a connected opening.

The native slab compiler now considers cell centres whose projection falls
between the original source jambs and within the cell's normal projection
radius of their plane. It retains the old samples and cuts the additional
display column below the quantized opening height. The extra column is `(3, 7)`
in A and `(-4, -8)` in B. Two spruce wall blocks are removed in each hypothesis;
other component cells and materials remain unchanged. Temporary door sealing
still verifies that the rest of the native shell is closed.

No source vertex, endpoint, height, mesh dimension or placement coordinate is
changed. This does **not** make the native aperture exact. The manual study span
is about **0.901 m**, while the two-cell envelope projects to about **1.758 m**
along the wall. The envelope overruns the jamb ends by approximately **0.531 m**
and **0.326 m**. `native_mesh_audit.doorway_rasterization` records these values,
the source endpoints, legacy and additional columns, source width/height and
`native_geometry_exact: false` for every opening. The band describes display
raster thickness; measured wall thickness remains unknown.

Openings below the 0.6 m player-width rule remain marked as source-too-narrow.
A finite span with no eligible native grid column is marked unrepresented.
Neither case is promoted to a usable passage by shifting jambs or forcing a
larger opening. One-block-per-metre geometry cannot represent every source
opening faithfully; physical width acceptance remains separate.

The new mask is also used when the draft park compositor reserves native
apertures, so it cannot restore one of the newly cleared cells using the old
single-column reservation.

## Exterior access is checked separately

Access audit version `provisional-world-access-v2` distinguishes:

* support and two metres of headroom at the declared floor;
* a connected route into the building interior;
* a supported crossing onto an exterior cell;
* an exterior route from emitted mapped walking surfaces;
* reachability from the saved spawn.

The exterior route cannot pass through another entrance and across the interior.
An opening reachable from inside can therefore remain unresolved. This tightens
the earlier audit, whose path/spawn checks could count such an interior detour.
The diagram marks openings green only when their exterior route and spawn
checks both pass.

The explicit new policy inside `review_component` is:

```json
"access": {"policy": "estimated_each_opening_approach_v2"}
```

It seeks a separate exterior approach for each interior-connected opening,
starting with the closest mapped surface. Later approaches may reuse earlier
support. A combined limit of 60,000 explored construction states applies across
all openings; each route is still limited to 32 columns, within 32 m of the
component anchor, with at most 16 blocks of fill depth. Routes are level or
descending from the floor, use cardinal movement and at most half-metre steps,
and require two metres of headroom. No terrain excavation or covering of mapped
walking surfaces is inferred. New cells are estimated stone or bottom stone
slabs; source meshes stay unchanged.

Before packaging, all proposed routes are checked against reopened native
blocks, including secondary routes. A blocked or unsupported route or spawn
rejects the export. Unknown collision shapes obstruct the simplified centred
player corridor. This remains a conservative check, not full Minecraft physics,
accessible-design compliance or an independently measured site access plan.

## Current retained examples

| Hypothesis | Added access blocks | External route lengths | Unresolved openings under this rule |
| --- | ---: | --- | --- |
| A | 11 | NE 7 m, SW 26 m, NW 21 m | None |
| B | 14 | SW 7 m, NW 16 m, NE 28 m | None |

All three declared openings now have checked exterior-to-interior access. Two
previous wall records are removed per scene; the terrain, mapped surfaces,
remaining component cells and source model are preserved. All new access cells
retain `accepted_physical_geometry: false`. Accepted planning components, accepted
park-world additions and generated training labels remain zero.

The three elevated OSM paths still lack absolute elevations and remain withheld
as generation errors. Minecraft playtesting, independent building identity,
placement, source dimension disputes and the floor datum still need review.
The validation receipt in `docs/evidence/doorway-review/` retains exact artifact
hashes, source-grid approximation and replay checks.

The subsequent [native walkthrough](native-world-walkthrough.md) adds complete
spawn-to-interior route witnesses and a guide/result form for testing this
same geometry in Minecraft. It also rejects the case where two disconnected
mapped approaches appear reachable only through another entrance's interior.
