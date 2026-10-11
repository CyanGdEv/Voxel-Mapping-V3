# Retaining short wall returns and roof edges

Native extraction previously applied a fixed 12 PDF point minimum to open strokes. At 1:200 this removes segments shorter than approximately 0.85 metres. Short returns, joints and roof edges may therefore disappear before exact enclosure recovery.

`min_line_length_points` is now an optional, source-contract-pinned extraction parameter, bounded from 0.25 to 12 points. Omitting it preserves the existing default and its extraction contract. Retaining short strokes changes no coordinates and performs no snapping, gap filling or semantic classification. Clipping, transparency, text masks, stroke styles and finite extraction/recovery budgets still apply.

For a park pipeline job:

```json
{
  "drawing_geometry": {
    "enabled": true,
    "min_line_length_points": 0.25,
    "options": {"max_candidates": 10000}
  },
  "linework_boundaries": {"enabled": true, "envelopes": true},
  "landmark_context": {"enabled": true}
}
```

For the area-by-area controller use `"drawing_geometry_options": {"min_line_length_points": 0.25, "max_candidates": 10000}` at the configuration root. These options apply to each area's extraction, are validated before source work and are pinned by its existing configuration checkpoint. Changing them requires a fresh area run. The geometry CLI exposes `--min-line-length-points`; Python callers can set the same bounded options.

A lower cutoff increases symbol and annotation noise as well as boundary detail. It may need a larger candidate budget; a partial extraction must not be described as complete. Landmarks remain unclassified until physical identity and geographic registration are established.

## Mutiny Bay test

The pinned floor/roof PDFs were replayed with a 0.25-point cutoff and a 10,000-candidate budget. Both finish without extraction budget deferral. The floor plan retains 8,465 native candidates and recovers 723 enclosed faces; the roof sheet retains 820 and recovers 149. Seven floor-plan room labels obtain unique complete enclosure associations.

Visual inspection of a preliminary five-outline relative fit found a courtyard fragment bounded by one survey line. Landmark-context v2 therefore also withholds a candidate when a contributing straight source line continues beyond both sides of its intersection with the polygon: each extension must be at least half `min_continuation_m`, and the existing shared-length/outside-ratio conditions must hold. This diagnostic policy can exclude real subdivisions along continuous walls. Original geometry remains available.

With the stricter screen, floor/roof pools contain 103/41 candidates. Neither finds a park-map fit. One cross-sheet hypothesis has four supports and approximately 0.0147 metres centroid RMS; it fails the five-landmark requirement. The preliminary five-support fit is not treated as accepted alignment. Exterior wall/roof identity, independent geographic registration and terrain contact remain unresolved; no world is generated.

`evidence/mutiny-short-boundary-edge-audit.json` includes input and output pins, visible scale evidence, counts, the significant candidate decisions and held-out checks. Sub-threshold-only decisions are summarized, with their complete decision-array digest retained. The reproduction command regenerates the complete audit from the pinned inputs.
