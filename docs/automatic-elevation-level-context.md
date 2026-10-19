# Automatic source-relative elevation level context

Component inventory v6 connects original printed level markers to the automatic
view pack and reviews original residual jamb evidence above a printed Shop Level.
It follows [named building/facade scope](automatic-building-facade-scope.md) and
keeps both the 955 broad and 40 narrower Wicker width alternatives available.
No user-supplied artwork box, floor trace, facade datum or opening trace is used.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-elevation-context-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-elevation-context-job.json --output output/elevation-context-audit.json
```

## Original marker assignment

The existing native level kernel gains an explicit `whole_view_containment`
recipe; its default remains `artwork_side` for existing callers. Native circles,
opposed black quadrant fills, horizontal leader paths and printed decimal level
claims remain original source evidence. Complete source fill/clip geometry, path
ordinals, paint sequence, text trace indices and original-font glyph-screen
receipts are retained. Marker clipping/visibility and physical level roles remain
unverified.

All automatic elevation views on a source page enter the membership comparison,
including views deferred by the component view limit. A marker can qualify only
when its entire circle, every eligible caption box and every leader endpoint are
covered by a unique automatic view. A crossing annotation, competing view,
nonunique caption/leader or failed glyph screen remains held. Unscaled competing
views remain in the membership test; they cannot supply metric references.

Internal automatic view IDs bind these results to source PDF/page/view hashes.
They are explicitly distinguished from printed project/sheet/view references.
The adapter requires rectangular source view scopes and positive aligned source
pixel-to-display transforms. Unsupported frames remain explicit holds.

A source-relative reference still requires exactly one visible `Shop Level`
claim in the view. Other supported decimal level references provide a nominal
spacing check against their printed differences, using the existing 0.01 m
window. A failed check withholds the relative reference. One reference alone
remains a candidate without an independent scale check. Units, physical floor
role, extension of the short leader across the facade and survey datum stay
unverified. This vocabulary does not yet cover every building's level convention.

## Original jamb support above the printed level

Every retained residual consensus family is reviewed. Each keeps its original
first-threshold pair and **every** matching second-threshold pair. The review
binds original pair/group hashes, grayscale hash, source bounds, nominal head and
bottom heights relative to the printed level, and the original common vertical
row interval of both jamb groups.

A separate interval records only whole original rows whose lower pixel edge is
at or above the printed level. Its upper end is the lesser of the original
common jamb bottom and `floor(printed_level_pixel)`. Empty intervals remain
empty; there is no rounding to make a candidate pass. Source jambs, heads,
endpoints and full rectangles are not trimmed, extended or filled.

The bounded discovery recipe asks for at least 24 such rows in **all** original
threshold witnesses. This is a source-raster heuristic consistent with the
scanner's existing 24-pixel minimum run, not a physical minimum opening height.
Its nominal size depends on render resolution. A merely positive head height
is insufficient. Witnesses that straddle the 24-row decision retain an explicit
threshold-disagreement status; no favourable threshold is selected.

The stage publishes a conditional `level_supported_width_links` channel for
previously retained numbered-reference width links that meet this row test.
Original broad/narrow links and all rejected or ambiguous families remain
available. Texture, cladding or unrelated structure can still satisfy the test;
small real openings and excluded repeated mullions may fall outside this recipe.
It is not a complete physical opening inventory or a door/window classifier.

No elevation facade origin is fitted to make a plan position agree. The original
plan projection remains available through the source building-link/projection
IDs; physical position alignment stays false. No sill, threshold, door bottom,
world height or training label is inferred.

## Bounds, outputs and replay

`elevation-level-context.json` is a ninth hash-bound component output. It retains
page scopes and native marker reviews, per-view relative references, every
family/witness review, and the conditional narrower links. The contract pins the
adapter, native level kernel and printed-level parser. Source PDFs and upstream
artifacts are rechecked before the completed report is published.

The existing native source limits and 100,000-check ceiling apply separately per
page. Family/witness/link work has its own configured ceiling, at most 100,000
checks, and at most 8,192 families across 32 selected component views. A budget
hold discards all partial context pages, families and conditional links. All
source-page competitor scopes participate, up to the native kernel's 100-view
limit. The component pack's cumulative 64 MB limit includes this output.
Inventory v6 uses area/controller v11/v9; use a fresh work directory for older jobs.

## Wicker result and remaining gates

| Evidence | Result |
| --- | ---: |
| Original native marker records | 7 |
| Usable marker/caption/leader links with original glyph evidence | 6 |
| Views with a source-relative Shop Level candidate | 4 |
| Original residual families reviewed | 291 |
| Families meeting the above-level row recipe in all witnesses | 38 |
| Families with insufficient support in all witnesses | 253 |
| Previous numbered-reference width alternatives preserved | 40 |
| Conditional level-supported alternatives | 6 |

The six conditional alternatives overlap in one north-west image neighbourhood;
they are **not six physical openings**. Their observed head height is about
2.147 nominal metres above the printed Shop Level. Their original vertical
runs continue below that level and remain unchanged. A physical aperture cannot
be carved from those full source rectangles.

The unparsed/nonunique south-west marker remains in the native review. South-west
still has no retained numbered-reference width match; north-east's inside-marker
facade hold and both broad SE/NW scan pair caps remain unchanged. The 955 broad
width pairs and 40 numbered-reference width pairs are preserved against PR #41.

Actual exterior/aperture identity, independent elevation facade extent/origin,
physical floor role and position alignment, construction state and independent
geographic/vertical registration remain unresolved. Accepted physical geometry,
world blocks and training labels remain zero; the semantic ranker remains untrained.
The independent level audit verifies 14 original quadrant fills, seven leader
paths, six original-font glyph claims, all 714 threshold-witness occurrences,
291 family decisions and the exact six-link conditional set.
Audit and local-test receipts are under `docs/evidence/elevation-level-context/`.

The final local suite passes **1,598 tests**, including nine new regressions.
The focused related suite passes 42 tests. All nine output artifacts match a
fresh replay; all 955 broad and 40 numbered-reference width pairs are preserved.
