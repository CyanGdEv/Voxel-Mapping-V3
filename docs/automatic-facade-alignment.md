# Automatic facade extent and origin review

[Automatic sheet-scale evidence](automatic-sheet-scale-evidence.md) now adds an
independent peripheral-text layout diagnostic alongside these raw comparisons.
It narrows Wicker's nearby-paint mismatch to 0.305 m; the 0.25 m gate still fails.

Component inventory v7 adds `facade-alignment.json`. It compares independently
extracted source extents before attempting an opening position comparison.
No user facade box, opening trace, origin, translation or scale fit is supplied.
The output retains rejected comparisons as well as conditional hypotheses.

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-facade-alignment-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-facade-alignment-job.json --output output/facade-alignment-audit.json
```

Use a fresh work directory: area/controller advance to v12/v10.
The example enables acquisition of the same three checksum-pinned originals.
The recorded validation uses verified originals offline.

## Independent source extents

Every numbered marker/enclosure frame retains the whole named enclosure as one
extent candidate. Every nonwhite original source paint with a boundary within
0.25 PDF points of a frame ray hit is another candidate, provided its complete
geometry fits the automatic plan view. All disconnected parts and holes survive.
The span is a projection of original exterior vertices, with exact extreme-vertex
provenance. It does not establish wall continuity or identify a physical facade.
Crossing paints are withheld whole, without clipping or selecting a nearby part.
The neighbourhood is a discovery heuristic, not proof of boundary coincidence.

For each preceding level-supported width link, the stage searches all retained
above-level residual families in that numbered elevation. Every original
threshold witness of a surrounding family must strictly enclose the child's
horizontal bounds, have a higher source head and reach at least its original
bottom. Every parent/child witness combination participates. Jamb groups must
be distinct within each threshold. Self matches and source-view crossings are
excluded. A containing frame is source line evidence; it is not a verified wall.

Each plan extent is compared with every eligible parent family once. The original
nominal scales must agree within 0.25 m in **every** parent threshold witness.
Mixed decisions remain explicit. Width ratios are diagnostic only: the stage
never applies them as a scale correction. Different extents and alternative
parents remain separate; none is promoted to a physical boundary.

## Conditional origins and position checks

Only an extent passing every width witness can supply an origin hypothesis.
The original left parent pixel edge maps to either the left or right plan
extent edge. Both directions remain available, using the original nominal scale.
Neither translation nor scale is fitted to an opening.

Every original parent/child witness combination produces a position interval.
Both endpoints must agree with the original plan gap projection within 0.25 m.
All-pass, mixed and all-fail outcomes are recorded separately. Complete original
jamb rectangles, including below-level runs, remain unchanged. Even an all-pass
comparison has `physical_correspondence_verified: false` and
`position_alignment_verified: false`: independent physical extent/aperture roles,
dimensions, construction state and registration are still required.

## Wicker result

The preceding 955 broad width pairs, 40 numbered-reference alternatives and six
level-supported alternatives remain available. Those six overlap one NW opening
neighbourhood. All six have the same enclosing residual family, yielding six
parent/child relations and two independent extent comparisons.

| Source extent | Nominal width |
| --- | ---: |
| Whole Shop-labelled plan enclosure, including its seven holes | 18.762735 m |
| Nearby original plan paint, including both disconnected parts | 14.110970 m |
| Surrounding NW elevation jamb/head frame, both threshold witnesses | 15.829751 m |

Both independent width comparisons fail the 0.25 m gate. No origin or position
comparison is issued for Wicker. The discrepancy can reflect extent identity,
nominal scale or other source interpretation; these observations do not establish
which is wrong and do not justify a correction. The required next evidence is an
independent dimension or corresponding source boundary/corner, rather than a fit
to the candidate opening.

Four numbered facade records retain six plan extent candidates across four
source-facing segments. SW still has no narrower width match; NE retains its
inside-marker hold. The two broad SE/NW pair-budget holds remain. Accepted physical
components, world blocks and training labels remain zero; the semantic ranker is
still untrained.

## Bounds and validation

The stage shares the inventory's 32-view bound and has a separate configurable
100,000-check ceiling. Original projected vertices, parent/child witness tests,
extent widths and conditional positions charge that budget. Exhaustion discards
all partial frame reviews. The tenth hash-bound artifact counts toward the
cumulative 64 MB output limit, and the contract pins the implementation and all
upstream source hashes. Duplicate/stale source inventories and view records fail.

Regressions cover real raster consensus families, original PDF paint holes,
disconnected source parts, independent origins, both directions, position/width
failure, threshold disagreement, every witness, shared jamb rejection, crossing
paint, stale/ambiguous inputs and late budget discard. The audit independently
reconstructs plan extrema, the complete parent/child relation set, all extent
widths and conditional position intervals; a fresh replay checks every artifact.

The final local suite passes **1,609 tests**, including 11 new regressions.
The focused suite passes 50 tests; all ten artifact hashes match a fresh replay.
All 955 broad, 40 numbered-reference and six level-supported alternatives are
preserved against PR #42. Browser review checks all five facade/frame states
with zero JavaScript errors. Audit, browser and local-test receipts are under
`docs/evidence/facade-alignment/`.

Render the offline source review with:

```sh
python -m scripts.render_facade_alignment_review \
  --components COMPONENT_PACK --views VIEW_PACK --output output/facade-review.html
```
