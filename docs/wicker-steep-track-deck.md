# Solid timber deck on steep track steps

This revision changes deck thickness on the elevation-corrected world. It does
not resample the route, move running surfaces, excavate terrain or alter roofs.

A one-metre rise between consecutive saved centre samples marks a steep step.
The three-cell deck is thickened within approximately one metre of that step.
Steep cardinal edges across the deck are checked separately, so a level centre
sample cannot hide a steep outer-edge gap.
Whole-height surfaces use matching oak or spruce full blocks instead of top
slabs. A surface at a half-height retains its bottom slab and gains a top slab
in the cell below. Those halves touch, giving one metre of wood with exactly
the same running height. Gentle half-block rises keep the previous slab style.

Only track deck cells are replaced. Under-deck fills that would touch retained
terrain, other geometry or a lower track's headroom are withheld and reported.
The thickness change is limited to the deck itself; no support frames, ground
posts, ties or footings are generated. Existing fences and trapdoors remain.

```sh
python -m voxel_mapper.steep_track_world \
  --base-directory PATH/elevation-fixed \
  --output FRESH-DIRECTORY
```

The input world, voxel records, track cells, ordered samples, clearance cells and
report are all checksum-pinned. The export independently verifies every original
running surface and centre air cell. Delivery checks compare the native states
of all unchanged terrain/building/track cells and inspect the full blocks and
paired half slabs actually saved in the world. Actual client import and ride
operation remain untested.
