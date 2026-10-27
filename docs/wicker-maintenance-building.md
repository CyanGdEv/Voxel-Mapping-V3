# Maintenance building construction

This adds the missing maintenance building over its existing marked floor, preserving the aligned preshow, station, shop, queue and all retained terrain/structure records. The roof uses native oak top/bottom slabs, weathered timber is represented by spruce, and the lower bunding has a one-block sandstone display course.

The original proposed maintenance sheet **2967-42 P1**, [attachment 163939](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163939), supplies the plan, elevations and material notes. The source PDF and exact 1888 × 1334 render are checksum checked. The retained architectural review distinguishes its 22.273 × 12.202 m wall envelope from the **22.986 × 12.959 m** roof envelope on 2967-48. The already placed floor/wall outline is retained; centering the source roof span over that floor is a local display assembly hypothesis.

## Height references and openings

West elevation samples use the printed **inspection level 181.50** reference: datum pixel y=739, eave y=625 and ridge y=555. At the source scale, these imply conditional absolute eave **186.577 m** and ridge **189.694 m**. The existing floor walking top remains **184 m**, so the display roof heights above it are 2.577 and 5.694 m. The roof is not incorrectly raised from the inspection level as though it were the current floor. The ±2-pixel endpoint sampling bound gives ±0.178 m for a height difference; this is not total physical uncertainty.

Inspection level 181.50, maintenance maximum-level label 183.745, landscape FFL 183.25, comms level 184.00 and the conflicting exit-bridge labels remain separate source claims. The drawn floor slope and physical datum are not resolved by the flat display floor.

The source-plan end gaps receive two-block display clearance, with **26 native air cells** checked. The west plan gap is substantially wider than the opening depicted in the elevation, so its full traced width remains an explicit review gap rather than an accepted ride-door mechanism. The small service doorway aliases a retained station-wall cell at **(122,115)**; that wall is preserved and pedestrian approach generation is withheld for this doorway.

Thirty-three station/maintenance roof/wall material aliases preserve the existing station blocks. A native half-block occupancy flood checks the compound station/maintenance seam with declared portals temporarily sealed, excluding partial fences/trapdoors from full-cube assumptions. No original block is replaced to force the join.

## Validation and replay

The generator checks **317 maintenance floor columns**, retains all previous blocks, and validates the native roof/wall materials, current and prior portal air, written geometry and unchanged terrain. Archive CRC/file checks and cold reopen cover all **187 chunks**. Thirty-seven focused tests include datum conversion, slab closure, sandstone lower walls, retained station seam aliases, opt-in/cancellation and existing preshow/shop behavior. Minecraft import/gameplay remains untested; there is no new physical survey acceptance or accepted training data.

```sh
python -m voxel_mapper.maintenance_world \
  --base-directory aligned-preshow \
  --pdf-directory original-pdfs \
  --evidence-directory evidence \
  --shop-directory corrected-shop \
  --output fresh-maintenance-world \
  --allow-provisional
```

The profile pins the exact aligned-preshow world, voxel/report/portal records, original maintenance and roof PDFs, architectural outlines and corrected-shop placement context. The distinct level name is `Wicker MAINTENANCE BUILT - aligned park retained`. The original world archive is never overwritten. Detailed interiors, the communications annex, floor slope, bridge levels, service-door connection and ride mechanisms remain unfinished.
