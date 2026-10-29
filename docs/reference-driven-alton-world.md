# Reference-driven Alton Towers world rebuild

Earlier intakes registered annotations but did not feed the newest Wicker Man,
Galactica and monorail labels into world generation. The landscape exporter also
omitted steel ride geometry, allowing classified foliage to occupy those layouts.
The v3 rebuild connects the retained references to native ground and structure
layers instead of delivering another unchanged world.

## Geometry that now uses the references

- Paired red boundaries from the latest Wicker/Mutiny Bay and tight-path images
  supply explicit source-assisted paving polygons. Building/water masks and
  polygon holes exclude roofs, ponds, lawns and islands. Visible canopy does not
  erase an explicitly marked path. Shadowed material samples use visible paving
  from the same family. Existing ground levels are retained for these surfaces.
- Wicker queue strokes supply paved lane bands with railings outside the marked
  walking band. The 2.2 m band is a voxel-clearance estimate, not a measured width.
  Unmarked entrances and complete internal routing are not invented.
- Green sound-tunnel marks constrain a hollow acoustic-shell footprint. Local
  class-6 survey returns provide half-block roof estimates; walls preserve the
  existing independent track visits and their running clearances. Unsupported
  roof sections remain unbuilt instead of borrowing canopy heights.
- The blue Big Bob footprint selects actual observed elevated surface returns.
  Class-5 points are accepted only inside the marked object and within two metres
  of class-1/6 seeds. These become wood/fence surface voxels with single-cell
  vertical gap connections. This is a draft scan-based surface representation,
  not a verified finished sculpture or a solid footprint extrusion.
- Towers Street's confirmed barrier and rock-boundary traces become oak fences
  and half-block stone boundary proxies. Their previous image-local semantics
  remain separate from the newer purple queue and green tunnel classes.

The original narrow-stroke limit accidentally rejected most dense blue/purple
ink. Image-specific limits now retain the shaded Big Bob/queue guides: blue
candidates rise from 58 to 941 source pixels and purple from 89 to 1,193. Their
local colour windows still exclude screenshot borders and natural colour is
checked against separate clean imagery. No neural weights are retrained.

## Galactica, Nemesis, Smiler and monorail

`supported_ride_layouts.py` follows the current pinned OSM snapshot's node/way
topology, including unnamed Galactica station branches joined at internal source
nodes. XY crossings do not join networks. The monorail reconstruction covers the
main operating loop; depot yard/spur ways remain outside this layout draft.

Galactica uses a pale steel appearance, Nemesis Reborn red track/black supports,
Smiler black track/light supports, and the monorail a grey guideway. Actual block
materials, cross ties, support bents and bounded passage air are generated.
Misclassified foliage is excluded only in the mapped ride/guideway corridors.
Source roof and Wicker structure blocks remain intact.

Class-6 returns outside building footprints provide sparse candidate structural
height context. Vegetation never supplies a track-height target. Missing profile
information uses an explicitly provisional terrain-clearance prior. OSM layers
constrain relative crossing order, not measured metric elevations. Independent
crossing passes receive approximately six metres of vertical separation and
shared source nodes retain equal heights. Steel bents are estimates; a bent is
withheld if it collides with running air, another rail or retained structure.

Generic station-floor/roof models do not establish the true ride envelope.
Conflicting rail cells at roofs are withheld; the roofs are preserved. Profiles,
station transitions, banking and inversions are not surveyed ride models. No
trains or functional ride operation are generated or claimed.

## Build and inspect

The existing aligned-world inputs and surface layers are retained. The additional
checksum-pinned manifest names a literal source-assisted profile, registered
reference folders, classified survey crop and retained track samples:

```sh
python -m voxel_mapper.alton_aligned_world \
  --work RETAINED_ALTON_INPUTS --wicker RETAINED_WICKER \
  --surface-layers surface-layers.json \
  --reference-edits world-edits.json --output FRESH_OUTPUT
```

The source crop is `P_10682`, 5 January 2022, EPSG:27700/ODN; withheld and
synthetic flags are Boolean masks. Its archive/crop receipts and all source hashes
are retained. The pinned OSTN15 operation supplies one common BNG frame. Image
alignment and shared coordinates do not prove independent physical accuracy.

The download is `Alton-Towers-Reference-Rebuild-v3.mcworld`, with world title
**Alton Towers — reference update v3**, targeting Bedrock 1.21.130. It includes
inspection waypoints for the reconstructed layouts and Wicker features. The
bundle contains a before/after view computed from actual saved v2/v3 block data,
not an imagery overlay or a Minecraft client screenshot.

Fifty-one relevant tests cover source-local ink, thick marks, canopy paths,
walkable queues, retained track/roof protection, source-node branches versus XY
crossings, separate crossing heights and connected steep block segments, plus
existing native export/material/terrain/transport checks. All 9,100 new native
chunks are reopened and compared with the generated material/state arrays.
The delivered-world comparison additionally verifies every new role and passage,
retained Wicker blocks, unchanged generic roofs/water, changed paving and removed
foliage against the actual v2 archive. Exact counts are in the validation report.
No Minecraft client import test or independently surveyed fidelity claim is made.

Attribution: OpenStreetMap contributors, ODbL-1.0; Environment Agency information,
OGL-UK-3.0; Esri World Imagery/providers; user-provided guides; Staffordshire
Moorlands public planning documents. Source epochs differ, and one-metre voxel
quantisation cannot preserve every small detail.
