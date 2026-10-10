# Station and pre-show 1:1 exterior review

V12 adds the station, lower pre-show gable and taller pre-show pyramid roof to
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

The pre-show uses its printed **183.30 metre** floor, snapped to grid 183.
The station shares this review base; its passenger floor is still unbound. Foundation fill
connects each ground-bearing column to the dated terrain; there is no inferred
excavation. The source's pre-show floor 183.30, inspection level 181.25 and
undercroft 178.00 remain separate claims. The inspection label is not promoted
to a passenger floor. This export does not reconstruct the basement, internal
layout, sandstone/earth bunding, entrance grading or exact surveyed floor registration.
Independent component snapping still requires circulation/interface review.

Existing shop blocks are collision-protected. Landscape cells in new building
columns are explicitly withheld, with their count retained. Taller walls win
shared component joins. All declared apertures are carved again after assembly,
preventing adjacent walls or decorative panels from obstructing them.

## Verification and reproduction

The native exporter verifies all written blocks and unwritten air cells. The
download itself is separately extracted and reopened by
`scripts/verify_wicker_station_package.py`: **1,940 building/access cells, 54 aperture
air cells and 389 bearing columns** pass. Roof overhangs do not require ground
contact. This is native block verification, not an in-game visual validation.
Five focused model/access tests and the full **791-test** suite pass. The receipt is
`evidence/wicker-station-section-validation.json`; reusable model assets are
`evidence/wicker-station-model.json`, `evidence/wicker-preshow_low-model.json`
and `evidence/wicker-preshow_tower-model.json`.

```sh
python scripts/build_wicker_station_section.py \
  --base landscape-v10 --terrain-base grounded-v7 \
  --sources preshow-and-basement-pdfs --retained roof-and-floor-pdfs \
  --floor 183.3 --output access-v12
python scripts/verify_wicker_station_package.py \
  --directory access-v12 --receipt station-package-validation.json
```

Import `Wicker_V12_Queue_Stairs.mcworld` and open **Wicker V12 QUEUE and STAIRS — access review**. The paved spawn beside the shop is retained.

## Access review and corrected source coordinates

PyMuPDF roof drawing strokes use an unrotated top-down frame. Pre-show
bounds are now converted with `y_up = 2384 - y_raw` before the rigid
registration; the V11 placement mistakenly used raw Y as architectural Y.
Raw and converted bounds are retained together, and a regression test checks
the conversion. Internal doorway sides follow the corrected low/tower order.

The station landing and two flights are traced from roof plan 2967-48.
Pre-show west queue access and southeast access use the corrected entrance
thresholds, with provisional 3 m widths and 7 m terrain connection runs.
These are five access features, not a reconstruction of the complete queue.
Oak slab/plank decks, side fence railings and stone bearing fill are proxies.
The actual export contains 80 access cells, including 15 slabs and six fence
cells. Slab flights replace overlapping landing cells to avoid overhead decks;
ends remain open and building collisions are excluded. At this 1:1 raster,
adjacent flight rises are 0.5 m, reaching 1 m on the rotated southeast flight.
A bounded voxel walkability check connects all 50 non-railing deck columns
through one surrounding-terrain component with two-block headroom and a
maximum one-block move. Exact riser layout, handrail specification and accessible ramps remain for
source binding and in-game review.
