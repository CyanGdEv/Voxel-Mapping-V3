# Provisional shop roof reconstruction

The dedicated revised elevation sheet now supplies a source-traced local roof
surface, rather than only image-placement metadata. Four elevation profiles were
manually reviewed on a fixed 1888 × 1334 full-page rendering. The proposed main
roof is represented by six vertices and four triangles in local metres; the
origin is its centre in plan and the drawn shop floor vertically. No park
translation, geographic bearing or ODN floor datum is assigned.

| Measurement | Approximate drawing-derived value |
| --- | ---: |
| Main roof length | 16.88 m |
| Main roof width | 12.83 m |
| Visible main wall length | 15.90 m |
| Visible main wall width | 11.81 m |
| Ridge above drawn shop floor | 7.21–7.26 m across views |
| Upper roof eave above drawn shop floor | 3.52 m |
| Visible end overhangs | 0.49–0.53 m |

Each annotation endpoint has an explicit manual sampling bound of ±2 rendered
pixels. Differences of two endpoints therefore have a worst-case sampling bound
of approximately ±0.18 m. This is not total physical accuracy: line thickness,
interpretation, design changes, source accuracy and as-built discrepancies are
not resolved by pixel bounds. Opposite views agree within their sampling
intervals. The graphical 10 m scale bar measures 9.98 m using the native page
transform and the printed 1:100 view scale.

The revised roof-plan line `96cae9d1…` is re-extracted from its checksum-pinned
PDF, yielding 16.85 m, approximately 0.04 m shorter than the elevation trace.
This supports drawing consistency; exact physical edge correspondence remains
unverified. The revised floor plan is visually consistent with a rectangular
main shop containing entrances and internal partitions, but those openings and
wall thicknesses have not been traced or incorporated. Its 170 m² GIA is an
internal area, not a check against the 187.7 m² outer wall-span rectangle.

The mesh excludes fascia thickness, the small roof projection, walls, entrances,
landscape bunding and adjacent buildings. Proposed roof appearance is retained
in the source catalogue, but no Minecraft material has been assigned. The mesh
is not eligible for accepted park/world placement. Independent physical
registration controls and checkpoints remain unresolved.

## Reproduce

```sh
python scripts/reconstruct_wicker_shop_roof.py \
  --pdf shop-elevations.pdf --roof-pdf revised-roof-plan.pdf \
  --annotations evidence/wicker-shop-elevation-annotations.json \
  --output local-roof.json
```

The script checks both source hashes, the rendered pixel hash and dimensions,
then transforms all annotated points into native PDF coordinates. Evidence is
retained in `wicker-shop-elevation-annotations.json`, `wicker-shop-local-roof.json`
and `wicker-shop-local-roof-validation.json`. Validation covers deterministic
replay, graphic scale, opposite-view consistency, mesh indices and rejection of
corrupt sources or stale raster annotations. Zero world geometry was placed.

Next: trace actual external wall segments and entrances from the floor plan,
then compare the proposed local roof with the dated LiDAR envelope without
assuming that the proposed floor level is already an accepted ODN datum.
