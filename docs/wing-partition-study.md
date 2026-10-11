# Source plan partition study

The north-range shell has a provisional rear plane. Visual review of the retained external elevation and plan shows projecting annexes: the rear elevation is not simply the core's straight rear wall. Its apertures and height datum are not silently mapped onto that plane. Rear correspondence remains unresolved.

An independent next step uses AL05's existing ground-floor geometry inside the source-pinned north-range plan scope. The old paired-wall detector only examines complete two-point components. This review enumerates exact straight segments from longer original paths and rings, retaining original component contracts, ring/segment indices, native endpoints and paint. No source is rewritten or cropped. Whole segments crossing the scope are excluded. Curved, dashed, truncated and unknown-paint paths are excluded. Segment or pair budget exhaustion withholds partial results.

The unchanged shared pairing kernel retains original side intervals, width/overlap checks and overlapping-interval competition. Its normal whole-component entry point and defaults are unchanged. Segment pairing remains a diagnostic source candidate stage and does not establish wall identity or height. It is not automatically exported by the area controller.

The real north-range scope yields 16 eligible original segments and one unambiguous wall strip. Explicit visual source review identifies it between the workshop and training-room area. Its plan-local bounds are approximately x=5.722–6.069 m, depth=0.408–5.717 m; original paired width is approximately 0.330 m, with 5.308 m overlap. The strip is slightly tilted in the drawing and is not snapped into an axis-aligned polygon. The remainder of the room-wall inventory is unresolved.

`evidence/mutiny-north-wing-partition-study-seed.json` selects the reviewed band by ID, pins the parent model and complete source review and explicitly acknowledges footprint review. The 2.5 m partition height is a display assumption. Exact extrusion retains the source strip and validates a closed oriented solid. Original component endpoints, source intervals, native band sides and the local transform must agree. Native sampling uses one block of thickness and a half-block top slab; it cannot retain the thin drawn width. All prior shell cells remain unchanged and the full-depth arch standing air is checked again. No glass is generated.

The new world adds 12 partition cells to the previous 652-cell shell, yielding 664 review cells and 5,872 composed blocks in eight chunks. All native blocks and unwritten air are cold-read verified. The exact cutaway render hides the roof for inspection and colours the new partition green. The downloaded world retains its roof. Rear closures, joining planes, upper floors, other partitions and annex volumes remain unresolved or hypothetical; no accepted park geometry is added.

```bash
python scripts/build_wing_shell_study.py \
  --recipe evidence/mutiny-north-wing-window-cycle-review-seed.json \
  --closure-seed evidence/mutiny-north-wing-shell-study-seed.json \
  --partition-seed evidence/mutiny-north-wing-partition-study-seed.json \
  --sources /path/to/checksum-named-pdfs \
  --output /path/to/fresh-partition-study
python scripts/render_wing_shell_study.py \
  --model /path/to/fresh-partition-study/shell-model.json \
  --cutaway --output /path/to/partition-cutaway.png
```

The command revalidates original PDF checksums, rendered samples and existing view captions before deriving bands. It requires a fresh output. The seed is an explicit study review, not autonomous acceptance of every room wall. Source/proof/output edits reject rather than updating geometry silently.
