# Theming envelopes with queuing below

The later [queue-area correction](queue-area-below-theming.md) replaces the note-only marker described below with a paved queue zone inside the user-identified circle. Internal queue routing remains unresolved.

The Wicker plan marking profile now recognises both theming limits and retains
their different vertical relationships. These were missing because the earlier
marking profile covered buildings and ride geometry, without the layered theming
annotations.

| Source feature | Printed upper level | Queue relationship | World marker |
| --- | --- | --- | --- |
| Theming Envelope 1 | 195.8 | Explicitly says “with queuing below” | Purple boundary, yellow note anchor |
| Theming Envelope 2 | 196.8 | No queue-below claim supplied by this note | Purple boundaries |

The literal note parser accepts split numeric text such as `195 .8` and both
`queuing` and `queueing`. It retains exact native trace/character identities,
label geometry and visible glyph proofs. Upper levels remain source drawing
levels with an unverified datum; **195.8 is not treated as building height**.
The queue floor level, queue extent and queue route remain null. Neither note
authorises a solid building footprint. The absence of a queue note on Envelope 2
does not prove that no queue exists beneath it.

## Boundaries and display

The reviewed original paint selections retain Envelope 1's translucent circular
limit and Envelope 2's overlapping rounded/curved limits. Their original fill
opacities are allowed explicitly for these reviewed features, rather than being
mistaken for opaque building footprints. The smaller annotation backplate is not
used as the envelope. Original curved controls participate in source witness
hashes; curved display outlines have a 0.05 native PDF-point chord tolerance.
No fill, endpoint repair or inferred queue path is generated.

In the current one-metre world, all **76 Envelope 1** and **68 Envelope 2**
boundary sample cells are visible in purple wool. A **single yellow wool block**
at the original `below` label position represents the note; it is not a queue
entrance, route or area. The interiors stay unfilled. Theming outlines receive
display priority at track crossings so they do not disappear into ride colours.
All original ride geometry is retained, although purple overprints 18 orange
alignment cells in this flat annotation view. This is not a functional coaster
or a physically layered building model.

The resulting world has 3,958 marking cells, 731 oak-fence columns and 482 rock
blocks. Source paving remains 7,558 cells, with 7,375 paving-material cells visible
beneath the complete marking overlay. Both source envelopes, their note proofs
and relationships remain in the portable review bundle and saved job result.
Native block/property, complete platform/headroom, supported-spawn and all 165
extracted-chunk/archive checks pass. Minecraft import and gameplay remain
untested; terrain and geographic registration remain unresolved.

## Compatibility and validation

New original-PDF planning pilots capture these annotations automatically when
processing the pinned reviewed Wicker drawing. The pure literal parser is reusable;
association with these particular contours remains a reviewed source profile,
not a new general autonomous detector or neural training result. Rerun an older
planning analysis to collect the additional features.

The previous four-feature profile is retained in
`voxel_mapper/data/wicker-plan-markings-v1.json`. Its actual saved Wicker review
still reloads under the upgraded exporter. Three-, four- and five-input requests
remain supported. Changed/re-signed geometry or changed level/queue claims are
rejected by profile and source-annotation witness checks.

Tests cover separate upper-level and queue semantics, no inherited queue claim,
unsupported prose, hidden/tampered annotations, original translucent curved
outlines, legacy replay, complete visible boundaries at crossings and saved
purple/yellow native block states. The frozen Windows smoke validates both note
interpretations, loads the bundled updated profile and exports/reopens five wool
colours. It does not claim a full frozen Wicker-source replay or physical accuracy.
