# Literal straight edges and tapered partition sides

The V6 review conservatively withheld every component whose source paint contained any cubic curve. This also withheld genuine straight wall edges belonging to a path with a door arc. V7 adds an opt-in original-operator review: each retained edge must exactly match an original `l`, `re` or `qu` operator, with paint ordinal, item/edge index and native endpoints retained. Cubic operators, including a collinear cubic whose flattening creates a long chord, cannot authorize a straight wall edge. Only retained source components that already passed clipping, opacity, layer and text-mask checks are considered. Crossing segments are not cropped. Original curves, filled topology and source paint records are unchanged.

Operator indexing is bounded and exhaustion discards the complete index. A failed index or failed source extraction cannot export a partial partition result. The new receipt version and complete source-review hash separate the opt-in path from V6; unchanged V6 seeds and default whole-component architectural reviews retain their prior behaviour.

Real source review exposed a second limitation: some survey wall sides diverge slightly. The opt-in kernel accepts an original side-angle sine up to 0.01 (about 0.573 degrees) and constructs the polygon directly from bounded intervals on both original sides. No line is rotated, offset, extended or snapped into a parallel rectangle. Variable widths remain explicit and overlapping source alternatives remain withheld. The existing default remains 1e-5. This is a drawing-candidate allowance rather than a physical accuracy claim.

## Mutiny north range

The original CTD AL05 plan contains 6,125 literal straight edges; 48 cubic operators are excluded from the literal index. The reviewed core scope still yields 16 eligible original straight segments. The real gain on this sheet comes from allowing its slightly divergent survey sides: one unambiguous band becomes three. Mixed line/curve recovery is verified on dedicated source fixtures; it does not account for additional retained core edges on this real sheet.

Explicit source-plan review selects the workshop/training divider, training/office divider and kitchen/lobby strip. Their exact footprints retain the original slight tilt and taper. Heights remain a 2.5 m display assumption. The partition seed pins the complete literal source review and acknowledges each selected band.

Native conversion also preserves endpoint gaps. A gap of 0.5–2 m between a source strip and the provisional wall's inner plane reserves an adjacent interior depth column. Those columns must contain standing air after complete assembly; a retained shell obstruction rejects rather than silently claiming clearance. This rounds gaps to native cells and may shorten a native partition. The exact source strip is unchanged. The wall's assumed thickness participates in this calculation, and physical doorway identity/height are not verified.

The workshop/training strip retains its previous 12 native cells. The training/office strip adds nine, reserving depth column 1. The kitchen/lobby strip adds six, reserving depth columns 1 and 4. Every V6 world cell remains unchanged. There are 679 review cells and 5,887 composed native blocks in eight chunks; cold readback checks every block and unwritten air. Full-depth arch standing clearance remains verified. No glass is generated. Exact meshes have nine individually closed solid components, with no whole-assembly boolean union claim.

```bash
python scripts/build_wing_shell_study.py \
  --recipe evidence/mutiny-north-wing-window-cycle-review-seed.json \
  --closure-seed evidence/mutiny-north-wing-shell-study-seed.json \
  --partition-seed evidence/mutiny-north-wing-mixed-partition-study-seed.json \
  --sources /path/to/checksum-named-pdfs \
  --output /path/to/fresh-mixed-partition-study
```

The seed opts into `recover_mixed_paths` and `preserve_partition_endpoint_gaps`. Its reviewed bands are not automatically chosen by largest/nearest geometry. Rear-wall apertures and annex correspondence, remaining partitions, upper floors and measured construction heights remain unresolved. This is an isolated provisional study and adds zero accepted park geometry.
