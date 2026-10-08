# Evidence-backed foliage

`voxel_mapper.foliage` provides deterministic, connected tree skeletons and lobed
crowns independently of any park. The reconstruction registry exposes `tree`
and `shrub` families with explicit dimensions and the existing provenance and
collision rules. Oak, birch, spruce and dark-oak fences form thin trunks and
face-connected branch skeletons, rather than vanilla full-block log trunks.
Crowns combine asymmetric lobes with two scales of seeded smooth 3-D noise,
bounded by the supplied radius and height. Leaves persist without random decay.
Ferns, grass and azalea blocks provide
understorey proxies.

`python -m voxel_mapper.park_foliage` overlays a retained Bedrock world using
mapped tree nodes, woodland/scrub geometry, DTM and DSM, and optionally an
explicitly georeferenced classified vegetation cloud. It does not rerun rides,
terrain or paving. All inputs use the retained world CRS and vertical datum.
The vegetation-cloud metadata must declare the matching vertical datum and
SHA-256; EPSG:27700 is checked in the cloud header. Withheld and synthetic points
are excluded. Input points, accepted trees and emitted voxels have hard budgets.

```sh
python -m voxel_mapper.park_foliage \
  --source park-water-v11 \
  --osm recovery/park-osm.json \
  --tree-nodes recovery/tree-nodes.json \
  --surface recovery/alton-surface-mosaic.tif \
  --boundary recovery/boundary-local.json \
  --datum-grid recovery/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --clearance recovery/Alton_Towers_Wicker_Trestles_V9_Evidence/rider-envelope.json \
  --planning-hints recovery/foliage-planning-hints.json \
  --vegetation-cloud recovery/park-classified-vegetation.laz \
  --vegetation-cloud-report recovery/park-vegetation-acquisition.json \
  --output park-foliage-v12-final
```

The Alton Towers pass uses 105 mapped tree positions, about 35 hectares of
mapped woodland, and 3,758,713 classified vegetation returns from Environment
Agency survey P_10682 (5 January 2022, tile SK0540). The retained clipped cloud
has SHA-256 `8c2f130d270f514c8d9fca9f1a1a1766e54318a444dc13bc614a7dfc223e88ae`.
The acquisition report retains source URLs, survey identity, OGL licence,
class counts, clipping bounds and the archive checksum. Downloaded archive ZIP
timestamps vary, so survey identity and validated point metadata are retained
alongside the byte checksum.

Eight-metre high-vegetation clusters provide estimated canopy centres and a
90th-percentile height above DTM. These are not surveyed stems. Canopies require
classified vegetation support where that source covers the candidate. DSM-only
forest candidates require an observed surface envelope. Sparse ground cover and
shrub shapes are estimates. Named OSM species select silhouette proxies; nearby
planning labels are provisional palette hints, never confirmed tree identities.
The resulting scene represents summer foliage, while survey dates vary.

Roots require actual grass/dirt in the retained world. Buildings, transport
corridors and low path clearance are excluded. The explicit rider envelope is
protected. A woody collision withholds the whole tree; branches are not cut into
floating fragments. Existing small tree previews are replaced only when roots,
vertical logs and adjacent leaves establish that they are trees. Crown overlaps
preserve fence branches. Preview cleanup cannot erase previously composed
neighbouring skeletons or crowns. Water, beds, terrain and architectural blocks
cannot be replaced.

Outputs contain the native world and `.mcworld`, an emitted overlay, per-tree
position/height methods, input hashes, withheld reasons and full changed-section
readback. Native palette, connected skeleton, deterministic shape, modular
evidence/collision behaviour and retained-world clearance tests are in
`tests/test_foliage.py`.
