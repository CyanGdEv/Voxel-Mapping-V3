# Drawing layout and outline review

Planning sheets contain physical outlines alongside legends, title panels,
notes, old text covered by later paint, and multiple scale annotations. Raw
text extraction and shape similarity alone cannot distinguish these.

`drawing-layout-v1` retains native PDF coordinates and records paint-order
occlusion, rectangular clip/frame hypotheses, opaque white panel hypotheses,
native label visibility and per-region scale text. Paper size is a hypothesis
from the PDF media box. A scale such as `1/1000 @ A3` alongside `1/500 @ A1`
is retained as two annotations; neither automatically establishes scale or
registration.

Run the resumable inventory and optionally review extracted geometry:

```sh
python -m voxel_mapper.drawing_layout \
  --corpus work/corpus --output work/drawing-layout \
  --candidates work/drawing-geometry/geometry-candidates.jsonl
```

`layout-pages.jsonl` contains labels, review regions and withheld reasons.
`outline-review.jsonl` contains panel overlaps, original paints fully covered
by later opaque fills, and building/path/wall/fence/water/rock/bridge label
proximity hints. Its source candidates must exactly match the retained
extraction, and the original PDF checksum is checked before cache reuse.
The outline stream accepts at most 2.5 million records, retaining one page's
candidate lookup and spatial indexes at a time. This is a record limit,
not a benchmark of 2.5 million verified physical objects.

Enable the inventory before matching in a park job:

```json
"drawing_layout": {"enabled": true, "max_pages": 10000}
```

Matching v2 uses only trace-bound native labels without detected fill/image
occlusion. Older matching receipts require a fresh matching output directory.
Layout cache contracts include the reader version and bounded options. Path,
label, mask and point budget failures withhold the page; a region budget
defers extra region hypotheses while preserving label analysis.

These are review queues. Visibility is conservative for modeled native fills
and image bounds; it is not a raster proof of arbitrary clipping, text
rendering or stroke occlusion. Unknown transparency/layer/clip fill bounds
can withhold a label. Small/nonrectangular panels, other object families,
ambiguous labels and viewports still need review. No reviewed outline is
automatically accepted as a physical object, material, elevation, current
as-built state or world placement. No geometry is added to the world by this
stage.
