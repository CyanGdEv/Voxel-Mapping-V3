# User path boundaries, trees and pond guidance

The user's annotated Towers Street / Mutiny Bay image is retained unchanged.
Its legend is red for projected path boundary points, green for tree locations,
and blue for the pond. The importer recovers **241 red, 47 green and 6 blue
markers** and records their native reference coordinates, clean-image
coordinates, IDs and source hashes. These are user-authored points; automatic
extraction, continuous edges and physical registration have not been reviewed
or surveyed independently.

Green markers describe overhead trees, not a ground-surface class. Their drawn
size is not interpreted as crown size. Blue points establish the pond's location;
their convex hull is not promoted to an exact shoreline. Sparse red points do
not automatically define closed polygons, junctions or which nearby edges join.
In particular, unmarked narrow routes must not become known non-paving merely
because the image lacks a dot there.

## Clean-image registration

The marked image is 1280 × 511 pixels. A separately retained Esri source is
1280 × 512. Feature matching excludes the need to feed coloured markup to the
network: 1,434 image-feature matches support the final transform, with median
residual 0.536 and 95th-percentile residual 1.081 clean-image pixels. These
numbers measure image alignment, not surveyed map accuracy. The original
Towers source separately provided 409 supporting matches.

The clean export samples approximately 0.446 m/pixel; provider point metadata
reports 0.5 m imagery dated 27 May 2023. No resolution upgrade or full-mosaic
date/registration verification is claimed. Esri World Imagery/provider attribution
and the original receipt accompany the download. The marked image is retained
as the user's reference; its metadata is not silently replaced by Esri metadata.

The source-matching experiment used SIFT from OpenCV 4.10.0.84. OpenCV was used
only for preparing this registration; the saved-transform importer, training,
gap rule and installed project do not require a new OpenCV dependency.

## Training performed

The new checkpoint learns **projected path boundary presence**, not ground
paving classification. Model input is exclusively the separately pinned clean
RGB/context features. The marked image supplies coordinates and labels only.
The dedicated checkpoint version and labels prevent it from being loaded as a
binary paving model. Existing paving and five-class checkpoints are unchanged.

Positive samples lie within 1.5 pixels of extracted red markers. Derived
non-boundary examples use six/nine-pixel offsets along local boundary normals,
only when several nearby markers establish a local tangent. They remain
assistant-derived negatives, not user-authored ground truth. Unmarked areas
outside those sparse samples stay unknown. The green and blue points currently
inform mapping layers and ground exclusions; this stage does not train separate
tree or water segmentation networks.

The CPU experiment fits a 64-unit binary head for 90 epochs. Its left-hand
training region contains 5,932 samples. The right-hand spatial check contains
1,915 samples, with a 32-pixel guard on each side of the split; the largest
context radius is 27 pixels. The final research checkpoint fits all 8,501 known
samples. Training used two CPU threads, approximately 302 MB peak process RSS
and 7.23 seconds in this environment. Parameters changed by L2 24.15 relative
to initialization.

| Right-hand spatial check | Result |
| --- | ---: |
| Boundary precision | 17.47% |
| Boundary recall | 44.48% |
| Boundary F1 | 25.08% |
| Always-boundary reference F1 | 30.46% |

This is a **weak same-site development result**, below the constant reference.
It does not establish improved accuracy on other parks or continuous boundaries.
The final all-guidance preview has seen these labels and is not a test result.
The model stays a research checkpoint; it does not replace the existing paving
model or justify automatically accepting new world geometry. One annotated
image and sparse derived negatives are insufficient for that claim.

## Tree-over-path rule

The user's additional instruction is implemented as a ground-layer rule:
where a tree overlaps an **established path footprint**, continue that path
under the canopy. Retain the overhead tree layer separately. Record the added
ground as `inferred_path_under_canopy`, not observed paving.

`fill_tree_gaps` requires a connected allowed footprint with a visible path
anchor. It never fills outside that footprint or across building, water or
bounded grass-island exclusions. A nearby tree with no established path does
not create a new path. This allows overlapping trees and paths without teaching
that every green location is grass or that every tree hides a pedestrian route.

The source demonstration uses the existing provisional Towers Street footprint,
known canopy traces and a provisional 3.5 m fallback buffer at user tree points.
The buffer is an assumption, not a recovered canopy outline. It adds **711
native pixels beneath canopy**, with zero additions outside the established
footprint and zero final path pixels in the hard exclusions. Inferred pixels
are not mixed into observed neural training labels. The pond exclusion uses the
existing bounded island outline at the user's blue pond location; its shoreline
remains provisional. Mutiny Bay points are retained and mapped, but this stage
does not invent complete closed path polygons there.

## Inspect and reproduce

The download contains the original marked reference, unmarked RGB/receipt,
registration, all point coordinates, projected EPSG:3857 GeoJSON, ground and
canopy masks, trained checkpoints, sparse supervision and the source-only viewer.
No world blocks or Windows executable were generated.

With the project installed, from the package root:

```sh
python -m voxel_mapper.user_path_supervision \
  --reference user-reference.jpg --clean clean-source/source-image.bin \
  --metadata clean-source/imagery-receipt.json \
  --registration registration.json --output fresh-boundary-training
```

The command does not access consumed Paultons or LEGOLAND test data. Its report
explicitly identifies the spatial-check limitations and the derived negatives.
The reference and clean-source hashes must match the registration before any
fitting. Source-receipt/hash tampering and marked-image substitution are rejected.

The next useful evidence is explicit edge connections, path-side/interior labels
and further annotated areas, especially small paths beside roofs and vegetation.
That can turn these precise local hints into supervised continuous geometry;
increasing epochs on this one image is not evidence of better generalization.
