# Forbidden Valley V20 planning draft

V20 continues the exact V19 Garden Bridges package. It retains 18 checksum-verified planning PDFs for Project Ocean, the Nemesis retail extension, Edge arcade and Nemesis maintenance, with existing/proposed state, source URLs and native-sheet revision notes. This is a partial planning draft, not a claim of surveyed placement or current construction.

## Applied world changes

The reviewed Ocean P0.5 queue mask contributes 153 safe full-block surface columns; 27 obstructed columns are protected. Existing paving can already match these surface materials. Seven of nine reviewed rockwork profiles contribute 20 new blocks. Two profiles are withheld for occupied cells or insufficient voxel coverage. Complete queue connectivity is not established.

Rock generation combines full cores, slab ledges, inward stair facets and grounded wall tips. Jagged stone/cobblestone, layered sandstone and weathered granite recipes are available. Footprints, heights and ground samples are bounded; wall tips have full supports. These recipes express visual rock types, not verified lithology. Ocean uses an explicitly estimated two-metre jagged recipe because its generic rockwork label gives no type or height.

The Ocean sheet's repeated stair geometry relates its ground and first-floor panels by a displayed PDF x shift of 779.88 points. Printed 1:100 scale is retained. Placement uses the mapped ride centroid/orientation and an approximate coffee-outpost context check (4.785 m residual). A stretching shape fit is rejected. This tolerance does not establish survey accuracy. The raster queue mask retains annotation knockouts and measures 174.77 m² versus the approximate printed 205 m²; it is not treated as a complete exact CAD boundary.

## Retained components awaiting placement

The retail footprint measures approximately 16.65 × 10.20 m and 139.05 m², matching the written 16.7 × 10.2 m and 139.1 m². Its reported ridge/eaves heights are 4.1/3.5 m. Arcade dimensions and the reported 5.7 m height are retained in a separate local drawing frame. Both specify insulated profiled metal panels; unspecified colours remain unspecified. The arcade catalogue says P0.3 but the native reviewed sheet says Option 2 / P0.2, so it is not claimed as the latest revision.

Building geography, Ocean deck elevation/mechanism, underpass clearance, fence routes and the unbounded resurfacing extent are not emitted. Nemesis plan evidence lacks rail heights, banking, inversions and support geometry needed for 3D track construction. Galactica is retained as mapped layout/underpass context. Each gate is explicit in the inventory rather than creating speculative buildings or track.

## Reproduction and verification

```bash
python -m voxel_mapper.forbidden_valley --planning-cache CACHE --output INVENTORY
python -m voxel_mapper.forbidden_valley --planning-cache CACHE \
  --source-output V19_OUTPUT --osm park-osm.json --estimated-placement --output V20_OUTPUT
```

CACHE contains the 18 PDFs named by catalogue SHA256. V19_OUTPUT contains `bedrock-world`, `quality-report.json` and `park.mcworld`. The draft output requires explicit estimated placement. Source checksum/revision/geometry guards fail before writing if the reviewed source changes.

All cells of eight touched native chunk sections and total chunk coverage were verified after reopening. V19's four garden bridges also passed the required native support, headroom and connectivity check before packaging. Fourteen relevant tests pass. The full suite has 411 passes out of 415; the same three drawing-coordinate failures and one error were present before this work. Native verification does not substitute for an in-game visual or player movement review. See `evidence/forbidden-valley-v20-validation.json` for source hashes, scope, materials, package hash and checks.
