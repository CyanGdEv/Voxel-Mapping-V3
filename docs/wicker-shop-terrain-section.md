# Provisional shop terrain section

The original Environment Agency P_10682 rasters have been recovered from the
official 2022 SK0540 DTM/DSM downloads. ZIP bytes differ from the earlier
archives, but both original GeoTIFF hashes match the retained dated audit
exactly. The build checks raster content, filename, native one-metre BNG grid,
matched survey identity/date, crop coverage and the pinned shop evidence.

```sh
python scripts/build_wicker_terrain_section.py \
  --dtm dtm.zip --dsm dsm.zip \
  --model evidence/wicker-shop-projection-model.json \
  --lidar evidence/wicker-shop-model-lidar-review.json \
  --context evidence/wicker-shop-context-review.json \
  --provisional-floor 184 --output terrain-section
```

The section spans BNG 407461–407603 / 343478–343627: 21,158 terrain columns,
100 native chunks, and the 657-cell context-preferred shop hypothesis. The
Bedrock exporter reopens the saved world and checks all written blocks and
unwritten air cells. This is a visual terrain/assembly review, separate from
accepted park compilation; the production registration and identity gates
remain unchanged.

## Floor conflict retained

Both orientations now have terrain coverage for all 263 emitted block columns.
Each has one intersecting column at the snapped self-fit floor of 183. For the
preferred orientation, the affected spruce wall cell is at BNG 407563 / 343591,
Y 183, over a DTM sample of approximately 183.094 m ODN. The overall sampled
terrain ranges from 180.321 to 183.361 m ODN.

The builder refuses that floor, with no inferred excavation. The delivered
review explicitly uses floor **184 m**, clearing the sampled terrain. This is
approximately +1.353 m above the roof self-fit, and one block above its snapped
floor. It is a clearance experiment, not an independently measured floor or a
replacement of the retained hypothesis. No floor value is automatically raised.

The world includes real dated terrain heights with illustrative grass and
subsurface fill, and the 1:1 slab/fence/trapdoor shop. Paths, station, ride,
lakes, internal floors and building foundations are not reconstructed. Lower
ground beside the shop can expose gaps beneath walls; resolving them requires
floor/foundation/grading evidence rather than silently extending the building.

The next park insertion requires independent alignment/handedness and floor
measurements, followed by a grading/foundation review. Zero independent controls
or checkpoints have been accepted by this review.
