# Wicker sculpture rework after the in-game v5 review

The user's screenshots at `[646,159,-645]` and `[639,151,-665]` exposed a
likeness problem that block round-trip tests did not assess. The v5 torso was
dominated by broad vertical log cladding, and its horn ribbons read as solid
dark patches from the side. A successful save was not evidence of a visual
match to the supplied Minecraft close-ups.

## Revised figure

`wicker-structural-reconstruction-v2.json` selects a separate stepped sculpture
builder. The v1 profile and builder remain available for replaying v5. The new
body has raised plank/stair ribbons, crossing shoulder bands, inset board and
clay panels, a higher tapered chest and a shorter tapered head. It uses no
broad bark-textured log cladding. Cheek and jaw planes, a projecting downward
ram muzzle and narrow eye slots replace the earlier box/door-eye treatment.

The horn curls run around the sides of the skull. Recesses behind their rings
leave an open centre in the native cell geometry. Two shoulder campfires replace
the six overlapping v5 emitters; each has a timber pad and a saved native block
entity. Short shoulder posts and trapdoor plates complete the stepped outline.

The supplied Minecraft close-ups guide blockwork and visual proportions. The
resort's [full-size side photograph](https://www.merlinannualpass.co.uk/passholder-hub/),
the [resort-released ram photograph](https://blooloop.com/theme-park/news/alton-towers-wicker-man-roller-coaster/),
and [creative lead's description](https://www.altontowers.com/about-alton-towers/blog/wicker-man-what-s-it-all-about/)
guide the distinct human/ram profiles, upward human face, downward ram muzzle
and deep side curl. The human face remains on the reverse of the ram face.
The official miniature is a secondary silhouette reference, not a scale survey.

The registered body/head placement and approximate 179–196.5 m ODN envelope
are retained. Upper survey returns within the marked footprint cluster near
E407554.5, N343550.4; they constrain location and height, not a complete face or
weave. Facial features, skin, shoulders, unseen surfaces and horn routing remain
explicit modelling inferences. No physical-accuracy or exact-likeness score is
claimed. Native metre cells constrain the available facial detail.

## Geometry boundaries

All retained Wicker track/support blocks and reserved passage air keep priority.
The three visits through the figure remain separate; no track is moved to fit
the new sculpture. Other ride, monorail, queue and landscape reference roles are
unchanged. This profile does not redesign support positions or their density.

The earlier capped structural vegetation exclusion is retained and unioned with
the new figure volume, so changing the silhouette does not regrow rejected
foliage around the former shape. Surrounding woodland and canopy above the caps
remain eligible. Raw LiDAR classification labels remain unchanged.

## Review and validation

The native verifier compares all 9,100 chunks with the delivered v5 archive,
checks every retained Wicker and reference cell, water, passages, new figure
materials, connectivity and lit campfire entities. Seventy-five tests include
the earlier invariants plus connected revised geometry, absence of broad bark
cladding, padded emitters and the open horn-curl centres. These are geometry and
serialization checks, not a certificate of artistic or surveyed fidelity.

Optional `--textures` output renders actual saved blocks from the two user
positions. Eye height is 1.62 blocks above those positions; camera aim and an
80-degree horizontal field of view are approximate. Both versions use the same
cameras and vanilla material texture inputs, exposing bark/plank differences
that the flat-colour isometric preview concealed. The software renderer omits
client particles, shaders and client lighting; its images are diagnostic views,
not Minecraft screenshots or pixel-calibrated photogrammetry.

Texture files are external inspection inputs from Mojang's public
[Bedrock samples](https://github.com/Mojang/bedrock-samples/tree/main/resource_pack/textures/blocks).
They are not installed in or redistributed with the native world. Download
receipts preserve their source URLs and hashes. The world continues to use its
ordinary Minecraft materials.

New import title: **Alton Towers — Wicker sculpture rework v6**. The prior
delivered v5 archive remains unchanged.
