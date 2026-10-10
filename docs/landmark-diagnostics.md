# Explicit landmark diagnostics

`python -m voxel_mapper.landmark_diagnostics` investigates a selected native
polygon/reference correspondence without accepting a placement. Required CLI
arguments are `--corpus`, `--candidates`, `--references`, `--target-crs`,
`--document-sha256`, `--candidate-id`, `--reference-id` and `--output`.
Optional `--page` defaults to 1 and `--reference-crs` to EPSG:4326.

The command verifies source PDF bytes and the exact retained current extraction
records on the selected page. It tries distinct equivalent boundary orientations
and compares every retained polygon against mapped polygons within the centroid
search tolerance. Outputs retain candidate/reference IDs, transform matrices,
outline IoU, centroid errors, distinct nonoverlapping matches, the top twenty
subthreshold comparisons per orientation and input hashes. Nested outlines and
repeated IDs cannot inflate the distinct match count.

This command is a diagnostic fallback for an explicit reviewer-selected seed.
It leaves generic automatic placement and verified registration thresholds
unchanged, does not refit to additional objects and exports no positioned
feature feed or world blocks. A match is comparison evidence, not confirmation
of construction state, material, line role, survey control or checkpoint identity.

## Retained SW8 result

The proposed woodland-path site plan, PDF
`1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`,
page 1, contains shop candidate
`c631c9fa7adff4f77172e3d30eac1cf566847a40d391ddad7b18a596a7d7be52`.
It was selected by visually inspecting the site plan and the enclosing building
outline, not the smaller label-shaped polygon also containing the text centre.
Its mapped comparison is `osm/way/834919978` (Wicker Man Shop).

The shop ranks 324th under the generic seed ordering, outside its first 64
objects. The correct reference ranks second by descriptor. Thus increasing the
reference shortlist would not fix this missed seed. A direct boundary fit gives
99.21% shop IoU and 0.044 m boundary Hausdorff distance, which describes agreement
with this mapped outline, not absolute positioning accuracy.

The best orientation gives two nonoverlapping outline matches: Wicker Man Shop
and Burger Kitchen (79.72% IoU, 0.74 m centroid difference). FastTrack is nearby
but only 56.3% IoU; it is retained as a subthreshold comparison. Four distinct
orientation trials have match counts 2, 1, 1 and 2. The second two-match orientation
is a slightly different fit at the same approximate location, not independent
corroboration. No result supplies three noncollinear object matches, much less
three reviewed controls and two separately sourced checkpoints.

## Next concrete evidence

Review the FastTrack footprint and surrounding existing buildings against the
same sheet's revision and source paint paths. Determine whether mismatch comes
from a changed building, different physical outline, source clipping or incomplete
mapped footprint. Do not lower the IoU threshold to count it. Retrieve an
independent georeferenced survey or image with measurable attachment points;
OSM shop corners and Burger Kitchen centroids remain map comparisons. A current
accepted physical feature, measured dimensions and vertical data are still
required before compilation and world export.

Receipt: `evidence/wicker-shop-landmark-diagnostic.json`.
