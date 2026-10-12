# Source-linked paths and landscape section V10

V8 adds the 2017 drawing **373/95/7B** to the grounded V7 shop/terrain review.
The official PDF is pinned to SHA256
`1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`.
Existing paving uses complete visible legend-associated fills; new paving and
ground-cover beds use matching PDF tiling-pattern/image resources. Rock edges
match the explicit `New rock edges to match existing.` legend fill and shape.
Curved boundaries are flattened with the existing 0.2 PDF-point tolerance.

The retained alignment is a hypothesis fitted to the mapped shop and checked
against mapped track labels, using the checksum-pinned OSTN15 datum grid. It
is not an independent surveyed registration. All features are clipped to the
existing 142 × 149 m section. Every column occupied by the shop, roof or its
foundation is protected from landscape changes.

## Delivered geometry and materials

The section adds **3,924 overlay cells** from **30 paving areas, 12 planted
beds and 3 rock-edge shapes**. Overlapping source areas resolve into one final
cell/material per coordinate. Documented material classes are mapped to
Minecraft proxies when a material label lies inside the paving polygon. The
user-requested whole-polygon rule applies to existing and proposed paving: brick
beats stone/concrete; tarmac also beats stone/concrete. Brick wins if both brick
and tarmac occur. The deterministic order is brick, tarmac, gravel, concrete,
stone. Labels outside the polygon do not affect its material.

| Source association | Minecraft representation | Status |
| --- | --- | --- |
| Brick / brick paving inside existing paving | Brick blocks | Documented class; block appearance is a proxy |
| Tarmac inside existing paving | Black concrete | Documented class; block appearance is a proxy |
| Gravel inside existing paving | Gravel | Supported mapping; none emitted in this crop |
| Concrete inside paving | Light gray concrete | Documented class; color is a proxy |
| Stone inside paving | Stone | Documented class; block appearance is a proxy |
| No material label inside paving | Neutral stone | Material unconfirmed; review placeholder |
| Legend-bound planted beds | Dirt with low oak-leaf accents | Soil/species/height estimates |
| Legend-bound rock edges | One-block stone shapes | Rock type and height estimates |

This requested policy uses contained material labels for proposed paving too;
it does not establish current/as-built material accuracy. No raised planter walls are claimed: there is no independently bound
raised-planter outline in the inspected source. The planted areas remain beds.
Path heights follow the dated terrain; accepted design levels, smoothing,
entrance grading and step/ramp details still need separate review. The shop's
explicit review floor remains 184 m with estimated foundations.

```sh
python scripts/build_wicker_landscape_section.py \
  --base grounded-section --pdf 373-95-7B.pdf --osm osm.json \
  --grid uk_os_OSTN15_NTv2_OSGBtoETRS.tif --output landscape-section
```

The builder retains source extraction, alignment hypotheses, material outcomes,
clipped/missing/protected counts and BNG feature geometry. It uses the native
Bedrock exporter, which reopens the world and checks every written block and
unwritten air cell. Registration and physical identity remain unaccepted;
this review does not promote these candidates into an accepted park job.

`evidence/wicker-landscape-section-validation.json` records the real build and
native verification. Tests cover label containment, whole-polygon precedence,
annotation-order independence, valid native block IDs, clipping, shop-column
protection, missing terrain and above-ground rock/planting details.

## Direct import and visibility check

After an all-grass screenshot was reported, native checks found the V8 paving
present at the same height as terrain, with air above the checked cells. The
specific cause of the screenshot is unresolved; no Minecraft client session
was available to inspect the imported world.

V9 delivers `Wicker_V9_Paths_Plaza.mcworld` directly. Open the world named
**Wicker V9 PATHS — plaza spawn — provisional — draft 1:1**. Its spawn is on
a broad paving patch beside the shop at Minecraft **407553, 73, -343578**.
The source geometry and material associations are retained. Unknown material
areas remain neutral stone placeholders.

`scripts/verify_wicker_landscape_package.py` extracts and cold-reopens the
actual download, compares all 3,924 landscape cells with their expected native
blocks, checks air above 3,771 uncovered path cells, and checks the packaged
spawn over paving. The receipt is
`evidence/wicker-landscape-v9-package-validation.json`. This verifies archive
contents, not in-game appearance or the user's imported world.

The material policy was updated after the V9 download was generated. Existing
V9 validation receipts describe its original materials; the new policy applies
to subsequent builds.

## Missing polygon audit and V10

The straight-fill extractor omitted two source paving polygons containing
curves. Applying the existing bounded curve flattening before the same legend,
clip and hole checks recovers both: sequence 37 intersects this section by
21.63 square metres; sequence 38 lies outside it. V10 adds 22 tarmac blocks
from sequence 37 and removes no existing landscape coordinates. The whole
polygon material policy also changes 446 existing cells. There are now 31
emitted paving areas, 12 planted beds and three rock-edge shapes.

Nine source-bound grass polygons intersect the section. Existing terrain
already provides grass; three polygons overlap paving by a combined 39.90
square metres. These conflicts are recorded without erasing the paths.
The understorey legend has only small matching hatch fragments on the plan,
not a recoverable area boundary above the two-square-metre threshold. Printed
1:3 grading notes are retained as unresolved annotations; this build does not
invent their grading boundaries or design levels.

Import `Wicker_V10_Paths_Ground_Audit.mcworld`, named **Wicker V10 PATHS**.
The package checker confirms all 3,946 landscape cells, including air above
3,793 uncovered path cells. It also confirms paving beneath the plaza spawn.
`evidence/wicker-ground-detail-audit.json` records the source omissions and
remaining conflicts; `evidence/wicker-landscape-v10-package-validation.json`
records verification of the actual downloadable archive.
