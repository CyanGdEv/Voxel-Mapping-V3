# Wicker landmark raster evidence

The raster audit samples the retained shop, Burger Kitchen and FastTrack OSM
comparison footprints against the retained Environment Agency terrain/surface
mosaics. It checksum-checks both mosaics against the original retained config's
lineage, checks the datum grid hash and uses the best available metre-scale
EPSG:4326 to British National Grid transformation. Its 1 m windows enclose all
footprint pixel centres. Masked/nonfinite observations are withheld; no gap
interpolation or roof/floor/rail inference occurs.

Run `scripts/audit_wicker_raster_landmarks.py` with `--terrain`, `--surface`,
`--grid`, `--references`, `--archive` and `--output`. The archive is the retained
V15 evidence ZIP; it supplies the original mosaic lineage config. Output is a
source-hashed observation receipt, not control pairs or accepted Features.

The retained lineage describes a 2022-01-05 survey P_10682 patch. The recovered
archive contains the merged mosaics but no per-pixel replacement provenance mask
or original dated patch raster. Consequently the audit does not assign that
survey date to individual sampled pixels. The surrounding composite includes
mixed epochs. Coverage and observed elevated surfaces cannot establish a
present-day physical outline or an independently measured checkpoint corner.

All three footprints have complete finite paired pixel coverage. Full counts,
ODN ground/surface ranges and above-ground observations are retained in
`evidence/wicker-raster-landmark-audit.json`. They are observations within mapped
comparison outlines; source independence of raster acquisition does not itself
verify correspondence to a planning-drawing corner.

## Concrete registration needs

* Recover the dated survey patch and its metadata or a per-pixel provenance mask
  before asserting a local survey epoch.
* Inspect raster edge/roof structure with the source drawing and identify exact
  corresponding attachment points. Pixel centres and mapped polygon centroids
  are not automatically building corners.
* Obtain enough independently reviewed attachment pairs for three noncollinear
  controls and two separate checkpoints, with geometry inside the validated
  domain. This audit supplies zero accepted checkpoint pairs.
* Establish physical feature state, dimensions and materials before promotion.
  DSM heights are surface observations, not station floor or rail levels.

Official product metadata:
https://www.data.gov.uk/dataset/cf3f1137-c12b-44a1-a835-e80fe4a60b92/lidar-composite-dsm-2022-1m
and
https://www.data.gov.uk/dataset/01b3ee39-da3f-47b6-83da-dc98e73a461f/lidar-composite-dtm-2022-1m
The DTM removes surface objects; the DSM retains them. Composite product
metadata does not prove a single local capture epoch. This pass acquires no
new imagery and adds no world geometry.
