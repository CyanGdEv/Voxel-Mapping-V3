# Image-local aerial feature supervision

Three user-annotated Alton Towers references now have independent, checksum-bound legends. Colour meanings are never global:

| Reference | Colour | Meaning |
|---|---|---|
| Galactica | Yellow | Monorail |
| Galactica | Purple | Coaster track |
| Image 1, The Smiler area | Purple | Coaster track |
| Image 1 | Red | Theming structure |
| Image 1 | Cyan | Support structure |
| Image 2, Towers Street | Purple / dark purple | Fence or barrier |
| Image 2 | Light purple around islands | Rock boundary |
| Image 2 | Yellow | Monorail |
| Image 2 | Red | Path trace |
| Image 2 | Orange | Theming structure |
| Image 2 | Small green dots | Grass-island locations |
| Image 2 | Larger green dots and outlines | Tree features |

Earlier purple building/roof examples retain their existing meaning. The latest small-green-dot correction is retained: a compact isolated small marker is a grass-island location, rather than a tree. Tiny dashes belonging to a larger tree outline remain tree features. The automatic source-pixel size and isolation thresholds are digitisation choices, not independently human-verified thresholds. The supplied image yields one tiny isolated grass marker near source pixel `(451, 529)`; its extent is not inferred. Larger filled dots and tree outlines stay separate. Empty or unmarked pixels are ignored, including any legend colour without qualifying marks; no red path pixels were extracted from image 2 after the orange-theming clarification.

Every reference is matched to independently acquired clean Esri RGB using unpainted texture. Image 1 was located in the full-park image before acquiring its detailed crop: its registered centre is approximately E407119, N343321, in The Smiler area. Final fits have 960 inlier features for image 1 and 703 for image 2, with 95th-percentile residuals of 1.24 and 1.02 clean-image pixels. Their rotations relative to north-up are about 18.29° and 11.30°. The Galactica fit has 210 inliers and a 1.60-pixel residual, with a 94.87° rotation. These are image-matching diagnostics, not surveyed physical accuracy.

The output stores the original ink mask, a nearest-neighbour registered sparse target, clean RGB, source receipts, class/legend metadata, projected BNG review points and a registered overlay. All unmarked target pixels use ignore value `255`. Marker thickness does not become a measured structural width. Open strokes do not close into polygons; points do not fill grass islands or tree canopies; projected line intersections do not become physical joints. Overlapping colour rules for different classes raise an error.

The two new references also have terrain, surface and above-ground height features sampled from the same native 1 m BNG/ODN rasters as the park world. A sampled RGB pixel does not imply finer measured height resolution. The Galactica crossing study additionally retains raw classified LiDAR and unresolved height groups, as described in [Galactica supervision](galactica-aerial-supervision.md). No training height labels, support heights or source connectivity are inferred from colour alone.

Use the `mappingreview` optional dependencies:

```sh
python -m voxel_mapper.aerial_feature_supervision \
  --reference user-reference.jpg --clean clean-rgb.png \
  --receipt imagery-receipt.json --frame frame.json \
  --legend voxel_mapper/data/smiler-aerial-legend.json \
  --dtm ea-national-dtm.tif --dsm ea-national-dsm.tif \
  --output FRESH-OUTPUT
```

Use `towers-street-aerial-legend.json` for image 2. Source hashes and dimensions are checked before extraction, each legend remains image-local and output must be fresh. The generated labels are reviewable supervision candidates. Clean RGB alone supplies image features; source annotation colours are never model input. Automatic pixel extraction remains unverified even when the user confirms a colour meaning. No weights are trained and no existing world blocks are changed by intake.

Validation includes the red/orange distinction, image-local purple meanings, small grass markers versus tree-outline dashes, ignored background, conflicting colour roles, rotated clean-image matching, pixel-centre reprojection and unchanged earlier path/building supervision. The delivery retains three exact target-mask replays, native-height sampling checks and independent raw-return crossing queries. Source imagery and large height/cloud arrays remain task artifacts outside Git.

Attribution: user-supplied markings, Esri World Imagery/providers, OpenStreetMap contributors (ODbL-1.0), Environment Agency information (OGL-UK-3.0). Source dates differ; absolute physical registration, complete structural dimensions and training improvements remain unverified.
