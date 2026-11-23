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

The profile includes USDA NAIP as a free public-domain imagery candidate. USDA provides state coverage indexes; the Florida acquisition year, resolution and exact coverage of this AOI still need verification before imagery is downloaded or labeled. USDA describes its acquired aerial photography and orthophotography as public domain. Record the actual tile metadata and keep date/resolution with each label.

The profile also registers USGS 3DEP as optional elevation evidence and links the Florida Peninsular 2018 Orange County project report. Orange County project coverage is documented, but this config does not claim that exact Magic Kingdom tiles have been downloaded or verified. Before ingesting tiles, intersect the AOI with the official LiDAR footprint, inspect acquisition date, point spacing, classifications, horizontal/vertical CRS and tile access terms. Use only the free public download route. LiDAR supports terrain and structure/vegetation geometry; it does not identify paving material by itself.

The `ground_surface_classes` map follows the existing ground-label vocabulary and IDs. Broader scene categories live in `semantic_feature_classes` and require their own reviewed masks/labels; they are not mixed into that ground-material mask.

## Suggested rollout

1. Check USDA's Florida NAIP coverage index and the USGS LiDAR footprint against the AOI; record exact tiles, dates, resolution, CRS and download URLs.
2. Obtain permitted, dated imagery and point-cloud tiles. Make reviewed masks for representative paths, roofs, vegetation, water and surfaces.
3. Package Magic Kingdom examples with the shared label map. Keep them grouped by aerial capture/zone for holdout evaluation.
4. Compare against Alton Towers and a separate held-out park. Tune shared features only when the held-out error improves; keep park-specific material/architecture overrides as explicit profiles.
5. Add a real trainer and world exporter only after sample provenance, labels and evaluation reports exist.

## International source adapters

There is no single free, high-resolution LiDAR or aerial provider for every country. Select a national or regional open-data portal per park. Add source adapters through the same metadata fields (provider, URL, license, capture date, horizontal CRS, vertical datum, units, resolution, classification and coverage). Reproject to a local metric CRS per park; do not assume U.S. feet, British National Grid, or one global vertical datum. If no suitable open data exists, the profile should report missing coverage instead of substituting paid imagery or fabricated detail.
