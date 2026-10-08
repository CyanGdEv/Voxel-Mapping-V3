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
  --include-oblivion \
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
profile. A 180-foot total drop is not a 180-foot structure above terrain. Smiler's physical track and supports remain withheld until sufficient 3D controls
are available. Oblivion's visible preview is explicitly estimated; it does not
satisfy verified planning acceptance. The first pass intentionally exposes that missing evidence rather
than exporting a flat approximation that loses inversions or tunnels.

## Visible Oblivion preview

`--include-oblivion` emits rails, spine, cross ties, lift chain/walkway and generic
vertical supports along the mapped closed route. The covered station and tunnel
ways identify phase boundaries; the longest outgoing straight is an explicit
lift hypothesis. The estimated station rail is three metres above the median
ground slab. The crest rises 65 feet (19.812 m) and the total drop is 180 feet
(54.864 m), including the underground portion. Exact ODN levels, bank, slope
transitions, lift boundary and support/tunnel sections remain estimates. A closed
monotone cubic profile preserves those controls without overshoot. Adaptive
sampling limits horizontal travel and vertical rise to 0.2 m so the steep drop
does not disappear between horizontally spaced samples.

Explicit train clearance cuts station portals and excavates an estimated six
metre tunnel section. Physical rail wins over its own void. The preview does not
include trains, ride operation or a detailed architectural facade. Spawn moves
to an aerial X-Sector viewpoint and is checked after export. Bedrock may omit
all-air sections; verification compares all cells across the union of section
indices rather than requiring identical storage keys.

### Return-height correction

The first preview mistakenly interpolated the tunnel exit directly toward the
station, flattening the elevated return turn. A reviewed historical as-built
photograph (`https://themeparkreview.com/alton/obliv2.jpg`) provides qualitative
shape evidence. The return now rises to a separate peak, falls into a dip and
climbs into level brakes before the station. Phase boundaries use the first
return way and following mapped straight. Peak is estimated eight metres above
station rail; dip is estimated five metres below it. Smooth roll reaches an
estimated 80-degree left bank at the return peak and returns to zero by the dip.
Rails, spine and ties use a pitch-aware rotated frame; the centreline and
clearance retain their own geometry. These are explicit shape corrections, not
photogrammetrically measured heights or angles. Rebuild from the station-only
base so the old low track and excavation do not remain as ghost geometry.

### One-block track requirement

The current Oblivion export uses the user's requested one-block-wide centreline.
No accepted application width overrides this requirement. Paired gauge rails,
offset spine, cross ties and lift walkway are omitted, rather than widening the
track with guessed dimensions. The chain marker occupies the same centreline
cells; support columns terminate directly beneath it. Height and roll profiles
are retained, but a single square voxel cannot visibly express rail banking.
Tunnel/train clearance is an excavation envelope, not the physical track width.
Rebuild from the station-only base to replace the earlier wide track completely.
