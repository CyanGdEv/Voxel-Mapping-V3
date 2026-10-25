# Coalesced planning-surface recovery

The surface stage now preserves every supported label's original search window
while combining overlapping windows into a bounded recovery schedule. A merge
must cover both complete original rectangles and must not increase their summed
area. A deterministic priority queue favours the least added empty area. A
65,536-pair-check ceiling bounds scheduling work; cancellation propagates.
Regions, paths, candidate/point, outline, association and output limits remain
unchanged. An incomplete schedule or extraction withholds the full result.

One native source pass extracts the union of the scheduled windows. Every paint
group must fit wholly inside at least one window, including the existing margin.
The pass retains original paint ordinals and processes the original clipping and
compositing stacks. It never clips a primitive or substitutes local ordinals.
The extraction contract records the complete window list.

This straight-face mode excludes curves and nonsolid open lines before candidate
quota accounting: the existing straight-boundary adapter cannot use them.
General drawing extraction still supports curves by default. Excluded aliases
are tracked by geometry identity and scope; a curved or nonsolid alias still
withholds an otherwise matching primitive in that scope. It cannot silently
turn a previously ambiguous line into a usable boundary.

Candidate and point limits apply to the unique eligible native inventory decoded
once. The same parsed geometry may be referenced by more than one region, but
faces are recovered separately in each region using only original paint groups
eligible for that region. Lines from distinct scopes are not combined into a
new loop. Global later-paint checks include paint outside the search union.
Scan-work accounting charges original paths times scheduled regions plus paint
membership assignments; it is not a claim that source indexing is implemented.

Receipts retain all original windows, each region's source-window membership,
merge work, the shared extraction contract and inventory hash, region inventories
and original source-record pins. The new surface version is
`planning-surface-boundaries-v3`. Actual saved v2 standalone layouts remain
reloadable; analysis jobs invalidate through their implementation contracts.

## Wicker development replay

The previously inspected woodland-path site plan now completes all **46** label
windows through **14** regions, using one native source pass, **9,902** shared
candidates, **20,966** points and **1,310,936** charged scan-work units. All remain
inside the original limits of 32 regions, 10,000 candidates, 200,000 points and
3,200,000 scan-work units. No lower-only limit was raised.

The complete inventory contains 199 unique supported enclosures. It produces a
nominal 1:250 shared layout with three building-role footprint proposals and two
material-labelled surface proposals (`stone` and `brick`). They are literal
source-label enclosure hypotheses, not accepted buildings or verified paths.
There are no explicit path/plaza candidates, no measured heights or roofs and no
verified connections. The enlarged evidence still withholds the courtyard/brick
and ground associations because their source roles conflict. It does not simply
restore every earlier proposal.

A full-layout world-preview attempt remains withheld: its padded platform would
be 196 by 115 metres, beyond the existing 128 by 128 metre display limit. The
five features are not cropped, discarded or rescaled to force an export. No real
world download, physical registration, accepted training label or neural update
is produced. This is development data, not an unseen accuracy benchmark.

The next export step needs explicit bounded-area selection or bounded streaming
of a larger complete preview. Physical surface interpretation and building
height/roof evidence are still needed for reconstruction.

The managed desktop smoke checks shared extraction and coalescing end to end,
with the original synthetic paving readback, embedded-font transform check,
A1/A3 paper choice and durable restart. Its buildings remain footprint markers.

The [source-pinned development receipt](evidence/coalesced-surface-recovery/validation.json)
records the complete schedule, shared quotas, original scope coverage, layout,
legacy reload and actual full-sheet export hold.
