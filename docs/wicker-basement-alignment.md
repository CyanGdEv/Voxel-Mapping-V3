# Basement and queue alignment

The original 2967-22 basement view is now related to the normalized 2967-21 upper-floor view and the existing 2967-48 roof-based placement. The page title blocks coincide, but the drawing views do not: their corners cannot be used interchangeably.

Three corners of the basement's dashed **shop above** outline fit the retained upper-floor shop wall outline using a rigid transform. The fourth corner is held out and differs by **0.06064 m** at printed scale. The fit has unit scale, no shear and no reflection. The existing floor-page reduction correction is reused; building dimensions are not stretched to agree. The baseline ten-stroke basement review, 23 basement reference-stroke bindings and the selected upper-floor queue/boundary strokes are replayed from checksum-pinned originals. All four shop corners and the three seam checks retain their exact stroke references.

As a diagnostic from a second building, the dashed **preshow above** envelope overlaps the normalized upper-floor reference by **96.4%**; their exterior boundaries differ by at most **0.217 m**. This diagnostic is excluded from the fit. The shared joint is closed only at a 0.1-micrometre numerical tolerance to avoid an affine floating-point slit. The upper reference uses source exterior extents and a clipped joint, not a complete accepted wall mesh. These related-drawing checks establish neither independent survey accuracy nor as-built identity.

## Queue evidence

Eight continuous source strokes (609–616) trace **36.701 m** of the queue walkway's outer edge. It meets the separately closed four-stroke **44.527 m²** queue walkway (601–604). Both now appear in the same nominal/BNG frame as the basement, its two visible 3.45 m wall gaps and the current buildings. The open edge is not converted into a centreline, a closed paving polygon, internal queue lanes or a staircase. Threshold elevations and circulation roles remain unresolved.

## Why world replacement is withheld

The source-aligned basement occupies **151 outer-envelope centre cells**. The earlier estimated upper-derived interior has 106 centre cells; these represent different footprint roles, so the difference is not a direct wall-count estimate. The comparison identifies 56 new outer-envelope centre cells outside that older interior and 11 old interior cells outside the aligned outer envelope.

All **five** retained entrance walking columns fall inside the new basement envelope. It also contains five orange/blue/brown ride/support marker columns and 274 retained structure records between the lower and upper levels. The aligned inner envelope extends about **39.1 m²** beyond the current preshow upper-wall footprint. Replacing the old undercroft alone would therefore conflict with the existing entry supports and leave the upper model inconsistent with its source footprint.

The next world edit must reconcile the preshow upper walls and roof assembly with the normalized floor outline, then coordinate the basement walls/openings and queue approaches. The generator emits the exact affected coordinates and refuses automatic replacement. The corrected shop, native slab roofs, previous world archive and terrain are preserved. No new training labels or world blocks are added.

## Replay

```sh
python -m voxel_mapper.basement_alignment \
  --world-directory current-station-access \
  --pdf-directory original-pdfs \
  --review-directory source-reviews \
  --shop-directory corrected-shop \
  --output fresh-alignment-review
```

`voxel_mapper/data/wicker-basement-alignment.json` pins the exact current world/report/voxel inputs, original PDFs, normalization reviews and placement review. Outputs include a plan comparison, annotated original basement gaps, projected EPSG:27700 GeoJSON and the JSON correspondence/conflict report. The GeoJSON contains projected metres, not RFC 7946 longitude/latitude.

Fourteen focused tests cover held-out rejection, scale/reflection rejection, non-collinear control requirements, actual stroke endpoints, cancellation, exact collision reporting and existing station/access behavior. Real-source replay verifies all pinned inputs and confirms the original world bytes remain unchanged.
