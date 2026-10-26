# Shared building and path layouts from planning drawings

Planning source, web planning and collection jobs now retain building and
surface boundary proposals in one nominal coordinate frame per supported plan
page. Open `area-layouts.html` in Results to inspect the combined map and download
its source-linked JSON and local-coordinate GeoJSON. The coordinates are nominal
metres from printed paper scale; they are not geographic GeoJSON coordinates.

This fixes a limitation of the earlier component measurements: each component
had its own bounding-box origin, so those individual previews could not preserve
the spacing between buildings and paths. The area stage transforms every source
polygon with the same affine. It preserves the original polygon, holes and
relative positions; a bounding rectangle never replaces the geometry.

## Boundary recovery and scale

The new fine surface pass reads visible standalone path/plaza role words and
supported paving material labels. It recovers complete native straight source
faces using segments below the earlier coarse length threshold. It never snaps
endpoints, closes gaps, clips a source boundary to a scan rectangle or chooses
the nearest/smallest enclosure. A competing enclosure discovered by the coarse
pass remains ambiguous after a focused scan. Material combinations use the
existing paving palette, and unsupported roles, states and finishes remain
explicit unresolved cases. A role-only label receives a recorded display-stone
default, not a claim that the plan specifies stone.

The first supported layout contract requires one visible horizontal ground/site
plan context and one unambiguous visible scale. Roof/upper-floor plans, mixed
view sheets, cropped artwork, nonstandard PDF units, mismatching paper sizes and
incomplete geometry discovery do not produce a usable area layout. A caption
and printed scale remain evidence hypotheses; they do not verify the physical
scope or dimensional accuracy of every source line.

Building enclosures and fine component faces merge only when their polygons and
roles agree. Nested/conflicting boundaries and inconsistent existing/proposed
claims remain withheld. The relation graph records positive-length boundary
contact, point contact, overlap and the actual gap between disjoint polygons.
It does not close those gaps or infer entrances. Traversability remains unknown
without levels and entrance evidence.

Reload validation recomputes source-record hashes, label-derived roles, finishes
and states, the common scale transform, nominal polygons and relation graph.
Desktop submission also checks every selected artifact against its completed
planning job's output manifest. These are consistency checks on retained
evidence; the standalone exporter does not independently authenticate the
original PDF or certify physical geometry.

## Flat Minecraft layout preview

In **Web research**, select a completed planning job and choose **Export plan
layout**. Choose a page if several supported plans are available. The managed
worker produces `area-plan.mcworld`; use **Open world** on the completed export
to open the download page.

Paths/plazas use centre-sampled source polygons and the recorded paving palette.
Yellow one-cell markers show building footprints. **No building heights, roofs,
openings, terrain levels or surveyed park placement are invented.** The grass
platform and foundation are artificial display terrain. A block represents one
nominal source metre, so narrow paths can disappear and sub-metre gaps or edges
can change apparent connections. Candidate-level losses remain in the report.

The writer reopens every displayed cell and its headroom. Four-neighbour paving
components are recomputed from the saved database, separately from the source
polygon relation graph. The package is checksum/CRC checked and reopened after
fresh extraction, including spawn support and saved chunks. These checks do not
establish physical accessibility or Minecraft gameplay.

An advanced request uses paths relative to its JSON file:

```json
{
  "version": "planning-area-world-preview-v2",
  "layout_path": "area-layout-<document-sha>-1.json",
  "layout_sha256": "<SHA-256 of those exact saved bytes>"
}
```

Run from source with `python -m voxel_mapper.planning_area_world_preview
--config request.json --output fresh-area-world`. The Windows executable also
provides `--planning-area-smoke-test fresh-validation` for the complete managed
PDF-analysis/export/restart check.

## Bounds and validation scope

Fine surface discovery permits at most 256 source labels, 10,000 native
candidates, 200,000 native points and 500 retained faces. Area layouts permit
128 candidates, 100,000 points, 8,192 relation checks and eight MB of evidence.
Overrides can only lower the discovery/layout limits. Preview v2 partitions the
complete platform into at most four disjoint sections, each at most 128 by 128
nominal metres and 16,384 cells. The entire single-world export still permits
only 100,000 native write attempts, including its three foundation layers and
feature writes. The total platform is therefore at most 25,000 cells before
features, usually fewer. Sampling remains capped at 262,144 checks and 200,000
points. Old v1 requests retain their original single-platform limit.
Cancellation or exhausted analysis quotas cannot publish a partial successful
layout. Native export stages a fresh directory and publishes only after checks
pass; existing outputs are never overwritten.

The full managed synthetic check starts with a complete PDF, without supplied
crops or polygon recipes. It discovers two building footprints and three paving
regions, preserves the independently calculated 31.0444 m building-centroid
spacing, exports the preview, checks 149 saved paving cells in two components
(including an intentionally disconnected path), and verifies persistent restart.
This is pipeline evidence, not a real-park accuracy benchmark.

The later original-colour, text-transform and coalesced recovery stages support
46 of the Wicker site plan's 134 relevant native labels. They produce three
building-footprint and two material-surface proposals in one nominal frame.
The [tiled preview stage](tiled-area-world-previews.md) now exports that unchanged
196×115 m layout. Its eight material display cells are not verified paths or a
complete paving network. No neural weights, reviewed training labels, accepted
park geometry or complete 3D buildings are produced.

Next work is reliable interpretation of those original annotations, more complete
path boundaries, plan/elevation correspondence for heights and roofs, and checked
area placement and terrain levels. A separate untouched area with measured
reference geometry is still required before claiming autonomous accuracy.
