# Wicker finished-floor and path-step review

The current OSM/LiDAR world has a source-level and terrain-grade audit. It extracts three literal FFL annotations from the original, checksum-pinned landscape PDF, compares their containing source footprints with the exact DTM pixels, and locates abrupt steps between adjacent candidate path cells. No world blocks or grades are changed.

## Floor claims versus ground

| Source building | Printed proposed FFL | Raw DTM ground range, ODN m | Printed FFL minus raw terrain, m |
| --- | ---: | ---: | ---: |
| Maintenance | 183.25 | 180.807–183.110 | +0.140 to +2.443 |
| Shop | 182.50 | 180.514–182.848 | -0.348 to +1.986 |
| Station | 183.25 | 178.048–181.673 | +1.577 to +5.202 |

These are conditional comparisons: the plan's floor datum has not been independently tied to ODN, and the drawing is proposed rather than as-built evidence. Neither the text position nor polygon containment establishes a surveyed floor anchor. Cropped original-page views show each literal annotation for review; automated independent glyph/visibility verification is not claimed. Ride HP/LP values, upper theming limits and queue-below text are not treated as floor levels.

The audit retains raw pixel heights and rounded block heights separately. The station's preview ground blocks are 178–181 m, yielding a different conditional range (+2.25 to +5.25 m). Quantization must not be mistaken for the original measured terrain. The raised station-floor difference and shop's possible cut/fill requirement explain why simply draping building markers onto DTM ground is insufficient to reconstruct floors or foundations.

## Path steps

The review checks 8,143 candidate walkable cells and 14,430 orthogonal neighbour pairs. Of these, 13,736 are level, 677 differ by one block and **17 differ by two blocks**. All 17 hotspot pairs retain source cells, ground heights and BNG midpoint coordinates. No stairs, ramps or smoothing are invented.

Source paving, the identified queue floor, courtyard flooring and passage proposals supply candidate floor cells. Building/ride/assumed edging overlays are excluded. With at most a one-block step there are 32 local components, but these are not 32 verified pedestrian routes: source gaps, overlaid markers, missing stairs and unknown entrances also divide the cells. Playability, clearances and a complete park network remain unverified.

## Courtyard and nearby building

The existing ground-plan study encloses 964.450 m²; the separately hash-checked existing roof/eaves study encloses 971.350 m², a 0.715% nominal difference. The OSM inner polygon encloses 861.467 m². The ground-plan area is 11.954% larger than OSM; equivalently OSM is 10.678% smaller than the ground-plan area. Percentage bases are explicit.

Roof/eaves and floor/wall outlines represent different physical edges. Their similar nominal size is useful corroboration, not proof of shared-edge identity or independent geographic registration. The source courtyard is not shrunk to remove the OSM discrepancy. Its existing manual trace, pose and canopy uncertainties remain.

The nearby source building/OSM footprint comparison remains unverified in identity and extent. A low IoU alone does not establish an erroneous planning footprint or justify changing it to match a differently dated mapped outline.

## Reproduction

With the delivered portable review pack and the repository installed:

```sh
python -m voxel_mapper.planning_surface_audit \
  --config alignment-request.json --world-directory world \
  --pdf originals/wicker-landscape.pdf \
  --roof-pdf originals/courtyard-existing-roof.pdf \
  --output a-new-floor-and-path-review
```

The checker revalidates all six planning input pins and geographic assets, recomputes the rigid fit, resamples all terrain heights and compares them with saved values. It checks the saved world hash and geographic implementation/profile pins. The original roof PDF is checked by the existing native-corner review. It refuses output overwrite, altered originals, missing coverage, changed world bytes and incompatible geographic implementations. The local path graph is bounded to 65,536 cells; hotspot reports cap at 10,000 records and fail instead of truncating. No Minecraft client or new native world export is involved in this read-only audit.

Ten source-level, terrain-step and geographic regression tests pass, covering literal FFL extraction, source hash rejection, separation of raw/rounded heights, incomplete coverage, correct path-role exclusions, cancellation, two-block component separation and changed-world rejection. The real retained-input run finds the three floor claims and 17 hotspots while keeping the current world hash unchanged.

Next work is verifying the project level datum, reviewing the 17 hotspots against detailed step/ramp/spot-level evidence, then modelling separate building floor plates and supports. Those evidence gaps remain explicit; neither a proposed floor claim nor an OSM fit silently authorizes finished grading.
