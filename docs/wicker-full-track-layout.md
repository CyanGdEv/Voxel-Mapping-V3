# Complete Wicker Man track layout, without supports

The complete retained 773.57 m plan centreline is built in the user's oak/spruce
slab, fence and outward-trapdoor pattern. An explicitly estimated 1.60 m connector
closes the small drafting gap. No footing, timber bent, brace, ground-reaching
post, under-deck tie or functional ride mechanism is added.

The input is the pinned 373/95/7 B planning drawing and the same mapped geometry
used for the earlier section. All 14 printed HP/LP levels are replayed against
original PDF text and crosshair vectors; expected chainages prevent accidental
branch rebinding. HP7 remains a provisional crossing assignment supported by the
crosshair's much closer selected branch; it is not independently surveyed.

The full vertical profile remains a display hypothesis. The flat station and
maintenance approach is estimated at 185 m to chainage 120 m, rising to an
estimated queue overpass at 188 m by chainage 140 m and the lift start at
165 m. The lift rises to
HP1, and the return closes at 185 m. Two extra estimated intermediate controls
separate raster deck crossings: 190 m at chainage 180 m and 190.5 m at 405 m.
They do not change the printed HP/LP values. Smooth interpolation and half-block
quantization between controls do not reproduce measured banking, actual vertical
curvature or construction sections. The actual raster surface may be higher than
an anchor by half-block rounding and choosing the highest local sample per cell.

Unlike the earlier single-section sampler, separate track visits to one XY column
retain separate vertical layers. The generator rejects slabs inside another
track's three-block centre clearance. It checks every slab's cardinal connectivity
and continuity of the ordered centre samples, including the closed seam.

Only local terrain under track cells is lowered, up to the six-metre cut budget.
Exact original terrain rows are retained in receipts. The provisional station,
preshow and maintenance mesh can be opened along the source track path, with
individual block-removal receipts. Adjacent fence aliases may be retired; shop
entrances and unrelated structures are protected. These cuts are prototype
integration changes, not recovered architectural portals or earthworks.

The export starts from the pinned pre-track maintenance world. This replaces the
previous 98.9 m track and avoids importing its rejected support frames. Native
checks verify every slab surface and centre headroom, archive integrity, chunk
reopening and the retained vertical offset. Independent delivery checks compare
all old native structure states except declared passage removals, and preserve
the corrected shop landings and queue surfaces/headroom. Actual Minecraft client
import and ride operation have not been tested.

```sh
python -m voxel_mapper.full_track_world \
  --base-directory PATH/maintenance-built \
  --markings-path PATH/source-markings.json \
  --pdf-path PATH/original-landscape.pdf \
  --output FRESH-DIRECTORY --allow-provisional
```

The profile `wicker-full-track-layout.json` pins original inputs, all marker
bindings, estimated approach/crossing controls and construction budgets.
