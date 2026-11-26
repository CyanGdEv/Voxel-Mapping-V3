# Park chip registration pilot — 2026-11-24

Actual archived training data was reopened and verified against reference rasters. The registration operation does not establish absolute survey accuracy, imagery rights or mask correctness. All original image and label bytes were preserved in the derivative ZIPs; ZIP integrity was checked.

| Park | Samples | Exact RGB-verified transforms | Labelled verified samples | Labelled pixel observations |
|---|---:|---:|---:|---:|
| Alton Towers | 346 | 320 | 320 | 51,232 |
| Magic Kingdom | 56 | 56 | 3 | 19,367 |
| Total | 402 | 376 | 323 | 70,599 |

Counts include repeated/rotated or overlapping samples and are not independent observations. Magic Kingdom labels only cover class 9 unspecified paving. Alton 320 patches derive from 80 windows and one Mutiny Bay source crop. Keep the whole source group together for evaluation. The original Alton starter manifest lacked park_id; the recovered archive explicitly declares alton_towers.

## Reproduce Magic Kingdom

```sh
voxel-recover-chip-georef \
  --dataset Magic_Kingdom_Reviewed_Paving_Starter_2026-11_v1.zip \
  --index-zip Magic_Kingdom_NAIP_2021_Annotation_Chips.zip \
  --source-zip Magic_Kingdom_NAIP_2021_Label_Starter.zip \
  --output Magic_Kingdom_Georeferenced_Paving_Starter.zip
```

All 56 RGB chips match source raster bands 1–3 exactly at their recorded windows. Source CRS EPSG:32617; source SHA256 91f216d99d987b8a7b873b43ff87fa005ae572121d9345744b8aaa12b270bfad, matching archived raster metadata. Each transform derives from the original GeoTIFF window, not rounded chip index coordinates.

## Reproduce Alton

```sh
voxel-recover-paving-georef \
  --dataset Alton_Towers_Ground_Surface_Starter_Training_2026-11_v1.zip \
  --expansion Alton_Towers_AI_Training_Expansion_2026-11_v2.zip \
  --reference Alton_Tree_Canopy_LiDAR_Training.zip \
  --west 407312 --north 343671 \
  --output Alton_Towers_Georeferenced_Ground_Training.zip
```

The 267 x 211 Mutiny crop matches the reference BNG 1 m mosaic exactly at this origin. All 320 chip RGB arrays match their indexed source window and specified counterclockwise rotation. Recovery composes a pixel-corner affine including the augmentation; the 320 patches keep the same capture/split group. Source archive SHA256 787851d42c29665049220f6876de73802b8b8afe26f7cc17db9aabe2e09f547e; full crop PNG SHA256 c0c29824403099d46546008720223c8367b0c2c331b54bcbb307c2b9aad0c882.

The remaining 26 Alton views have no accepted georeferencing. SIFT matching against a 1 m mosaic produced 11 provisional candidates meeting heuristic gates (at least 20 inliers, 60% inlier fraction, 50% spread on each axis, maximum 0.5 m in-sample RMS). Residuals are relative to the reference and not an independent accuracy measurement. Duplicate/overlapping views occur in different batches. No screenshot transform was admitted to training. Existing intra-park split IDs must not be trusted as independent geographic groups without review.

## Benchmark blocker

A real RGB versus GIS/LiDAR training comparison was not executed. Public ArcGIS and GitHub DNS lookups failed in the local runtime. The available Alton canopy archive has 96 georeferenced raster tiles but is a different label schema; it was used only as the reference RGB mosaic, not as ground-material labels or validated DSM-DTM height. Actual GIS/height context on reviewed pixels is still required in both train and validation splits. Use actual open-data outputs, preserve dates/licensing, and evaluate the park held out as a whole. Do not infer improvement from registration counts or the small Magic Kingdom paving-only mask set. The new recovery commands and unit tests are committed but GitHub CI is not yet confirmed. The derivative ZIPs were prepared separately in the local runtime with equivalent exact-match verification, not uploaded to GitHub.
