# Wicker Man structure and vegetation correction

The user's in-game examples at `[668, 167, -670]` and `[673, 162, -664]`
showed two problems that finer LiDAR bins alone did not fix. Big Bob remained a
107-cell partial return surface, and vegetation-labelled timber could still
create leaf blocks and estimated tree trunks inside the support field.

## Big Bob

The optional checksum-pinned `structure_profile` in the reference-world manifest
replaces the partial-surface interpretation with an explicit reference-assisted
effigy. Its hollow torso, lower arch, shoulder caps, neck, human face, ram muzzle
and paired curled horns share one BNG frame. A half-slab caps the top where the
17.5 m profile intersects a half-block level. Native metre quantisation still
limits facial and woven detail.

The finish follows the user's four Minecraft reference close-ups: stepped oak
and spruce stairs, darker curled horns, trapdoor panels, warm terracotta infill,
log ribs and a pale slab collar. Six lit campfires on timber shoulder pads supply
native flame and smoke effects. These are checked as lit blocks with saved block
entities. The reference screenshots' shader lighting is client-side and is not
part of the world geometry.

The shape uses the two opposite views of the resort's
[official Big Bob miniature](https://shop.altontowers.com/products/wicker-man-big-bob-resin)
and its creative lead's
[description of the opposite faces and three passages](https://www.altontowers.com/about-alton-towers/blog/wicker-man-what-s-it-all-about/).
The miniature is a silhouette reference, not a measured full-size survey.
The body/head placement and approximate 179–196.5 m ODN extent use the registered
aerial outline and dated LiDAR context. The native source window contains 294
elevated context returns, including 147 class-5 and 34 class-4 observations;
source vegetation labels alone do not identify this known sculpture correctly.

Shell thickness, facial details, rib pattern, horns and unseen surfaces are
source-assisted modelling choices. They are explicitly recorded in
`wicker-structural-reconstruction.json`; the completed shape is not presented as
a complete measured LiDAR surface. The original source classifications are kept.

All original structure blocks and riding air retain priority. Three visits
through the figure remain separate by route station, including the high pass.
Their paths and elevations are not merged or moved to fit the sculpture. A
proposed model cell is withheld wherever it would fill an existing passage,
intersect retained architecture/track, or be buried in terrain.

## Timber versus trees

Each of the 1,391 retained support members supplies a narrow horizontal corridor
from its original brown footing to its assigned centre-deck bearing. The local
structural volume runs from ground to that branch's deck plus three metres,
with a 1.25 m horizontal margin. Big Bob supplies a separate bounded figure
volume. A vertical exclusion mask rejects leaf voxels inside these volumes;
canopy above and woodland beyond them remain eligible.

Estimated trunks are not grown from return peaks within the structural columns.
The original dark-oak support blocks, footing positions and member endpoints
remain intact. Vegetation returns are not indiscriminately turned into timber,
and surrounding forest is not globally cleared. Source-class and geometric-role
evidence remain separate. Fine LiDAR terrain/structure infill respects these
structural grade columns as well.
Returns suppressed from native structure output still supply local source
support to adjacent observed surfaces. This prevents a boundary filter from
deleting an otherwise supported slab just outside the semantic volume.

The optional manifest keeps older v3/v4 jobs replayable without silently adding
the shape completion to them. Source profile checksums participate in the world
audit and all new structure blocks are exported to the native world.

## Checks and delivery

Seventy-one tests cover connected sculpture geometry, a hollow arch, capped
vegetation exclusion, canopy retention, trunk rejection, source restrictions,
roof/terrain sampling, the blockwork palette, native campfire state/entities,
native material/state preservation, adjacent LiDAR-surface retention and earlier reference
and transport invariants. The exporter reopens all 9,100 chunks. The additional
saved-world comparison checks every chunk against the delivered v4 archive,
every retained Wicker block, unchanged other reference roles, riding air, water,
all new sculpture materials, and zero remaining leaf blocks in structural
volumes. The actual effigy parts must connect through native timber, rather than
only having connected points in a diagnostic proposal.

`scripts/verify_wicker_structure_fix.py` generates the exact receipt and native
before/after crops. Its isometric material/shape render is simplified, not a
Minecraft client screenshot. Independent physical fidelity and a client test
remain unverified. Existing ride heights, supports and stations retain their
earlier provisional status.

New import title: **Alton Towers — Wicker structure fix v5**. Geometry outside the
bounded structural columns is checked separately to keep the park-wide v4 work.
The correction changes reconstruction, not neural model weights.
