# Wicker Man and courtyard geographic alignment study

The retained current geometry now has a map-relative transform to British National Grid (EPSG:27700) and a separate terrain-following Bedrock preview. The original flat Wicker/courtyard world is preserved. This stage does not expand the area, reconstruct building heights, or approve independent geographic registration.

Three labelled source polygons (Shop, Station and Maintenance) supply centroid correspondences to OSM ways 834919978, 834919980 and 834919981. The latter two are distinct outer components of station relation 17436869. A rigid, orientation-preserving fit keeps the existing printed-scale metre grid unchanged: no stretch, reflection or shear. Its rotation is approximately -1.0829185 degrees. Control centroid residuals are approximately 0.187, 0.144 and 0.310 metres; polygon IoUs are 0.966, 0.882 and 0.852. These are agreement with mapped footprints, not surveyed accuracy. The controls are clustered and the two station components are adjacent parts of one complex.

The retained October 16 OSM snapshot is projected with the pinned regional OSTN15 grid. No ballpark or Helmert fallback is allowed. The EPSG:7710 WGS84 approximation has advertised one-metre operation accuracy; OSM source accuracy and epoch differences are not independently measured.

## Checks outside the fit

The ride centre line is compared with mapped Wicker Man track without entering the fit. At 201 uniformly spaced samples its median separation is 0.840 metres, 95th percentile 1.844 metres and largest sample separation 2.641 metres; symmetric Hausdorff distance is 2.863 metres. These are horizontal checks only; track heights remain unknown.

The courtyard inner-area comparison is also held out: centroid difference 2.448 metres and IoU 0.803. Its manual raster trace and same-building join remain provisional. A separate nearby source building is close in position (0.685 metres) but disagrees in outline (IoU 0.451). That mismatch is explicitly flagged and neither polygon is warped to hide it. These checks use the same OSM dataset and do not become independent survey checkpoints. Production-placement and training eligibility remain false.

## Terrain and coordinates

The full EA 2022-01-05 SK0540 DTM was recovered. Its ZIP bytes differ from the previously retained archive, but the extracted original raster exactly matches SHA-256 `57becd3683c8492b645472d936ff0d714acd5d037326a6c6f0b6050e04eb2493`. The crop preserves original EPSG:27700 one-metre pixels, without resampling or filling nodata. All 39,250 preview cells have coverage; sampled ground ranges from 175.920 to 193.514 metres ODN.

Each existing source-cell centre is transformed to BNG, samples the nearest DTM pixel, then floors the ground elevation to a one-metre block. Every current XY cell/material and each edging column is retained: 12,602 ground feature cells, 4,178 plan-marking cells and 1,147 rock/fence columns (1,213 above-ground blocks). The original supported spawn keeps its horizontal position and moves to the corresponding ground height. There is no invented smoothing, flat building pad, grade correction or route reclassification. Draped coloured footprints are not finished floors; stairs/fences are still the earlier display prototype.

The Minecraft grid follows the retained drawing axes, rotated relative to BNG. `planning-geographic-alignment.json` inside the world supplies the exact affine transform:

```
source_xy = [Minecraft X + 0.5, -(Minecraft Z + 0.5)]
[E, N] = rotation_matrix * source_xy + translation
ODN block elevation = Minecraft Y - vertical_offset_blocks
```

For this export the vertical offset is -111 blocks. Further geographic features must use the inverse of the same transform to enter this world. OSM is a comparison/reference layer, not an additional set of overlapping path blocks. Building outlines, paving, ride guides and courtyard polygons are also exported to `planning-bng.geojson`, explicitly in projected BNG metres rather than RFC 7946 longitude/latitude.

## Reproduce and validate

The delivered portable review pack includes the six unchanged planning inputs, map snapshot, terrain crop, grid, source receipts and a pinned request. With the repository installed:

```sh
python -m voxel_mapper.planning_geo_preview \
  --config alignment-request.json --output a-new-geographic-preview
```

This is currently a source/CLI preview workflow, without a new desktop button or automatic production merge. The existing 65,536-cell geometry limit is retained. The terrain export separately caps native writes at one million, using three-block per-chunk foundations; this accounts for varying heights rather than changing the old flat exporter. Missing coverage, nodata, altered pins, reflected/degenerate controls, changed map identities and exhausted native budgets fail instead of cropping or stretching.

Twenty focused geometry/grid/alignment tests passed, followed by all five final geographic tests after the overlay update. The actual native export validates all terrain heights, materials, partial-block properties, edging, headroom and supported spawn. Archive bytes/CRCs and all 187 extracted chunks reopen successfully. Minecraft client import, walking and final architectural/path levels have not been tested.

Before further area expansion, review the courtyard/nearby-building discrepancies and add distributed controls from independent survey evidence. DTM ground, planning finished-floor levels, roof/ride heights and source dates must remain separate. The current alignment provides a reproducible common frame for that work.
