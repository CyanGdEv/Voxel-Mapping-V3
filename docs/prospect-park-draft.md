Prospect Tower is now placed in the full Alton Towers V17 baseline at 1 block
per metre. The V18 package replaces 462 stone-brick placeholder cells with the
280-cell component model, restores exposed ground, adds platform footings and
a short connected sandstone approach. The overlay contains 608 cells across
two chunks; no foliage cells were pruned.

The anchor is explicitly estimated at British National Grid
(407744.2079, 343322.4628), using the north-up AL3.42 location drawing and the
retained OSM Skyride station centroid. It has no independent checkpoint
validation. The base is estimated at 183 m ODN, aligned to the adjacent native
garden path walking level. These estimates do not promote the drawing to an
accepted geographic survey. Relative component profiles retain their own local
paper registration and the limitations in `prospect-study.md`.

The generic replacement composer is separate from architectural generators.
It removes only reviewed placeholder material above original terrain within
the selected footprint; other solids, barriers, trunks and water cause a
refusal. New geometry below terrain is rejected. Platform foundations are
explicit cells, and the approach is an inferred level link rather than a
traced planning polygon.

Reproduce with `scripts/place_prospect_draft.py --source V17_DIRECTORY
--output NEW_DIRECTORY --osm park-osm.json --grid OSTN15.tif`. The source must
contain `bedrock-world`, `park.mcworld`, `quality-report.json` and
`resolved-config.json`. The package hash is pinned to the reviewed V17 world;
the retained datum grid is hash checked. Sandstone now uses its explicit
normal variant so strict Bedrock readback compares equivalent block states.

Every cell in changed chunk sections and total chunk coverage passed native
readback. The remaining 4,755 chunks are copied from V17. A separate native
check verified that the level approach reaches the platform through cardinally
adjacent cells, with two blocks of route headroom and clear spawn cells.
Spawn is Minecraft (-190, 146, 114). There is no in-game visual fidelity check;
one-metre voxels still merge fine columns, arches and internal stair detail.

See `evidence/prospect-park-v18-validation.json` for the package checksum,
composition counts and validation scope.
