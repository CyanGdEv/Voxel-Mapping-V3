# Supplied-world registration and real LiDAR cycle, 2026-11-25

## Outcome

Recovered the supplied world's native horizontal grid against actual EA terrain:
**E = 406912 + X; N = 343984 − Z**, for grid edges in EPSG:27700, at 1 m/block.
Block centres add 0.5 m east and subtract 0.5 m north. This independently
recovers the same source grid used by the registered Mutiny crop; it was not
assigned from the training archive or an unrelated development branch.

The terrain surface relationship is approximately **ODN elevation = Minecraft
block-top Y + 98 m**. For a full terrain block, its bottom coordinate is therefore
approximately `round(DTM_ODN) − 99`. Do not confuse the top boundary with the
block's integer bottom coordinate. This is an observed terrain relationship;
roof, ride and manually changed structure heights are not independently surveyed.

Also acquired a matched dated terrain/surface pair and classified LiDAR, derived
ground intensity, attached real height/intensity context to all 320 registered
chips, and executed nine additional production-architecture training runs.

**Zero blocks changed.** The original `.mcworld` checksum remains
`0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
Existing reviewed paving is already represented in the baseline; new model
results do not justify replacing it. No redundant world export was generated.

## Alignment evidence and limits

- Read the working copy's 8,704 overworld Data3D heightmaps into a 2048 × 1088
  grid. Values are height metadata, not a guaranteed terrain/semantic surface.
  Low/artificial columns at or below Y=10 were explicitly excluded.
- Actual EA composite DTM WCS request: EPSG:27700, bounds
  [406000,342500,409500,344500], native 1 m spacing, 3500 × 2000 cells.
  The WCS coverage is
  `13787b9a-26a4-4775-8523-806d13af58fc:Lidar_Composite_Elevation_DTM_1m`.
- Compare all eight axis orientations using normalized terrain correlation.
  The final coarse search uses only world bounds [64,64,1024,1024], scoring
  0.992813 for the identity orientation versus 0.789216 for the next alternative.
- Refine translation and median vertical offset on that western area only.
  Best reference pixel offset is [912,516]; median absolute residual is 0.265 m
  and reference-minus-heightmap offset is 97.981 m.
- Two eastern regions excluded from both coarse and fine fitting contain 5,327
  and 85,211 sampled columns. Median absolute residuals are 0.253 m and 0.268 m;
  98.78% and 92.98% are within 1 m of the fitted surface offset. Neighbouring
  raster samples are correlated, not independent statistical observations.
- Eight geographically separated OS footprint centres selected for strong
  elevated-footprint agreement contain actual native deepslate roof blocks.
  These are corroborating controls, not a random survey sample or proof that
  every generalized footprint is correct.
- All 3,202 unique reviewed Mutiny label cells agree with the baseline's material
  families or palette proxies at the recovered coordinates. Physical-family
  agreement alone is 2,489 cells; 705 brown-terracotta brick proxies and eight
  gray-terracotta asphalt proxies make up the remainder. The next-best 1 m
  translation matches 2,934 cells including proxies, versus 3,202 at zero offset.
  Terracotta proxies are not measured brick/asphalt truth.

The EA composite and national terrain may share lineage. The world paving
likely shares the reviewed masks' lineage. These checks establish **source-grid
recovery**, not independent absolute survey accuracy or new reconstruction
evidence. The receipt permits read-only attachment/candidate audits and explicitly
does not authorize automatic block edits. Existing geometry stays unchanged.
Exact results: `world_registration_evidence_2026-11-25.json`.

## Actual LiDAR acquisition

The official survey search requires `Content-Type: application/geo+json`; the
initial application/json request returned HTTP 415. Correcting that request
returned the real SK0540 catalogue, including matched 2022 products.

Reused `acquisition.py`, `survey.py`, `point_cloud.py` and survey regression tests
from existing repository branch `codex/alton-reference-world-v3` at
`e923af594a6685bbdc86af4448d5daa3565c19b6`, rather than creating competing
terrain/point-cloud implementations. Added the class-2 intensity raster helper
to that point-cloud implementation. The GIS extra now declares its scientific
and LAS/LAZ dependencies.

Matched survey: **P_10682, 2022-01-05**, 1 m EPSG:27700 raster grids, published
EA ODN heights, OGL-3.0. Native world-area bounds:
[406912,342896,408960,343984], 2,228,224 cells.

| Evidence | Actual result |
|---|---|
| DTM | 100% finite crop coverage |
| Last-return DSM | 98.5948% finite crop coverage; gaps preserved |
| Classified LAZ | 98,342,681 points scanned; 10,537,336 retained |
| Ground, class 2 | 4,262,744 retained points |
| Vegetation, classes 3/4/5 | 256,653 / 706,609 / 4,993,046 retained points |
| Buildings, class 6 | 254,597 retained points |
| Unclassified / low point | 63,262 / 425 retained points |
| Derived ground intensity | 1,729,427 observed cells; 4,262,696 class-2 returns used |

The intensity aggregation drops the crop's exact south/east boundary points to
follow half-open raster cells, explaining the 48-return difference. It averages
actual uint16 LAS intensities per 1 m ground cell, with nodata elsewhere. It does
not interpolate, infer materials or calibrate reflectance. The separately
downloaded published lowest-Z intensity raster is not assumed to have the same
raw encoding. First-return DSM, published intensity and vegetation-height
products were also downloaded but not substituted into the current schema.

`tools/acquire_lidar_training.py` automates discovery, bounded two-worker
downloads, transient retries, tile/year archive caching, survey identity/date
and CRS checks, point cropping, intensity and training catalog generation.
Downloads are limited to 768 MB per archive; scans to 150 million source points
and retained clouds to 15 million points. Changed bounds or source archive hashes
require a fresh output directory, preserving retained evidence. Actual repeated
execution reused all three source archives and the hash-checked cropped cloud.

Exact URLs, archive hashes, capture identity, coverage, counts, license and
provenance: `ea_acquisition_evidence_2026-11-25.json`. Counts are raw observations,
not tree/building counts or independent evidence votes.

## Attachment and new training results

Both the buffered derivative and the supplied 346-sample archive were packed with
GIS/land cover plus real paired DSM-DTM height and raw ground intensity. All 320
registered samples have context; the 26 unregistered views remain untouched.
All 693 original non-manifest members retain identical bytes.

In the 211 × 267 source crop, 43,753 cells have usable height and 33,982 have
observed ground intensity. Of the 3,202 unique labelled pixels, 2,489 have usable
height and 2,947 have intensity. Negative/nonfinite DSM-DTM values remain unknown;
no ground height or intensity is invented to increase coverage.

Same 32 m buffered spatial split, seeds 41–43, 20 epochs, 64-pixel patches,
batch size 4, learning rate 0.001, two CPU threads and 0.2 context dropout.
Each paired RGB/full comparison uses the same archive hash and reviewed pixels.

| Input | Mean validation IoU |
|---|---:|
| RGB | 29.49% |
| RGB + real height/intensity | 26.83% |
| RGB + available GIS/satellite/height/intensity, 28 channels | 30.03% |

Full minus RGB is **+0.54 percentage points**. It remains a one-crop,
validation-selected experiment, not independent park testing or grounds for
promotion. The preceding GIS/satellite-only experiment averaged 31.59%; adding
real LiDAR did not improve that mean. Water polygons and OSM remain absent.
These results argue for better geographical/class coverage and controlled
normalization/ablation experiments rather than automatic deployment.
Full metrics and source hashes: `mutiny_real_lidar_results_2026-11-25.json`.

## Reproduction

```sh
python -m pip install -e '.[gis]' 'Pillow>=10,<13'
python tools/acquire_lidar_training.py \
  --native-bounds 406912 342896 408960 343984 --park-id alton_towers \
  --cache output/ea-cache --output output/alton-ea \
  --gis-catalog output/alton-live/training-catalog.json
voxel-pack-multisource --dataset Alton_Towers_Georeferenced_Ground_Training.zip \
  --catalog output/alton-ea/training-catalog.json --output output/alton-full-context.zip
```

Use the prior buffered preparation tool for training; do not split the 320
rotated/overlapping views randomly. Existing downloaded archives can be reused
with `--catalogue /path/actual-ea-catalogue.json` and the same cache directory.

Extract Data3D metadata only from a working copy using the isolated native
environment documented in the preceding cycle:

```sh
/path/native-venv/bin/python tools/extract_bedrock_heightmap.py \
  --world-copy /path/extracted-copy --output output/world-heightmap.npz
python tools/register_world_terrain.py --heightmap output/world-heightmap.npz \
  --reference /path/native-1m-search-dtm.tif --output output/registration.json \
  --coarse-bounds 64 64 1024 1024 --fit-bounds 64 64 1024 1024 \
  --validation-bounds 1024 64 1984 512 --validation-bounds 1024 512 1984 1024 \
  --minimum-height 10
python -m unittest discover -s tests -v
```

Bounds/masks are explicit pilot parameters, not park-specific reconstruction
rules. No source accuracy, material or world placement is inferred from merely
obtaining a successful network response.
