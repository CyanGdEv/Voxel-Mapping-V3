# Wicker Man: original footprint to centreline supports

The user rejected the previous frames' positions. This correction replaces the
entire support layer with dark oak fences only. Each member starts in the metre
cell containing an original brown footing-symbol centroid, at retained ground
height, and ends below the corresponding branch's centre deck. No arbitrary
footings, transverse beams, longitudinal links, gates or trapdoors are added.

The old grouping could combine two crossings of the centreline, then average
their chainages. That put the group on an unrelated route segment. The correction
uses actual native brown cross-line intersections with individual source route
segments. A footing follows its original connected cross-lines to a centreline
intersection; shortest graph distance assigns outer feet through their main-row
foot. Competing branches within 0.75 m graph distance are withheld. Components
without a source cross-line intersection remain unresolved. No group-average
station or lowest-deck selection determines a member endpoint.

The endpoint uses the final centre-sample key and solid-step deck underside of
that exact branch. Each complete voxel member is checked against original terrain,
retained architecture, every track deck and three blocks of clearance over the
whole deck width. Fence collision height is included. If an upper-track member
would pass through a lower track or its walking/riding clearance, the entire
member is omitted and reported. It is not clipped into a floating piece or given
an invented detour. A fence may meet its own target bearing.

## Dated LiDAR review

The January 2022 EA P_10682 tile is re-downloaded from the retained catalogue URL.
The ZIP has the same length and tile name but a different container checksum from
the earlier download. Before use, scanning all 98,342,681 returns must reproduce
the previous 68,237-return raw crop byte-for-byte (SHA-256 `78524af74e857a866fa6cc68bf8970600fbfc5ad0917dd4d0def1530760b0584`).
The new archive checksum and both crop receipts are retained explicitly.

The expanded crop covers the full ride, rather than the earlier shop/station
window. Native XYZ, classification, withheld and synthetic flags are preserved.
The retained nominal-plan-to-BNG transform places it in the current world frame;
that map registration is not independently surveyed. Every stacked deck column
gets a local height-band/classification review, with nonvegetation counts kept
separate. Sparse returns, trees and upper-deck occlusion do not prove a lower
track is absent, and do not justify averaging track elevations or identifying
hidden timbers. LiDAR supplies review context; it does not silently alter track
heights or override ambiguous source branch assignments.

## Replay

Use the existing pinned solid-step track parent and original landscape inputs:

```sh
python -m voxel_mapper.fence_support_world --style footprint \
  --base-directory PATH/solid-step-track \
  --markings-path PATH/inputs/source-markings.json \
  --pdf-path PATH/inputs/original-landscape.pdf \
  --cloud-path PATH/lidar/ea-point-cloud.las \
  --cloud-receipt PATH/lidar/crop-receipt.json \
  --output FRESH-DIRECTORY
```

The `reference-crop.las` file alongside the new cloud must reproduce the retained
raw checksum. Old dense/reference styles remain explicit replay options.

The diagonal fence members are a metre-grid placement prototype, not verified
as-built engineering. Existing track heights and architecture are preserved.
Client import and visual appearance require an in-game review.

The retained expanded-crop receipt is `evidence/wicker-support-cloud-crop.json`.
The current export places 546 complete members (536 unique metre-grid ground
positions), using 2,855 dark oak fence cells. It reports 331 omitted footprints:
123 without a native cross-line-to-centre intersection, 19 ambiguous between
branches, 84 without ground clearance and 105 blocked by retained geometry or
terrain. All 74 stacked deck columns have dated LiDAR context in the report.
