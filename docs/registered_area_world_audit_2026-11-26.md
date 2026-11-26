# Registered-area world audit, 26 November 2026

The repair audit now covers all four existing registered source groups. It found
**zero additional qualified block changes**. The latest separate preview remains
the classified-LiDAR courtyard world with 38 cumulative changes in 19 lawn
columns; no unchanged world was exported as a new improvement. No model was
trained or promoted during this cycle.

## Executed evidence audit

The 47 chips in `alton-broad-area-context-v2.zip` contain 8,615 labelled window
observations. Merging by native metre cell removes 6,282 overlapping observations,
leaving 2,333 unique cells: 474 grass and 1,859 unspecified paving, with zero label
conflicts. There are 786 cells inside the existing two-cell class erosion.
Overlapping chips do not become independent evidence or validation examples.

The new `prepare_area` command reuses single-chip grid, CRS, pixel-centre and
height checks. It refuses mixed dataset/registration/raster identities and
inconsistent overlap heights or coordinates. Conflicting classes stay ignored,
even if later chips agree with an earlier label. Merging never grants write
acceptance; an explicit hash-bound scoped review is still required.

| Existing source group | Unique cells | Grass | Paving | Distributed ground observations |
|---|---:|---:|---:|---:|
| `geographic_63b0ff5ef1ff` | 827 | 70 | 757 | 34 |
| `geographic_1bcc4fca1552` | 1,170 | 291 | 879 | 15 |
| `geographic_1f2030b78bd1` | 100 | 0 | 100 | 12 |
| `geographic_299b80e09090` | 236 | 113 | 123 | 16 |

The complete cropped EA cloud was scanned: 10,537,336 points, including 6,251
returns in requested cells. Seventy-seven cells meet the existing distributed
ground criterion. These are observations from the same 2022 survey lineage as
the rasters, not independent evidence votes or calibrated absence probabilities.
Vectorized membership filtering reproduces the prior 236-cell courtyard audit's
counts, classifications, quadrant and support decisions; numerical spans agree
within 1e-7 m. Half-open cell boundaries remain enforced before linear indexing.

| Planner outcome | Cells |
|---|---:|
| Outside reviewed surface interior | 1,547 |
| Retained overhanging vegetation | 82 |
| Observed elevated returns | 75 |
| Vertical quantization residual | 403 |
| Negative surface height remains unknown | 174 |
| Measured above-ground geometry | 10 |
| Already matches | 36 |
| Unverified ground material | 6 |

All 82 previously opaque native-column exclusions have complete supported
storage scans and oak leaves above the recorded ground-height entry. The
inspector now reports both observed non-air top and height metadata, identifying
retained canopy explicitly. This does not diagnose a corrupt heightmap, authorize
tree removal, or change the writer's guards. Legitimate canopy over paths stays.

A read-only diagnostic with vertical residual thresholds of 0.10, 0.25 and 0.50 m
found zero new candidates at every setting (36, 120 and 406 already-matching
cells respectively). The production threshold remains 0.10 m.

## Registration and acquisition retries

All 19 remaining unregistered views were retried at matching long sides 768 and
1536 with unchanged acceptance gates. Neither run produced a validated candidate.
Failures include insufficient distinct matches, limited spatial control,
weak consensus and withheld checkpoint errors. No transforms were written;
327/346 registered samples remain available. This is source-relative alignment,
not independently surveyed absolute accuracy.

The official OS downloads listing returned HTTP 200 and 169 records. The SK
OpenMap Local shapefile archive is advertised as `opmplc_essh_sk.zip`,
137,251,364 bytes. Following its fresh official redirect failed at proxy CONNECT
with HTTP 403 for `omseprd1stdstordownload.blob.core.windows.net`. No archive or
water/woodland features were acquired. The environment reports enforced
unrestricted network policy and connected connectivity; no missing task domain
grant was identified. The exact rejecting proxy rule remains unknown. Proxy and
TLS controls were preserved. Temporary download query tokens are omitted.

Listing: <https://api.os.uk/downloads/v1/products/OpenMapLocal/downloads>.

## Reproduction

Run from the repository with the existing source files. Each output must be new.
The inspection step uses the isolated pinned Bedrock runtime; other steps use
the GIS runtime. `--group` can be repeated to scope preparation.

```sh
python -m tools.plan_surface_repairs prepare_area \
  --dataset /workspace/data/alton-broad-area-context-v2.zip \
  --registration /workspace/evidence/alton/world-registration.json \
  --dtm /workspace/evidence/alton/ea-2022/ea-national-dtm.tif \
  --dsm /workspace/evidence/alton/ea-2022/ea-national-dsm.tif \
  --include-paving --output /tmp/area-requests.json
python -m tools.audit_surface_returns \
  --requests /tmp/area-requests.json \
  --registration /workspace/evidence/alton/world-registration.json \
  --source /workspace/evidence/alton/ea-2022/lidar-evidence.json \
  --cloud /workspace/evidence/alton/ea-2022/ea-point-cloud.las \
  --output /tmp/area-returns.json
/workspace/bedrock-venv/bin/python -m tools.plan_surface_repairs inspect \
  --requests /tmp/area-requests.json \
  --baseline /workspace/experiments/Alton_Towers_Courtyard_Classified_LiDAR_Preview.mcworld \
  --output /tmp/area-observations.json
python -m tools.plan_surface_repairs propose \
  --observations /tmp/area-observations.json --cell-returns /tmp/area-returns.json \
  --output /tmp/area-proposals.json
```

The compact machine-readable results are in
`registered_area_world_audit_2026-11-26.json`. Local full audit reports are under
`/workspace/experiments/registered-area-cycle/`; registration retries are under
`/workspace/experiments/registration-scale-2026-11-26/`.

Regression validation: 66 tests pass with three optional native skips; all five
native tests pass in the separate pinned runtime. No Minecraft client
import/play/save test was performed. No new independent final AI test labels,
whole-park accuracy claims or world changes result from this audit.

Latest world SHA-256:
`4825dadc4a0e0d4e3874affff1583dba0d631280a79b3e7af1bd9ca4a73f1ae1`.
Original world SHA-256:
`0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
