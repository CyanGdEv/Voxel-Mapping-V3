# Multisource ground segmentation

The existing RGB ground segmentation U-Net now optionally consumes 25 additional aligned contextual channels (28 total): six mapped/known vector pairs, eight one-hot Sentinel-2 classes plus validity, height above ground plus validity, and raw LiDAR intensity plus validity. Coarse GIS is not a material label. The network still predicts only the reviewed ground-surface class map.

## Prepare

Install free tooling:

```sh
pip install '.[gis,train]'
```

Each source ZIP must have manifest.samples. A sample may declare geographic alignment, e.g.:

```json
{"image":"rgb.png","labels":"labels.png","park_id":"alton_towers","split_group":"zone_01","georef":{"crs":"EPSG:27700","transform":[0.25,0,400000,0,-0.25,340000]}}
```

The example affine is illustrative only: use the actual six coefficients mapping pixel corners to source coordinates, including any rotation/flip already applied to the chip. Do not use the example coordinates for a real park. Only attach context to geographically verified chips. Missing georeferencing is counted and skipped. RGB images and target masks are copied unchanged.

Provide a catalog JSON, with paths relative to the catalog:

```json
{"parks":{"alton_towers":{
  "gis":"output/alton-gis/gis-context.json",
  "dtm":{"path":"lidar/terrain_dtm.tif","source_id":"ea-lidar","license":"OGL-3.0","observed_date":"2024-01-01","vertical_datum":"ODN","vertical_units":"m"},
  "dsm":{"path":"lidar/surface_dsm.tif","source_id":"ea-lidar","license":"OGL-3.0","observed_date":"2024-01-01","vertical_datum":"ODN","vertical_units":"m"},
  "intensity":{"path":"lidar/ground_intensity.tif","source_id":"ea-lidar","license":"OGL-3.0","observed_date":"2024-01-01","encoding":"raw_las_uint16"}
}}}
```

Dates and file paths are examples, not verified source metadata. Height uses nonnegative DSM minus DTM from compatible same-date metre elevations with a known matching vertical datum; values are clipped at 60 m. Intensity is scaled by 65535, not calibrated reflectance. Missing layers are zero with zero validity. The GIS catalog can map other source IDs to roles with source_roles. GIS channels combine mapped presence without counting duplicates as independent evidence. Nearest neighbour resampling retains classes; it cannot create fine-scale evidence. No model labels are generated.

```sh
voxel-pack-multisource --dataset reviewed.zip --catalog sources.json --output aligned.zip
voxel-benchmark-multisource --dataset aligned.zip --output benchmark --cpu
```

The paired benchmark trains RGB and multisource with identical reviewed dataset bytes, split membership, training parameters and random seed; evaluates the same reviewed pixels and reports per-class IoU and validation mean IoU. The best validation checkpoint in each mode is selected by the same criterion. This is validation performance, not an independent test result. No automatic deployment. Use a fresh output directory. Existing RGB-only datasets remain supported by voxel-train-surfaces without --multisource. Use --multisource for the new mode, with optional --context-dropout (default 0.2). Both train and validation splits need some context on reviewed pixels; missing samples retain RGB only. Small chips are padded, not resized; augmentations are synchronized across labels, imagery and context. A separate random generator drops whole contextual modalities, including their known masks.

## Validation and limitations

Unit tests cover context decoding, validity masks, alignment, preserved target bytes and synchronized augmentation. A synthetic one-epoch CPU smoke test exercises both network modes and the benchmark. CI is configured but results are not yet confirmed. A synthetic smoke test is not an accuracy benchmark. Existing Alton/Magic Kingdom starter ZIPs need verified sample georeferencing and real reviewed masks; no training on actual park data or Minecraft placement has been performed. Global source presence and live acquisition still require verification. Future work: inference/export using the checkpoint schema, independent held-out park benchmark, and safe placement/refinement.
