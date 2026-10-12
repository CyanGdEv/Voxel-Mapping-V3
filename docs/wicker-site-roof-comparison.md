# Revised site-plan registration comparison

The shop-derived transform is now tested against the revised **373/95/7A** station and maintenance outlines, without fitting either additional building. Exact native candidate IDs are reproduced from attachment 163929. The revised shop outline is byte-coordinate equivalent to the previously fitted shop outline, allowing both frozen orientation hypotheses to be reused.

## Survey coverage resolved

The original crop ended at 407603 E, cutting across the mapped station complex. Its eastern boundary is extended to **407620 E**, using the same hash-pinned 2022-01-05 survey archive. The expanded crop contains **77,938 returns**. All **68,237 original point records** reproduce byte-for-byte when filtered back to the original bounds; coordinates, classifications and flags are preserved. No interpolation or coordinate adjustment was applied. Expanded-crop indices have their own namespace and must not be mixed with the original crop indices.

The search extent is the union of the original bounds and mapped station context plus a 10 m margin, rounded outward to 5 m. The map determines inspection coverage, not a fitted survey position.

## Frozen-transform result

At 1.5 m XY connectivity radius / 0.5 m height step:

| Frozen plan rotation | Station returns seeding its selected component | Maintenance returns seeding its selected component |
| --- | ---: | ---: |
| 1.36045° | 360 | 575 |
| −178.63938° | 2 | 0 |

The north-consistent hypothesis places the additional outlines over substantial class-6 building support. The reversed hypothesis does not. This provides stronger cross-building orientation context while retaining both outcomes. It does not establish measured physical corner correspondence or independently sourced checkpoints.

Projected-window maximum heights are 188.52 m ODN for the station and 190.21 m ODN for maintenance, compared with proposed section parameters of 188.7 and 190.3 m. These maxima reuse the projected windows, are not surveyed roof vertices, and do not certify the drawing's vertical datum.

## Remaining geometry blocker

Station and maintenance select **the same 1,336-return component** at the above parameters. They also share components at every combination in the nine-setting connectivity sweep. Its convex envelope includes the connected roof complex, so its boundary cannot be assigned independently to either building. Their individual outline-to-complex IoUs (22.5% / 34.8%) and boundary distances (14.49 / 17.97 m) are mismatch-of-scope diagnostics, not evidence that either drawing is wrong.

The shared component is no longer near a crop edge at the example settings. Separating native roof planes and identifying their physical edges is now the useful geometry step. Reusing two labels on one component cannot manufacture separate physical controls.

Accepted controls: 0. Accepted checkpoints: 0. World geometry additions: 0. Native edge uncertainty, physical line roles, drawing datum and separately sourced checkpoints remain unresolved.

## Replay

```sh
python scripts/extend_wicker_station_crop.py \
  --archive ../outputs/wicker-point-cloud/cloud.zip \
  --old-cloud ../outputs/wicker-point-cloud/ea-point-cloud.las \
  --receipt evidence/wicker-point-cloud-crop.json \
  --context evidence/wicker-shop-context-review.json \
  --output work/wicker-station-cloud
python scripts/compare_wicker_site_roofs.py \
  --pdf 3a8a18eb3959a39e7559309046b0815469b9f9baa52a5d1364a0cc4aa2cbb279.pdf \
  --cloud work/wicker-station-cloud/ea-point-cloud.las \
  --crop work/wicker-station-cloud/crop-receipt.json \
  --shop-fit evidence/wicker-roof-plan-review.json \
  --output work/wicker-site-roof-comparison.json
python scripts/plot_wicker_site_roofs.py \
  --review work/wicker-site-roof-comparison.json \
  --cloud work/wicker-station-cloud/ea-point-cloud.las \
  --svg work/wicker-site-roof-comparison.svg
```

The comparison retains both frozen transforms, all sweep outcomes and native component geometry. Original expanded-crop point indices are stored losslessly as zlib/base64 little-endian uint64 arrays; decoded bytes reproduce each membership hash. No quantization or geometry compression is applied. Checksum rejection, deterministic comparison replay, native component reconstruction and the 16 existing point-cloud/roof/registration tests passed.
