# International park training and Magic Kingdom pilot

This adds a park-neutral data contract and a U.S. pilot configuration to the current open-data workflow. It does **not** train neural-network weights: the repository currently prepares labels and maps evidence-backed geometries, but has no model-training or Minecraft world-export stage.

## Cross-park learning rules

- Reuse stable semantic categories across parks: buildings, paths/plazas, parking, water, vegetation canopy, ride/attraction structures, and unknown/ignore.
- Keep detailed ground-surface labels separate from object/feature labels. The current ground-label IDs are listed in the Magic Kingdom profile; generic path labels must not be treated as proof of brick, stone or asphalt.
- Store every sample with park, region, source URL, source date, license, imagery/point-cloud resolution, CRS and label scheme.
- Split training/validation by source capture and park area, never by nearby image patches from the same capture. Hold out entire parks or large park zones to measure geographic transfer.
- Report per-class precision/recall and coverage by park/region. A global average can hide a class that only works in one park.
- Keep attribution and license metadata with every artifact. Only ingest imagery, plans and point clouds whose terms permit the intended use; public viewing does not imply permission to redistribute imagery.
- For an unfamiliar region, use OSM as a coarse geometry prior, then add only open/licensed local elevation, aerial, planning and survey data. Preserve source conflicts and uncertainty rather than silently snapping one source over another.

The shared classes are a schema, not training examples. The current Alton Towers bundle does not contain Magic Kingdom examples. Add reviewed image/mask pairs before claiming a class has been learned in a new region.

## Magic Kingdom pilot

`examples/park_profiles/walt_disney_world_magic_kingdom.json` is a small WGS84 AOI around Magic Kingdom, not a surveyed park boundary. The current CLI accepts its `bbox`, `voxel_size_m`, budgets and `sources` fields; without `--features`, it can request currently mapped OSM features from Overpass. It remains a coarse baseline because attractions, detailed paving, tree canopy and buildings are incomplete in OSM.

### Verified free coverage

The AOI was intersected against the USDA Florida 2021-22 NAIP quarter-quad index: one tile intersects, `m_2808136_sw_17_060_20211201_20220330.tif` (Windermere SW, nominal 0.6 m GSD, four bands, acquisition window encoded in the tile ID). The tile is linked in the profile. A 3,200 × 2,700 four-band crop has been prepared from the free public image service at about 0.619 m per pixel in EPSG:32617, and is included in the label-starter package. USDA NAIP imagery is public domain.

The AOI was also queried against the USGS TNM Access API for LAZ LiDAR Point Cloud products. Four Orange County tiles from the Florida Peninsular 2018 project intersect: `LID2019_260760_E`, `LID2019_260761_E`, `LID2019_261060_E`, and `LID2019_261061_E`. Their full source files total about 1.05 GB; crop them to the park AOI before keeping training derivatives. The metadata and direct public download URLs are recorded in the profile. Check acquisition details, classification, point spacing, horizontal CRS and vertical datum from the product metadata before converting the points to geometry.

These are coverage intersections, not proof that every park feature is captured. NAIP is from 2021-22 and may predate changes at the resort. LiDAR helps with terrain and structure/vegetation geometry, but cannot identify paving material by itself. The clipped crop is a source starter only: its aligned ground-surface mask is all ignore (255), and there are no reviewed Magic Kingdom labels yet.

The `ground_surface_classes` map follows the existing ground-label vocabulary and IDs. Broader scene categories live in `semantic_feature_classes` and require their own reviewed masks/labels; they are not mixed into that ground-material mask.

## Next data-preparation stage

1. Download the selected NAIP tile and crop it to the AOI; keep the original tile ID/date and four-band data as source evidence.
2. Download the four LAZ sources only if needed, crop each to the AOI, and preserve the original classification and full per-tile metadata.
3. Create reviewed, pixel-aligned image/mask examples for paths, paving materials, buildings, vegetation canopy, water and parking. Keep uncertain/occluded pixels as ignore.
4. Split evaluation by park zone/source capture; compare transfer from Alton Towers to Magic Kingdom and report per-class misses and false detections.
5. Add a real trainer and world exporter only after sample provenance, labels and evaluation reports exist.

## International source adapters

There is no single free, high-resolution LiDAR or aerial provider for every country. Select a national or regional open-data portal per park. Add source adapters through the same metadata fields (provider, URL, license, capture date, horizontal CRS, vertical datum, units, resolution, classification and coverage). Reproject to a local metric CRS per park; do not assume U.S. feet, British National Grid, or one global vertical datum. If no suitable open data exists, the profile should report missing coverage instead of substituting paid imagery or fabricated detail.
