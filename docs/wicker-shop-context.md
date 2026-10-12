# Separate entrance observations and mapped orientation context

A current indexed AccessAble shop guide supplies first-hand access observations:
[Wicker Man Shop](https://www.accessable.co.uk/alton-towers-resort/access-guides/wicker-man-shop).
It describes a 3 m front opening, with no doors or protective canopy at that
entrance, and rear ride-to-shop access through steps and a platform lift. The
page's survey date was not obtained; retrieval on 10 October 2026 is not a survey
date. Direct requests returned 403, so source access in this pass was indexed
text, not photographs. No dated aerial photograph was acquired.

The front observation does not refute a proposed rear canopy. Conversely it
does not corroborate that canopy. The observed front opening differs from the
approximately 5 m proposed broad openings, so planning profiles remain proposed
rather than current/as-built dimensions. No opening is automatically resized
because its physical plan-to-observed identity has not been established.

## Orientation preference

The retained OSM dataset contains the named shop way 834919978 and nearby
unnamed station-complex relation 17436869. The latter comprises three mapped
outer building polygons and carries a roller-coaster station tag. Their union
centroid is used as contextual direction, not a surveyed corner or positively
identified Wicker Man attachment point. Datum conversion uses the checksum-pinned
OSTN15 grid and the best available metre-accuracy BNG transform.

For the stable 505-return roof envelope, one rear/canopy direction lies about
16.72 degrees from the mapped station-complex direction; its reversed hypothesis
lies about 163.28 degrees away. The first is context-preferred because it faces
toward the mapped ride buildings, consistent with rear ride access. This narrows
which orientation to investigate; it does not accept a registration or prove
that the canopy was constructed. The expanded envelope's paired context rankings
are retained as well, with its poor boundary agreement unchanged.

OSM already seeded the roof comparison; these mapped features are not separately
sourced independent geographic checkpoints. The access guide supplies topology
and dimensions but no usable georeferenced physical control coordinate.
Independent controls/checkpoints and canopy identity remain unresolved.

```sh
python scripts/review_wicker_shop_context.py \
  --osm park-osm.json --grid uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --lidar-review evidence/wicker-shop-model-lidar-review.json \
  --output context-review.json
```

The report retains both directional scores, mapped station-complex geometry,
input hashes, access-guide URL, access limitations and uncertainty. Validation
checks replay, complementary opposite-direction angles, rejection of a corrupt
datum grid and retention of zero accepted controls/checkpoints/world geometry.
The existing model, openings and registration gates are unchanged.

Next: acquire independently dated/georeferenced imagery or a physical survey
that identifies the rear structure and supplies actual control/check coordinates.
Use the preferred orientation only as a provisional candidate while doing so.
