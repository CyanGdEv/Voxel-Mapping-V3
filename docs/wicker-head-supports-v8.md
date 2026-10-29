# Wicker head shape, facing direction and support foliage

The user's v7 screenshots exposed two remaining problems: the opposing faces
read as a large rectangular mask, and source foliage still obscured some support
members well below the track. The additional real photograph and marked plaza
position provide a facing anchor for this revision.

## Head geometry and pose

The human face points southwest toward the marked plaza approach; the ram face
points northeast on its reverse. This is a 90-degree head yaw change relative to
v7. The torso, track and brown-footing registration frames are retained. The head
centre is E407554.45, N343550.15, within 0.1 m of the mean of the 69 dated LiDAR
returns above 193 m in the identified head context. The old centre was
E407554.10, N343550.20. Source point positions are not moved. This small centre
adjustment and the change in facing direction have different purposes; the
photographs do not provide a calibrated camera or an independently surveyed yaw.

The v4 profile selects an independently posed head and neck. Elliptical skull
sections, a projecting downward muzzle, an inclined human jaw/nose and actual
eye/mouth recesses replace the old broad mask. Native block octants choose slabs,
upper/lower stairs and full timber, reducing protruding corners around the crown
and cheeks. Horn curves are sampled as tubes; narrow timber ties join native
corner crossings while both curl centres remain open. A new collar follows the
neck, rather than leaving corners of the previous collar suspended beside it.
The source-assisted overall 179–196.5 m ODN envelope remains.

The supplied Minecraft close-ups guide blockwork. The user's real human-face
photograph and marked path anchor the visible side. Full-size resort photographs
and the official miniature provide opposing-face and curl context. The resort's
[creative lead describes](https://www.altontowers.com/about-alton-towers/blog/wicker-man-what-s-it-all-about/)
an upward-looking human face and a downward-looking ram on the reverse. The
miniature is a secondary feature reference, not a scale survey. Facial features,
hidden surfaces and weave remain inferred; the dated upper returns constrain
placement and height without establishing a complete head surface.

The three track visits, all retained Wicker track/support/building cells, printed
height controls and v7 crossing estimate remain unchanged. The verifier checks
actual native riding clearance at all three visits and ceilings at all six
portals. The earlier source-assisted crossing height remains an estimate.

## Support interpretation

The two-block test now includes the 4,283 retained dark oak support member cells,
alongside the actual deck. It measures 3-D separation between native cell/deck
bounds, including slab halves and the fence collision height. Each route visit
retains its own height. This reaches support returns below the earlier deck-only
cutoff while keeping riding space, walking space, buildings and water protected.

The revision preserves the previous 2,141 source fence interpretations and adds
825 beyond the deck-only rule. Of those added cells, 295 were visible leaves in
v7, five were generated tree logs and 525 were air from earlier structural
vegetation suppression. All use dark oak fences at the same cell positions. Raw
survey classifications are unchanged. The complete native comparison records
one further leaf removal and no added leaves.

A separate read-only check constructs 566 valid bays from adjacent brown-footing
assignments. Pairs must lie within three metres of track station and five metres
between footings, in the same footing family/bank. Crossed or degenerate polygons
are rejected. Different station visits are never joined by XY proximity. The
source nominal-Y to exported-row offset of one cell is applied before registration.
Each bay is capped below both deck undersides, allowing the full fence height.

That audit inspects 12,884 native cells across 1,334 columns and 33 chunks: none
contain leaf blocks. It performs no geometry changes. The main verifier also
finds no remaining native leaves at the 6,280 eligible two-block deck/member
candidate cells. Canopy outside these bounded tests remains eligible as woodland;
the check does not declare every nearby tree to be support timber.

## Validation and delivery

The full unittest run passed 3,127 cases with 13 skipped. The 91 focused geometry
tests are included in that run. Two further source-bay tests check the exported
row offset, full fence height and separation of overlapping track visits. Native
save/reopen checks cover all 9,100 chunks. Comparison with the delivered v7 world
finds 1,011 changed block states, zero changes outside the declared edit scope,
zero water changes and every retained track/support/building cell unchanged.

All figure-owned materials, connected timber, two padded campfire entities and
open curl centres are checked in the saved world. Head measurements are spans
and projections of occupied cell centres, not sub-centimetre surface measurements.
The crown is narrower than the cheek row and the lower muzzle projects farther
forward than the upper face. These checks establish geometry and persistence,
not an exact visual-likeness or as-built accuracy score.

The test workflow previously omitted optional Torch and OpenCV dependencies,
causing the failed CI notification visible in the user's screenshot. Both test
jobs now install the corresponding extras and a CPU-only Torch 2.6.0 wheel,
matching the local test environment. This does not add training to world export.

The head close-ups and full-view comparisons use actual saved native blocks,
fixed cameras and external vanilla textures. The three overview cameras include
the user's positions 646,159,-645; 673,153,-694; and 648,169,-689. Camera aims and
lighting are approximate. The images are diagnostic renders, not Minecraft
client screenshots. Provider images and texture files are not redistributed.

Import title: **Alton Towers — Wicker head and supports v8**. Import the v8 archive
as a new Bedrock world; earlier imported copies do not update automatically.
