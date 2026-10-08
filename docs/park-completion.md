# Transport and landmark geometry preview (V7)

This pass builds on the verified V6 world. It targets omitted transport and
barrier routes, the Pagoda, main entrance, Towers exterior and the Wicker Man
terrain/track conflict. It is a geometry preview, not a complete accurate park.

| Component | Current reconstruction | Still unresolved |
| --- | --- | --- |
| Wicker Man | Retained route/height controls; bounded terrain clearance; oak centre deck, spruce edges/slabs; fence bents and braces, trapdoor details | Actual structural brace angles, surveyed grading and detailed bent design |
| Sound tunnel | Existing footprint/height retained; timber skin, fence frames, trapdoor bands and slab roof | Section dimensions and acoustic construction detail |
| Skyride | Two retained OSM cable ways; iron bars and provisional vertex supports | Actual pylon locations, surveyed cable heights/sag, gondolas and station interiors |
| Monorail | Fourteen retained OSM ways including branches; connected wall beam and estimated piers inside current world extent | Exact beam profile, station levels and measured pier spacing |
| Barriers | Sixty-two mapped fence/wall/retaining-wall/gate/turnstile ways | Material and height unless specified; unrecorded routes |
| Pagoda | Mapped octagonal footprint; three open stages, tiered canopies, stair edges, five half-block step rises and finial | Exact dimensions, painted iron detailing, fountain effects and architectural roof curves |
| Main entrance | Mapped roof footprint, open canopy and posts; six-metre maximum preview height | Ticket booths, exact openings, facade details and canopy elevation |
| Towers ruins | Hollow mapped perimeter with locally sampled exterior wall profile instead of a solid extrusion/flat roof | Interior walls, actual towers/turrets, arches, windows, crenellations and room subdivisions |
| Rocks | V6 reviewed rock geometry retained | More usable individual footprints required; ambiguous rockery faces remain excluded |

The official Pagoda listing establishes octagonal form, three open stages,
five steps and the roof/finial features. Source:
https://historicengland.org.uk/listing/the-list/list-entry/1192054
The Towers architectural listing is retained as context, not positioned CAD:
https://historicengland.org.uk/listing/the-list/list-entry/1374685

Five retained Wicker application pages were checked for support/section text.
They identify supports but provide no bound 3D brace-angle section. Estimated
brace angles (45–63.4 degrees) are explicitly recorded rather than presented as
planning measurements. Dark timber remains the tunnel skin; partial blocks
supply framing/detail rather than replacing the whole enclosure with open fence.

Only exact old Wicker component cells matching their expected material may be
removed. Terrain cuts are restricted to the approximately three-metre track
corridor and natural ground block types. Track heights are not raised to hide
terrain conflicts. The 1,279 emitted oak centre-deck cells have no terrain
immediately above them in the exported world. This check is not a complete
ride envelope or engineering clearance certification.

Landmark footprint masks intentionally hollow prior generic extrusions; other
transport/barrier additions only occupy air. All 245 V6 detail cells retain their
previous materials. Transport and barrier lines include intermediate cells at
diagonal joins; monorail wall blocks retain explicit connection states. Partial
blocks translate to native Bedrock identifiers and pass world readback.

The verified export changes 64,921 cells, including 45,412 air/clearance cells
and 19,509 physical partial/full blocks. Solid delta is +1,198 rather than the
number of additions because old landmark/ride shells and terrain are removed.
Every cell of touched chunk sections and total chunk coverage passes Bedrock
readback across 383 chunks. All 311 tests pass.

```bash
python -m voxel_mapper.park_completion \
  --source /absolute/path/verified-v6-world \
  --park /absolute/path/alton-full-park \
  --raw-osm /absolute/path/osm-raw.json \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/new-v7-output
```

The preview is rendered from reopened world blocks with simplified silhouettes
for partial blocks; it is not an in-game screenshot. Absolute registration,
historical source dates and non-surveyed dimensions remain provisional.

## V8: above-terrain correction

V7 cleared a narrow trench while leaving some rail heights below surrounding
terrain. Its exported-record check also missed samples where a deck block was
rejected or replaced. V8 supersedes that clearance policy.

The generator samples the original terrain over a five-metre lateral envelope
at every 0.4 m route station. A nonnegative periodic correction keeps the deck
at least two whole blocks above the original terrain envelope. The correction
ramps at no more than 0.12 m per metre into adjoining spans. Maximum uplift is
seven metres. These are corrected preview heights; original planning controls
that move are not presented as measured ride heights. Tunnel shells follow the
corrected local profile, and the oak centre deck wins over generated supports,
walkways and sound-screen blocks at the same cell.

The generator reopens the exported world and checks all 1,949 intended route
samples, rather than a subset of successfully emitted records. All 957 unique
centre-deck cells contain oak planks; minimum clearance above the original
terrain envelope is two blocks, with no natural terrain immediately above the
deck. This is a terrain/deck check, not a complete rolling-stock clearance or
architectural collision audit. All 245 V6 detail blocks remain unchanged.

The full touched-section/chunk-coverage check passes across 383 chunks. All
314 tests pass. Validation: `evidence/wicker-clearance-v8-validation.json`.
The imported world is labelled “Wicker track clearance V8” to distinguish it
from previous exports.
