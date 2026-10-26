# More 2D building boundaries from planning applications

Planning pilots now include a separate building-boundary overlay. Blue contours
mark source-supported building proposals; amber boxes mark visible building
labels for which no unique closed source fill was found. The source evidence
retains the original outline, visible label proofs and fill paint references.
This is an additional 2D review, not a certification of exterior walls or roofs.

The pass starts with the existing validated shared-frame building proposals.
It then matches the existing bounded literal building-label vocabulary (building,
shop, station, maintenance, toilets, restaurant and kiosk) to whole opaque white
source fills on the same page. Equal polygons painted more than once form one
proposal, retaining all paint references. Two distinct containing outlines remain
ambiguous: neither the smallest nor the last-painted outline is selected.
Transparent/coloured fills, known legend backplates, annotation text masks and
full-page white backgrounds do not supply additional outlines. There is no
snapping, gap closure or rectangular replacement of a source polygon.

The Wicker SMD/2017/0111 page-one replay now marks **eight distinct proposals**,
up from four. The additions are **Shop, Station, Maintenance and Kiosk**. Shop,
Station and Maintenance each have two identical source paints; these do not
become six buildings. Twelve literal labels have no unique qualifying white fill;
some already correspond to older linework proposals. This is a fill-recovery
hold count, not an independently checked count of missing physical buildings.
Other application sheets and the remaining linework require further review.

The Windows area-world action recomputes this review from the selected completed
job's pinned paving, layout and visible gap-label evidence, including older jobs
that predate the new overlay. It writes a fourth pinned input for the geometry
exporter. Reload recomputes the entire building review, so altered or re-signed
outline JSON is rejected. Original three-input geometry requests keep their
previous filled yellow footprint display.

With the fourth input present, the world marks each building's boundary with
light-blue concrete at ground level, keeping the interior grass and preserving
paving. The Wicker replay gives all eight proposals visible boundary samples.
There are still 7,558 paving cells, 839 oak-fence columns on paths under four
nominal blocks, and 534 reference-style rock blocks. Reported boundary-cell
counts identify any lost one-metre samples. No height, roof, entrance, surveyed
terrain, physical placement, neural weight update or training truth is inferred.
Minecraft import and gameplay remain untested; saved native blocks and archive
reopening are checked.

The module has lower-only budgets of 512 fills, 128 labels, 100,000 points,
100,000 comparisons and eight MB of review output. Quota failure clears the
candidate set and cancellation propagates. The pilot contract fingerprints the
new module and records its limits. The frozen Windows smoke starts with an
original PDF containing both width-dependent edging and duplicate painted
building footprints, then verifies the managed export's blue 2D boundary mode.
