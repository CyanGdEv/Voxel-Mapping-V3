# Building names split across planning annotations

The Wicker courtyard hold was caused by the label **COURTYARD TAVERN** being
split into separate native text shows. The literal parser read `COURTYARD` as
a plaza, while a separate visible `building` label described the same enclosure.
The resulting building/plaza conflict was correctly withheld. A brick finish
was not the cause: ordinary courtyard-role and brick-material labels already
combine successfully.

The new `planning-name-context-v1` adapter retains the original noun but excludes
it from literal surface-role voting when one supported adjacent uppercase
building-name suffix qualifies it. The initial suffix vocabulary is TAVERN,
INN, PUB, HOTEL, CAFE, CAFÉ and LODGE. It is deliberately limited; unsupported
names and typography retain the existing interpretation and ambiguity rules.

Both source runs must be horizontal, uppercase, of the same font and colour,
and within the recorded 15% size compatibility bounds. They must be directly
adjacent on one line, or closely spaced and left/centre aligned on consecutive
lines. Exactly one suffix may meet these typography tests. Both complete label
boxes must independently belong to the same single source enclosure. Nested,
competing, distant, cross-boundary, hidden or inconsistent suffixes cannot
remove an existing role conflict. Original glyph visibility checks apply to
both texts; no OCR correction, endpoint repair, snapping or boundary selection
is introduced.

A qualifying name **does not create a building**. A building-role proposal still
requires its own supported visible literal building label and complete source
boundary. A material label inside a named enclosure cannot independently turn
it into paving. A courtyard with no qualifying name remains a plaza hypothesis
and may retain its bound brick finish. Genuine building/path/plaza, state,
legend, material and enclosure conflicts remain withheld.

The source label retains `qualified_building_name_withheld`, exact trace and
character indices, original geometry, compound name text, suffix geometry and
glyph proof. Building associations and saved area layouts retain the excluded
name witnesses. Reload checks require those witnesses to remain visible,
source-bound and inside the same enclosure. Surface decisions also retain the
actual semantic context, including all conflicting label texts and roles, so
material-only diagnostic lists no longer conceal the reason for a role hold.

Printed existing/proposed/new states on excluded name fragments remain in the
association and saved layout's state calculation. A qualified name cannot
discard an existing/proposed conflict or silently replace it with a caption state.

The adapter adds lower-only limits of 128 candidate suffix runs and 64,000
name-context comparisons. Existing label, geometry, containment and output
limits remain unchanged. Exhaustion or cancellation cannot publish partial
successful outline hints. The literal parser and source label identities retain
their existing version; additive context metadata and implementation hashes
invalidate new analysis scopes while older saved layouts remain reloadable.

## Wicker development result

The same original site-plan PDF now retains **four building-footprint proposals
and two material-surface proposals**, up from three and two. The added enclosure
has a nominal area of about 209.83 m² and retains the original source polygon.
There is one nominal boundary contact, with no verified doorway or route.
The surface stage still uses 14 regions, 9,902 native candidates and 20,966
points. Of 134 relevant native labels, 45 remain eligible surface labels; the
qualified building name is no longer counted as an eligible surface role.

The six-proposal layout exports on the same 196×115 m flat platform: 22,540
cells, two sections, 90,492 native write attempts and 104 saved chunks. The added
building proposal contributes 211 marker cells. An independent archive audit
checks every ground, foundation and headroom cell. All previous five proposals
retain their source polygons, roles and finishes; the actual previous saved
layout reloads successfully. This remains a flat inspection output.

There are still **41 eligible labels without usable surface enclosures**, no
explicit path/plaza candidates, no reconstructed heights or roofs and no
surveyed park registration. The two material patches remain only eight display
cells. This is previously inspected development data, not an unseen accuracy
benchmark. No accepted park geometry, reviewed training labels or neural updates
are created.

Twelve regressions cover complementary role/material labels, multiline and
separate inline text shows, names without building labels, hidden and ambiguous
suffixes, typography and scope mismatches, nested enclosures, quota exhaustion,
rotation/replay/cancellation, preserved printed states and tampered saved witnesses. The managed/frozen
desktop smoke now starts with a synthetic split building name, discovers the
same two building/three paving proposals, and retains both the small and complete
tiled export/restart checks.

See the [source-pinned development receipt](evidence/planning-building-name-context/validation.json).
The next geometry task is recovery and interpretation of the remaining path and
plaza boundaries, then cross-view building heights and roofs.
