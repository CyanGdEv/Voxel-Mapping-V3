# Wicker shop imagery comparison

The retained 2023-05-27 shop-location imagery is now overlaid with the two existing stable LiDAR roof/canopy hypotheses and the mapped adjacent complex. The main roof candidate is visible, but the narrow rear attachment zone cannot be cleanly separated from roof edges, shadows and adjacent structures. Neither canopy identity nor orientation is independently resolved.

The overlay uses the original four JPEG tiles unchanged. Coordinates pass through the pinned OSTN15 datum transformation and Web Mercator tile transform. No image translation, rotation, scale adjustment or manual control point was fitted. Cyan marks the provisional main roof, yellow the NE canopy hypothesis, pink its opposite, and orange the mapped adjacent complex. Lines are clipped to the image extent. These are projected hypotheses, not traced as-built boundaries.

Source resolution is 0.5 m; the shop-point citation reports 8.47 m positional accuracy. That accuracy exceeds the 1 m registration gate. Surrounding mosaic pixels do not have independently verified acquisition dates. OSM and the LiDAR fit already contributed to these hypotheses, so their appearance in this image does not create independent checkpoints.

## Reproduction

Run from the repository root with Python dependencies pyproj and shapely:

```sh
python scripts/overlay_wicker_imagery.py \
  --context evidence/wicker-shop-context-review.json \
  --lidar evidence/wicker-shop-model-lidar-review.json \
  --imagery evidence/wicker-shop-imagery-context.json \
  --svg docs/wicker-shop-imagery-context.svg \
  --grid ../inputs/survey-recovery/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output evidence/wicker-shop-imagery-overlay.json \
  --output-svg docs/wicker-shop-imagery-overlay.svg
```

Inputs are hash pinned. The receipt retains the datum pipeline, mosaic transform and projected pixel coordinates. Validation covers deterministic replay, source-image byte preservation, coordinate round trips and rejection of altered source metadata.

## Placement consequence

Accepted controls: 0. Accepted checkpoints: 0. World geometry additions: 0.

This inspection exhausts what this imagery can establish about the canopy. The next useful input is an independently positioned survey or drawing that supplies physical registration controls and checkpoints, plus dated rear shop imagery or an as-built plan for the attachment. The roof, wall and canopy models remain provisional until those requirements are met.
