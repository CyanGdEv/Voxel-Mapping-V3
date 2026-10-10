# Proposed shop wall and opening trace

The revised floor-plan drawing 2967-21 now has a reproducible main external-wall
trace. Four manually reviewed outer corners and three opening pairs are pinned
to the complete rendered pixel hash and PDF checksum. The script converts them
to native PDF coordinates and local metres using the printed 1:100 scale. It
projects each opening onto its wall, records the projection residual, and splits
the perimeter into seven uninterrupted wall segments. This is a local source
trace, not an accepted as-built footprint.

The two broad dashed openings measure approximately 4.54 m and 4.57 m; their
exact door mechanisms are unverified. The small door-swing opening measures
approximately 0.82 m. Heights are unset. Interior partitions, the small corner
internal lobby arrangement and door swing arcs are not external wall segments.
The sheet explicitly labels internal layout illustrative.

## Conflict that prevents joining the roof and walls

| Check | Floor trace | Elevation trace |
| --- | ---: | ---: |
| Main external length | 14.38 m | 15.90 m |
| Main external width | 10.76 m | 11.81 m |
| Apparent external area | approximately 155 m² | approximately 188 m² wall-span rectangle |

The floor dimensions differ from the elevation wall spans by approximately
1.53 m and 1.05 m. The floor's apparent outer area is below the labelled 170 m²
GIA, even after buffering by its explicit endpoint sampling bound. A genuine
external footprint should not be smaller than its own internal area. These
checks identify inconsistent source interpretation, scaling or design scope;
they do not establish which explanation is correct. No scale correction or
roof-to-wall fit is automatically applied. The elevation mesh remains provisional
and its dimensions cannot yet be promoted to a complete shop model.

The floor endpoints have ±2 pixel coordinate sampling bounds (approximately
0.126 m radial bound per endpoint). This only describes manual sampling, not
source or physical accuracy. The observed discrepancies exceed those bounds.
The outer-corner trace deliberately follows the main rectangular wall face;
opening endpoints follow the same outer face rather than the inner wall face.

## Reproduce

```sh
python scripts/trace_wicker_shop_floor.py \
  --pdf revised-floor-plan.pdf \
  --annotations evidence/wicker-shop-floor-annotations.json \
  --roof evidence/wicker-shop-local-roof.json \
  --output local-floor.json
```

Retained records are `wicker-shop-floor-annotations.json`,
`wicker-shop-local-floor.json` and `wicker-shop-local-floor-validation.json`.
Validation checks deterministic replay, conservation of each edge's solid and
open lengths, rejection of invalid or overlapping openings, source integrity,
and detection of both cross-sheet and area-label conflicts. No wall height,
Minecraft block material or world registration is assigned; zero world geometry
is placed.

Next: investigate sheet/view scaling and revisions using original drawing
linework and additional dated architectural attachments. Resolve the dimensional
conflict before combining walls and roof or treating either as physical controls.
