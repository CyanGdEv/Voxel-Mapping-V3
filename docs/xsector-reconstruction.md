# X-Sector first reconstruction pass

`voxel_mapper.xsector` starts Smiler and Oblivion in the retained full-park
coordinate frame. Both OSM track graphs form closed unbranched routes. Smiler
has 34 non-adjacent segment intersections; each still needs branch-specific
vertical control. The reported lengths are horizontal plan lengths, not the
actual three-dimensional track lengths. OSM layer numbers never become heights.

The first world overlay replaces the two generic solid station extrusions with
level, hollow, black-concrete footprint shells. The slab is the median terrain
sample and the roof is a composite DSM percentile with at least four metres of
clearance. Neither is a surveyed loading level or finished architectural model.
Doorways, platform levels and facade details remain unresolved. Existing park
paths, terrain, shops and the Wicker Man reconstruction remain in the copied
world; no new queue or entrance connections are inferred.

The overlay checks every cell, including preserved cells and air, in changed
chunk sections after saving/reopening the Bedrock world. It also checks total
chunk coverage. Untouched chunks come from the previously verified full park;
this is not a new exhaustive whole-park verification. World block counts include
the composed overlay delta. Existing outputs are never overwritten.

```bash
python -m voxel_mapper.xsector \
  --park-output /absolute/path/alton-full-park \
  --osm-raw /absolute/path/osm-raw.json \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/xsector-pass
```

The datum grid is checked against the original acquisition hash before sampling.
Output contains a copied full-park `park.mcworld`, station levels, visit
coordinates, the complete track topology/crossing audit and validation results.

## Evidence and remaining work

`voxel_mapper/data/xsector-sources.json` records official ride dimensions, the
Smiler planning application and alternative archived plan/elevation images.
The council PDF endpoint returned an HTML 502 during this pass. The archive
images were successfully downloaded and visually reviewed. They are proposed
plans, not accepted as-built geometry, and are insufficient to register reliable
height controls. The official dimensions provide global checks only.

Smiler needs the actual inversion sequence, both lift profiles, bank/roll
controls and a separate level for each branch at crossings. Oblivion needs a
station/lift datum, holding-brake location and a drop-shaft/underground exit
profile. A 180-foot total drop is not a 180-foot structure above terrain. These
rides' physical track and supports remain withheld until sufficient 3D controls
are available. The first pass intentionally exposes that missing evidence rather
than exporting a flat approximation that loses inversions or tunnels.
