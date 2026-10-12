# Bounded regional extraction of dense source plans

Large native plans can exceed the whole-page path budget. The regional adapter retains complete source paint primitives in overlapping windows, in the original `pdf_native_points_y_up` frame. It does not clip paths to a window, close boundary cuts into polygons, assign geographic coordinates, or accept physical objects.

```bash
python -m voxel_mapper.regional_drawing_geometry \
  --pdf /absolute/path/source.pdf --output /absolute/path/output \
  --page 1 --columns 4 --rows 4 --overlap-points 24
```

The grid is bounded to 8 × 8 windows, with 0–100 points of overlap. PyMuPDF's complete native display list is materialized once; the scan is capped at 500,000 entries. Each window independently enforces the normal 100,000 relevant-path, 4,000 candidate and 200,000 retained-point limits. A path-limit failure withholds the complete window; candidate and point-limit deferrals remain explicit in its report. This is a bounded discovery pass, not a completeness certificate or streaming PDF parser.

Original page-wide paint ordinals and geometry IDs survive window extraction. Clip/group scope is tracked even when its defining operation lies outside the window. Any whole source primitive whose bounds cross or touch the window boundary within 0.25 points is deferred. Compound paths are never separated merely to fit a window. Exact geometry also must lie inside the window. Overlap can recover a crossing primitive in an adjacent window; primitives too large for every window remain deferred. Identical overlapping candidates are emitted once. The report retains every window's bounds, selected path count, deferrals and budgets, plus source/output hashes. Source changes during extraction prevent publication of the candidate file.

`drawing_geometry.extract_page` and the ordinary corpus runner also accept an explicit `region_native_points=[xmin,ymin,xmax,ymax]` option, with a distinct extraction contract. Whole-page extraction keeps its existing path ceiling. Regional candidates remain unclassified and unplaced; existing source/view/state, physical identity, survey registration, dimensions and vertical-datum checks still apply before voxel compilation.

## Paper-size scale captions

`printed_scale_review` now recognizes standalone `1/800 @ A1` and `1:1600 @ A3` captions. It chooses the applicable denominator only if the uncropped effective PDF sheet matches one ISO A0–A5 size within 1.5 mm on both dimensions. Rotation is immaterial. Unknown/resized/cropped sheets and non-default PDF UserUnit values are withheld. Ordinary standalone `Scale 1:200` labels retain their visibility checks.

A narrow native adapter joins adjacent singleton glyphs of the same font, size, baseline and paint convention. It retains trace references for coincident duplicate glyphs and never substitutes OCR text. Original-font raster checks remain mandatory; unsupported or ambiguous fonts cannot establish a usable scale. Page size alone does not certify that a drawing was plotted correctly, or establish geographic registration.

## Recovered Mutiny plans

The three source hashes and attachment transports are pinned in `evidence/mutiny-recovered-plan-sources.json`. The reproducible regional trial uses the command above for each distinct source, with unchanged default geometry budgets. Its receipt is `docs/evidence/mutiny-regional-extraction-validation.json`.

These are discovery candidates from historical planning sheets. Their captions can be recovered and their sheets match A1. The `94eefa9040ce` and `3ec5325a5f62` revisions pass the original-font visibility check at 1:800; ambiguous native font resources prevent verified scale visibility for `cbb3d88a3eb1`. Independent survey controls/checkpoints, source policy, component identity, construction state and vertical datum remain unresolved. No real registered frame, physical component or world block is accepted by this trial.

| Source SHA prefix | Retained lines | Retained polygons | Windows without extraction-budget exhaustion |
| --- | ---: | ---: | ---: |
| `94eefa9040ce` | 4,296 | 325 | 16/16 |
| `3ec5325a5f62` | 4,295 | 309 | 16/16 |
| `cbb3d88a3eb1` | 4,295 | 319 | 16/16 |

The 13,839 candidates are counted across three source revisions, not as distinct park objects. Their output hashes, region contracts and complete geometry containment were independently checked after extraction. Whole-page limits remain unchanged.
