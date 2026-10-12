# Native station-complex roof plane extraction

The shared 1,336-return building component has been partitioned into **seven native plane patches** using deterministic bounded RANSAC and least-squares refinement. Plane fitting uses native XYZ only; planned footprints do not fit or clip the planes. Connectivity subsequently separates disconnected support patches. Original crop indices and fitted coefficients are retained.

Points within tolerance of multiple planes are withheld from patch boundaries. This prevents peel order from assigning a ridge/intersection point to whichever plane was fitted first. Convex support envelopes still bridge holes and do not establish physical eave boundaries.

## Sensitivity sweep

| Vertical residual tolerance | Patches | Assigned returns | Ambiguous returns | Unassigned returns | Ridge-like intersections |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.08 m | 7 | 1,190 | 59 | 87 | 3 |
| 0.12 m | 7 | 1,193 | 98 | 45 | 3 |
| 0.18 m | 7 | 1,149 | 163 | 24 | 3 |

All runs also identify two valley-like intersection candidates. These are mathematical classifications based on patch slopes and support locations, not verified physical ridge or valley identities. Larger tolerance can increase ambiguity and therefore reduce assigned support.

At the 0.12 m inspection setting the two large paired roof slopes are approximately 26–27 degrees. The third pair is approximately 30 degrees; a small near-horizontal patch is also retained. Candidate ridges are intersections of fitted planes, restricted to buffered observed support. The 0.75 m buffer is a contact search margin, not an uncertainty certificate. Ridge endpoints may extend beyond observed support within that margin.

## Frozen drawing comparison

Each ridge-like pair's convex envelope is compared with the previously frozen north-consistent site transform. No source or survey geometry is moved to improve the overlap.

| Planning outline | Best pair support | Envelope overlap | Boundary Hausdorff difference | Candidate ridge height |
| --- | ---: | ---: | ---: | ---: |
| Station | 309 returns | 89.8% | 1.30 m | 188.54–188.55 m ODN |
| Maintenance | 706 returns | 73.9% | 5.72 m | about 190.23 m ODN |

This separates the native plane surfaces that the earlier connectivity envelope merged. It does not certify the names or full physical building boundaries. The maintenance mismatch requires an explicit roof/wall-offset, drawing-version or as-built explanation; it is not corrected by stretching or translating the drawing.

Membership stability and boundary differences between tolerances are retained for every primary patch. Some smaller patches vary substantially. Those changes measure algorithm sensitivity, not survey accuracy. Native edge uncertainty remains unset. Plane residuals, fitted ridge heights and same-survey comparisons cannot replace independent controls or checkpoints.

Accepted controls: 0. Accepted checkpoints: 0. World geometry additions: 0.

## Reproduce

```sh
python scripts/extract_wicker_roof_planes.py \
  --cloud ../outputs/wicker-station-cloud/ea-point-cloud.las \
  --review evidence/wicker-site-roof-comparison.json \
  --output work/wicker-native-roof-planes.json
python scripts/review_wicker_roof_planes.py \
  --planes work/wicker-native-roof-planes.json \
  --site evidence/wicker-site-roof-comparison.json \
  --output work/wicker-roof-plane-correspondence.json
python scripts/plot_wicker_roof_planes.py \
  --planes work/wicker-native-roof-planes.json \
  --site evidence/wicker-site-roof-comparison.json \
  --svg work/wicker-native-roof-planes.svg
python -m unittest tests.test_roof_planes tests.test_roof_candidates \
  tests.test_roof_plan_review tests.test_point_cloud tests.test_wicker_registration
```

The reusable `voxel_mapper.roof_planes` module caps native component size, RANSAC trials, plane count and aggregate comparison work. Source component encoding, point indices, classifications and native envelope are verified before fitting. Synthetic tests cover adjacent gables at different heights, ridge ambiguity, unassigned outliers, unchanged source arrays, deterministic results and invalid/budget inputs. All 20 focused tests passed. Native receipts replayed byte-for-byte; patch support, residuals and intersection equations were checked against the original return records.
