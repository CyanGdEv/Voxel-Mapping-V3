# Heritage discovery for park reconstruction

The NHLE adapter acquires official Historic England listed-building point and polygon layers in British National Grid (EPSG:27700). It discovers named assets without generating blocks. It rejects truncated responses, API errors, unexpected coordinate systems, duplicate list identities, malformed points and queries above 25 km² or 1,000 records per layer. Failed second-layer requests produce no accepted partial inventory.

## Alton Towers snapshot

Retrieved 9 October 2026. The initial 3 km × 3 km query returned 106 records per layer. Listing locations intersecting the retained park boundary select **31 list entries**. This is a discovery transform, not accepted plan registration. Each list entry may cover several structures. The retained point and polygon responses are in `voxel_mapper/data/alton-heritage-source.json`; the normalized inventory and input SHA-256 are in `alton-heritage-inventory.json`.

New Alton park runs include these candidates in `reconstruction-source-inventory.json`, write a separate `heritage-inventory.json`, and disclose the snapshot date and attribution in the acquisition manifest. This does not silently claim the snapshot is live data. Other parks can use the bounded CLI or an explicit `nhle` feed.

Useful reconstruction targets include:

| Listing | Targets |
| --- | --- |
| 1192054 | Pagoda Fountain and bridge pier |
| 1192015 | Prospect Tower, wall and railings |
| 1037876 | Loggia terrace retaining wall, steps and piers |
| 1286814 | Terraced garden walls, gate piers and steps |
| 1037875 | Fountain, terrace walls, steps, lions, urns and sundial |
| 1037872 | Boating lake dam retaining wall |
| 1037884 | Historic principal entrance gate piers, gates and railings |
| 1374685 | Towers, attached garden walls and gatehouse |

The historic principal entrance is not automatically the current theme park visitor entrance. Match identities and present-day condition before constructing it.

## Geometry limits

The Prospect Tower polygon is a three-vertex triangular location symbol, approximately 2.5 m wide. It is not its physical footprint. The adapter identifies triangular rings as marker candidates, and keeps all other listing polygons unreviewed. Neither kind is extruded, even if the feed's registration flag is accepted. This avoids replacing an absent structure with an invented box. Plans, independent registration controls, vertical profiles and material evidence still supply the physical geometry.

Historic England's [terms](https://historicengland.org.uk/terms/website-terms-conditions/open-data-hub/) state that spatial data indicates location and describe differences between listing boundaries. Its [official API catalogue](https://www.api.gov.uk/he/national-heritage-list-for-england-nhle/) links the service.

## Usage

```bash
voxel-heritage --bounds 406000 342000 409000 345000 --output nhle-query
voxel-heritage --bounds 406000 342000 409000 345000 \
  --retained-input voxel_mapper/data/alton-heritage-source.json --output nhle-replay
```

Optionally pass `--boundary` with a Polygon/MultiPolygon geometry JSON and `--boundary-crs` to filter listing locations, including holes. Bounded live queries outside England normally return no candidates; they do not establish absence of physical assets. Feed reports carry discovery decisions; the `nhle` feed supplies zero reconstruction features.

© Historic England 2026. Contains Ordnance Survey data © Crown copyright and database right 2026. OGL v3. Historic England does not endorse this reconstruction. Snapshot data was obtained on 9 October 2026; obtain current data through the official Open Data Hub.
