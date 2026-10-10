# Station and pre-show 1:1 exterior review

V11 adds the station, lower pre-show gable and taller pre-show pyramid roof to
the V10 shop, paths and terrain section. It uses the same source-mesh rotation,
half-metre slab sampling, wall closure, fence/trapdoor detailing and terrain-bearing
foundation functions as the shop. Native world scale remains one block per metre.

## Source and geometry

The revised 2016 P1 sources are checksum-pinned: roof plan 2967-48, overall
ground floor 2967-21, basement 2967-22 and pre-show elevations 2967-30.
The retained station roof rectangle is 9.218 × 17.952 metres. The two pre-show
roof rectangles are replayed from the native 2967-48 boundary segments. Eave
and ridge heights are rounded first-review estimates informed by elevations;
the four-decimetre wall inset and aperture sizes are illustrative.

Placement selects the retained drawing correspondence with station-plan IoU
0.986, verifies a rigid rotation without scale/reflection, then reanchors it to
the provisional shop roof centre. This remains a hypothesis: zero accepted
independent controls or checkpoints. The models are compatible with the normal
`local_building` adapter; its registration and identity acceptance gates remain.
An optional validated roof palette lets that adapter and this review use the
same oak full-block/top-slab/bottom-slab proxies for thatch-effect tiles.

## Floors and missing construction

The explicitly chosen exterior review base is **185 metres**. Foundation fill
connects each ground-bearing column to the dated terrain; there is no inferred
excavation. The source's pre-show floor 183.30, inspection level 181.25 and
undercroft 178.00 remain separate claims. The inspection label is not promoted
to a passenger floor. This export does not reconstruct the basement, internal
layout, sandstone/earth bunding, entrance grading or exact floor registration.
Independent component snapping still requires circulation/interface review.

Existing shop blocks are collision-protected. Landscape cells in new building
columns are explicitly withheld, with their count retained. Taller walls win
shared component joins. All declared apertures are carved again after assembly,
preventing adjacent walls or decorative panels from obstructing them.

## Verification and reproduction

The native exporter verifies all written blocks and unwritten air cells. The
download itself is separately extracted and reopened by
`scripts/verify_wicker_station_package.py`: **2,556 building cells, 42 aperture
air cells and 330 bearing columns** pass. Roof overhangs do not require ground
contact. This is native block verification, not an in-game visual validation.
The full test suite passes **788 tests**. The receipt is
`evidence/wicker-station-section-validation.json`; reusable model assets are
`evidence/wicker-station-model.json`, `evidence/wicker-preshow_low-model.json`
and `evidence/wicker-preshow_tower-model.json`.

```sh
python scripts/build_wicker_station_section.py \
  --base landscape-v10 --terrain-base grounded-v7 \
  --sources preshow-and-basement-pdfs --retained roof-and-floor-pdfs \
  --floor 185 --output station-v11
python scripts/verify_wicker_station_package.py \
  --directory station-v11 --receipt station-package-validation.json
```

Import `Wicker_V11_Station_Preshow.mcworld` and open **Wicker V11 STATION and
PRESHOW — exterior review**. The paved spawn beside the shop is retained.
