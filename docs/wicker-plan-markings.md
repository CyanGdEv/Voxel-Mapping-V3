# Games, toilets and Wicker Man plan markings

The reviewed Wicker landscape drawing now supplies additional ground-level 2D
markings in the area-world export:

| Feature | Marker |
| --- | --- |
| Games 9×3m source boundary | Light-blue concrete |
| Toilet / arcade visible wall lines | Light-blue concrete |
| Wicker Man source alignment | Orange wool |
| Track side display guides | Blue wool, one nominal block either side |
| Drawn support-frame edges and post outlines | Brown wool |

The orange alignment retains the original 428-point faceted CAD line, about
773.6 nominal metres long. Brown follows all 73,495 original structural paint
groups, including frame cross-members and post outlines; it is not a guessed
constant-width support envelope. Blue sides are per-segment one-block display
offsets with bevel connections. They retain both branches at projected crossings
and are **not measured rail edges**. No ride height or crossing level is inferred.

Games uses its reviewed original filled boundary, excluding the smaller white
text mask. The toilet/arcade marking retains five source wall paint groups,
including their openings and small gaps. It does not invent a closed footprint.
As with previous markers, a one-metre block grid can hide sub-metre openings and
cannot represent every source detail. Existing building boundary proposals remain
available; no building height, roof or functional coaster has been constructed.

## Source review and scope

`voxel_mapper/data/wicker-plan-markings.json` pins SMD/2017/0111's previously
inspected landscape drawing (SHA-256 `1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`),
page one, its content hash, reviewed paint selections, source witness hashes and
exact geometry hashes. This profile records interpretation of that specific
original drawing for the user's marking request. It is **not a general autonomous
ride or toilet detector**, an unseen accuracy benchmark or a learned model update.
Other documents return `no_reviewed_source_profile` and cannot acquire ride roles
merely by using similar colours. A changed original or changed/re-signed marker
geometry is rejected rather than silently substituted.

New planning pilots retain the marking review, source-plan overlay and profile
fingerprint. Windows area export passes it as an optional fifth pinned input.
Older saved jobs without this review retain their existing export; rerun the
original planning analysis to collect the new markings. Three- and four-input
geometry requests remain supported. Input caches use compact JSON for the 5.57 MB
marking review while retaining the existing 16 MB per-input limit.

## Current world

The complete 219×157 block platform now has 3,928 marking cells: 32 Games,
206 toilet/arcade, 976 orange alignment, 1,471 blue side-guide and 1,243 brown
support-frame cells after overlap priorities. Source supports first, then side
guides, alignment and named building boundaries determine visible ground colours.
The source geometry remains in the portable review bundle.

Annotations overpaint 183 of the 7,558 source paving cells, leaving 7,375 paving
material display cells. They also overpaint 15 earlier building-marker cells and
replace 154 assumed edging columns where those would obscure the explicit new
markings. The resulting native world has 731 oak-fence columns and 482 rock
blocks. The strict under-four-block oak-fence rule still applies to remaining
edging. Detailed initial fence connector/diagonal diagnostics describe the edging
stage before the marking overrides; final saved block counts describe the output.

Every platform material and block property, profile and paving headroom is
verified in the saved database. Archive CRCs, packaged bytes, supported spawn and
all 165 chunks are checked again after extraction. The full source screening,
annotated-plan render and native world run took about 101 seconds with 458 MiB
peak process RSS on the Linux runner. Minecraft import and actual player movement
remain untested. The terrain is flat nominal ground without surveyed registration.

The source extractor is bounded at 100,000 drawings, 100,000 selected operators
and 200,000 points; this drawing uses 73,959 operators and 147,461 marking points.
Output is limited to 16 MB. World marking traversal is bounded at one million
steps and 20,000 distinct cells and never crops an oversized result. It uses
half-open grid traversal without thickening, snapping or endpoint repairs.
Cancellation and exhausted budgets cannot return a successful partial marking.

Native tests cover open wall preservation, source mutation, re-signed geometry,
unknown drawings, projected crossing guides, negative/reversed grid traversal,
quotas/cancellation and all three saved wool colours. The frozen Windows smoke
loads the bundled reviewed profile and exports/reopens a native three-colour wool
palette. That smoke validates packaging and block states, not a frozen full-Wicker
replay or Minecraft gameplay.
