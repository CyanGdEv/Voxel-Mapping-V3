# Wicker attachment-point review

This pass restores the exact retained proposed site-plan PDF and reproduces its
shop, Burger Kitchen and FastTrack candidate IDs from the current native
extractor and exact linework recovery. The PDF checksum is verified; no source
geometry is copied from a screenshot or changed to fit a survey. Planning
physical identity, fill and construction state remain separate review tasks.

`scripts/review_wicker_attachments.py` takes `--pdf`, `--dtm`, `--dsm`,
`--survey-receipt`, `--osm`, `--grid` and `--output`. The receipt is
`evidence/wicker-dated-landmark-audit.json`; the paired dated crop comes from
`scripts/audit_dated_wicker_survey.py`. Input bytes, survey identity, metre grid
and grid transform are checked. Native PDF geometry is re-extracted, rather than
trusting a manually entered polygon. All three source candidate IDs reproduced.

## Edge sensitivity results

For inspection only, the complete dated raster crop is segmented at six
surface-above-ground thresholds: 1.5, 2, 2.5, 3, 3.5 and 4 m. Regions are formed
without mapped-footprint clipping, snapping or gap filling. The largest IoU
comparison with each mapped landmark is retained at each threshold; that
comparison does not identify a physical roof/wall or exact attachment point.
Minimum-rectangle corner estimates are available for inspection and explicitly
marked as not verified physical points.

| Comparison landmark | Maximum boundary spread across tested thresholds |
| --- | ---: |
| Burger Kitchen | 10.77 m |
| FastTrack | 31.76 m |
| Wicker Man Shop | 32.89 m |

These are segmentation changes, **not survey positional-error bounds**. Low
thresholds can connect roofs with adjacent elevated surfaces; high thresholds
can shrink or split a structure. At 3 m the shop comparison is a 938 m² merged
region with only 20.1% map overlap. At 3.5 m it separates to 206 m² and 83.2%
overlap; at 4 m it becomes 195 m² with 81.4% overlap. Choosing the highest overlap
does not independently prove that a roof edge equals a planning wall corner.

The diagnostic source-shop-to-3.5 m-region boundary fit has 89.7% outline IoU,
1.15 m boundary Hausdorff difference and scale 0.08546 m per PDF point. It is
retained as a boundary hypothesis, not accepted registration or point identity.
Native edge uncertainty and roof-to-wall offset are unmeasured. Even an ideal
1 m square pixel has a half-diagonal of about 0.71 m; this is a sampling indicator,
not an accuracy certificate or an error budget for the complete survey.

## Decision

No point pairs are submitted to accepted registration: there are zero accepted
controls and zero checkpoints. The evidence supports a review queue containing
source-linked outlines, independent dated raster candidates, candidate rectangle
coordinates and the relevant unresolved identification/uncertainty fields.
It does not support relabelling pixel corners or mapped centroids as surveyed
attachment points. No world blocks are generated.

Next, identify the same physical boundary on both sources: isolate the intended
roof or wall, determine any eave offset, and measure stable attachment points
with known uncertainty. Higher-detail survey points or orthophotography may
help, but stable physical boundary identification is still required. Controls
and separately sourced checkpoints can then enter the existing checked
registration route without weakening its thresholds.

Full queue: `evidence/wicker-attachment-review.json`. It retains the failed and
no-region outcomes as well as the best overlaps. Repeated execution produced
byte-identical output.
