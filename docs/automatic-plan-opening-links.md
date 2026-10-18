# Automatic plan-to-elevation opening discovery

The automatic component inventory now recovers facing plan endcaps and compares
nominal gap widths with retained residual elevation families. It needs no manual
wing seed, opening trace, facade datum or view rectangle. This supplies candidates
for subsequent position/direction and physical-role interpretation.

Use the existing opt-in `drawing_views` and `drawing_view_components` settings:

```sh
python -m voxel_mapper.area_reconstruction \
  --job examples/wicker-opening-links-job.json --stage extract
python -m scripts.audit_drawing_view_components \
  --job examples/wicker-opening-links-job.json --output output/opening-links-audit.json
```

## Source plan gaps

For each non-roof floor-plan view with a nominal scale, the adapter runs the
existing exact straight-fill/clip and facing-endcap kernels on the original PDF
page. Whole-page fill recovery happens before view filtering: crossing/outside
fills remain available to the original corridor overlap test. No missing blocker
is created by discarding another view's fill first.

`plan_gap_review` retains the whole page's recovered fills, original fill rings,
clip references, paint sequence and endcap recovery. A gap enters this view only
when both entire parent fill geometries and the entire source-corner corridor
are covered by the candidate view. Crossing gaps remain listed by ID, without
clipping. Native copies use the exact unrotated MuPDF-to-PDF transform; the source
PDF and original endcap endpoints remain unchanged. The original projected width
and the nominal distance between cap centres are recorded separately.

The existing recipe searches cap thicknesses 0.08–1 m and gaps 0.08–8 m, with
its original 0.5-degree direction and one-PDF-point transverse/cap-width windows.
These are nominal discovery filters. A gap may be a doorway, hatch, symbol,
internal partition or unrelated pair of filled structures. Intersecting fills
remain explicit flags; neither clear paint nor a closed corridor proves an opening.
Unsupported curved/composited/optional-layer fills remain in the existing recovery
counts. No complete visible-page or complete physical-gap inventory is claimed.

## Width links and remaining ambiguity

A new `opening-links.json` is included in the component report's hash manifest.
It compares every retained plan gap with every scoped residual elevation family
in this area. Same-area membership is only a search domain: building identity,
view association, direction, position, height and physical aperture roles remain
unverified. The broad raster scans and their existing budget failures are preserved.

Plan width is the original endcap-axis projection times the printed nominal scale.
Elevation width is the first-threshold family's pixel-edge width times its exact
pixel-to-native step and that view's nominal scale. All matches within 0.25 m are
retained, including competing families and matches in different elevations. There
is no nearest match, manual floor-layout correction, facade origin or scale fit.
The tolerance is a discovery window, not an accuracy or uncertainty claim.

Every link identifies both views, gap and residual family, binds both complete
inventory hashes, records both nominal widths and their signed difference, and
carries the original fill-overlap and unresolved-construction-state flags.
Explicitly conflicting printed construction states do not match; an unspecified
state is never inherited from the catalogue or another drawing.

Plan-gap summaries retain all match IDs and explicit state conflicts. No match
means no compatible retained residual family, not that a physical opening is
absent. Repeated-stroke exclusions can also remove real mullions. Missing-scale,
withheld-plan and withheld-elevation statuses remain visible separately.

## Bounds, replay and real Wicker result

Source fill/endcap kernels retain their fixed candidate, vertex and output caps.
The existing 100,000-check option now also bounds endcap pair/overlap checks and,
separately, the complete width-link comparison. Link input is bounded to 32 unique
views, 4,000 gaps and 8,192 residual families. Exhaustion discards all partial
links. The component pack's 64 MB cumulative limit includes `opening-links.json`.
The contract pins the new adapter and underlying fill/clip/endcap implementations.
Inventory v4 uses area/controller v9/v7; use a fresh work directory for older jobs.

The three checksum-pinned Wicker originals produce six unchanged source views:

The overall floor plan includes the shop, preshow, ride station and maintenance
buildings. The 24 gaps cover that entire source-view search domain. They have
not yet been assigned to individual physical buildings; a shop elevation match
can therefore still point to a gap in a neighbouring building.

| Measurement | Result |
| --- | ---: |
| Retained original floor-page fills | 98 |
| Facing-endcap gaps within the automatic floor-plan view | 24 |
| Original endcap edge proofs | 48 |
| Plan gaps carrying other-fill overlap flags | 4 |
| Residual elevation families retained | 291 |
| Families with at least one nominal-width link | 145 |
| All alternative width links | 955 |
| Plan gaps with multiple alternatives | 24 |
| Plan gaps with no retained width match | 0 |

The independent audit checks all 6,984 gap/family width pairs, verifies the exact
955-link set and original source endpoints, and reproduces every pack artifact
in a fresh directory. Existing native geometry and original capped scans match
the hash-verified PR #39 baseline. The two broad SE/NW scans remain pair-budget
withheld; overall requested-pass completion remains false.

This is candidate correspondence, with zero accepted physical components, world
blocks or training labels. The semantic ranker remains untrained. Actual exterior
and opening roles, facade position/direction, cross-view dimensions/construction
state and independent geographic registration/vertical datum still gate assembly.
No new reconstructed building or park world is generated by this step.

Audit and local-validation receipts are retained under
`docs/evidence/automatic-opening-links/`.

The final local suite passes **1,580 tests**, including nine new regressions.
The focused related suite passes 55 tests.
