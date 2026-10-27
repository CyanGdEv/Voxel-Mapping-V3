# Floor-led preshow, aligned basement and queue world

This conditional world applies the [basement correspondence](wicker-basement-alignment.md) to the scene. The preshow walls now follow the normalized upper-floor exterior extents. The lower gable and pyramid slab roofs are recentered over those walls, retaining their earlier source-plan spans and source-relative eave/ridge heights. Roof recentering is an assembly hypothesis; competing partial roof-source interpretations remain held. The corrected shop is preserved.

The lower preshow entrance now follows the original floor-plan gap between native points (1045.679, 1459.220) and (1091.278, 1459.220), rather than the middle of an estimated roof-derived wall. The shared preshow passage follows the floor-plan joint. A provisional connecting strip retains the station interface; its exact circulation dimensions remain unverified.

## Basement and queue

The aligned basement outer envelope replaces the old upper-derived undercroft footprint. Its floor walking top is **178 m** and its ceiling/deck walking top is **184 m**. The source outer envelope contains 151 centre cells; the conservative one-block exterior wall raster adds boundary columns, giving **185 floor/deck columns**. Horizontal wall thickness is a voxel display choice. Both source-visible wall gaps are carved with two blocks of headroom: **16 native air cells** are checked. Source opening heights, exterior lower approaches and internal stairs remain unresolved.

The larger basement ceiling supports the preshow and adjacent queue deck together. This retires the previous entrance flight that collided with the newly aligned basement. The source queue envelope uses its eight outer-edge strokes and three building-exterior closing sections, combined with the separate closed walkway. It covers about **87.02 m²**; its exact geometry is retained in the report.

At metre resolution, some source path cells alias the retained shop wall, facade or the preshow wall raster. These blocks are preserved and all **38 blocked centre cells** are recorded. The world generates **48 clear queue columns**; their entire set is checked for cardinal connection to the preshow and the new ground gate. The connector algorithm can add cells within 0.75 m of the source polygon; this scene needs none. This preserves source geometry and makes voxel limitations explicit; it does not claim full paving coverage or exact internal queue lanes.

The new estimated ground approach has **three walking columns** over 2 m, descending 184 → 183.5 → 183 m to retained paving. Native half-step surfaces and six headroom cells are checked. The source queue elevation remains unbound: tying its display deck to the preshow's rounded-up floor is provisional. Narrow queue edges use oak fences, with two rail gaps retained where existing objects prevent placement. One isolated non-queue clear upper-deck cell remains reported outside the connected circulation set.

Orange, blue and brown source guide cells within the excavated envelope keep their XY and materials in the lower floor. The report records their old and new display levels; these are plan guides, not measured track/support elevations. Other source edging displaced by the new architectural footprint has explicit original-column receipts. Terrain outside the new basement/station floor regions remains unchanged.

## Replay

Use the portable station inputs and the checksum-pinned alignment receipt:

```sh
python -m voxel_mapper.planning_station_preshow_world \
  --config alignment-request.json \
  --base-directory corrected-shop \
  --geographic-directory geographic-base \
  --pdf-directory original-pdfs \
  --evidence-directory evidence \
  --aligned-review alignment-review.json \
  --output fresh-aligned-world \
  --allow-provisional
```

The new level name is `Wicker ALIGNED PRESHOW - basement and queue deck`. Original archives are not overwritten. All source PDFs, the architectural review, corrected-shop input and geographic baseline remain checksum checked. The exact prior alignment receipt and its source implementation/profile pins are required; changed receipts fail before geometry generation.

Thirty-three focused tests cover lower gap carving, queue aliases, protected shop geometry, full queue circulation, rail placement, half-step ground connection, changed-receipt rejection, correspondence checks and prior shell/native slab behavior. Native readback additionally checks all generated queue surfaces/headroom, the lower gaps, compound portals, hollow undercroft, written structures and 39,250 terrain columns. Archive CRC/file-byte validation and cold reopen cover all 187 chunks. Independent archive extraction rechecks the 576 preserved shop blocks and 11 shop entrance landings. Minecraft import/gameplay and physical registration remain unverified; no accepted training labels are added.
