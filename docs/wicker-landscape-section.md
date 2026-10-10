# Source-linked paths and landscape section V8

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
Minecraft proxies only when a material label lies inside an **existing** paving
polygon and no competing material class is present.

| Source association | Minecraft representation | Status |
| --- | --- | --- |
| Brick / brick paving inside existing paving | Brick blocks | Documented class; block appearance is a proxy |
| Tarmac inside existing paving | Black concrete | Documented class; block appearance is a proxy |
| Gravel inside existing paving | Gravel | Supported mapping; none emitted in this crop |
| Unlabelled, conflicting or proposed paving | Neutral stone | Material unconfirmed; review placeholder |
| Legend-bound planted beds | Dirt with low oak-leaf accents | Soil/species/height estimates |
| Legend-bound rock edges | One-block stone shapes | Rock type and height estimates |

The old survey material labels are never inherited by proposed replacement
paving. No raised planter walls are claimed: there is no independently bound
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
native verification. Tests cover label containment/conflicts, refusal to inherit
old materials into new proposals, valid native block IDs, clipping, shop-column
protection, missing terrain and above-ground rock/planting details.
