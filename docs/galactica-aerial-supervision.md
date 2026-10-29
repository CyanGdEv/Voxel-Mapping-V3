# Galactica aerial ride labels

The user identifies yellow as monorail and purple as roller-coaster track in the 1,222 × 1,280 reference image. The legend is bound to that image's SHA256. Earlier purple building/roof annotations retain their existing meaning. This intake creates sparse projected ride labels; it does not train weights or place world blocks.

The reference is registered against separately acquired 1,536 × 1,536 Esri RGB using unpainted image texture. The similarity fit uses 210 inlier image features, with a 1.60-pixel 95th-percentile inlier residual. The reference is rotated 94.87 degrees relative to the clean north-up image. The true returned EPSG:3857 image extent and a pinned OSTN15 operation locate the labels in EPSG:27700. The image fit and OSM agreement are reproducibility checks, not independent physical accuracy measurements.

The clean-image target contains 3,911 monorail pixels and 9,224 coaster pixels. All other pixels are ignored (`255`), including gaps between dots. Ink thickness is not a measured track width; strokes are not interpolated into a complete route. There are 2,904 sparse review locations, separate from the full positive-pixel loss mask. Model RGB comes only from the independently acquired clean image, never the painted reference.

OSM comparison keeps original ways and their layer/tunnel properties. Median / 95th-percentile nearest-map distances are 0.76 / 1.65 m for monorail and 1.72 / 4.96 m for coaster. They describe map agreement; labels are not snapped to OSM. Nearby coaster ways include other rides and remain labelled as contextual source ways, not all assigned to Galactica.

Two monorail/coaster crossing areas are flagged for review. A full scan of the retained January 2022 EA survey crops 327,976 eligible raw returns to the trace region. Two-metre queries at the crossings contain 70 and 50 returns, respectively, with several separated height groups. The elevated groups are classified mainly as vegetation: none is accepted as either track's height. Raw classes, height groups, source hashes and query positions are retained. XY crossings do not become connected route junctions. Coaster self-overlaps also keep original source-way separation.

The training input includes native one-metre DTM, DSM and above-ground height channels sampled at clean RGB pixel centres. This does not increase measured height resolution. Height channels are features, not supervised track elevations. Ground paths and canopy remain separate layers beneath/above the ride evidence. The existing world remains unchanged.

## Reproduce

Install the `mappingreview` optional dependencies. Use the retained reference, clean provider RGB/receipt, OSM snapshot, BNG frame with its pinned local OSTN15 grid and image-specific legend:

```sh
python -m voxel_mapper.ride_aerial_supervision \
  --reference user-reference.jpg --clean clean-rgb.png \
  --imagery-receipt imagery-receipt.json --frame frame.json \
  --osm osm.xml --legend voxel_mapper/data/galactica-aerial-legend.json \
  --output FRESH-OUTPUT
```

Optional raw/height context requires all four arguments together: `--cloud-archive`, `--cloud-receipt`, `--dtm` and `--dsm`. The source archive checksum, native BNG header and declared ODN receipt are checked. Withheld and synthetic returns are excluded. Output must be fresh. Large imagery and raw sources remain task artifacts, outside Git.

Validation covers local legend scoping, positive-only labels, isolated JPEG specks, unresolved crossings, correct pixel-centre projection and rotated unpainted texture registration. Existing path/building supervision and source ride-geometry tests check for regressions. Exact label/mask replay and independent raw-return crossing queries accompany the retained delivery. No new background negatives, 3D labels, support targets or model accuracy improvement are claimed from this single example.

Attribution: user-supplied annotations; Esri World Imagery and its providers; OpenStreetMap contributors (ODbL-1.0); Environment Agency information (OGL-UK-3.0). Source dates differ and physical registration remains unverified.
