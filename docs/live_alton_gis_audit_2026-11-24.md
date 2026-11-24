# Live Alton Towers GIS audit, 2026-11-24

Audited PR #171 at `c8e61b8a78e99993e6cf537a7bee8e98d52cdb54`,
stacked on PR #170 at `5a1b655c220cf88b2d24ebe885ea876fd4a54b06`.
Both are open drafts. Parent Actions run 45225388483 passed. Latest child
runs 45510446482 and 45510446318 failed; logs confirm missing Pillow
in the basic suite and source ZIP corruption in context packing. The
separate training smoke job passed. No branch was merged.

## Implemented fixes

- Copy `ZipInfo` before writing: Python mutates header offsets on the supplied
  object, which previously corrupted subsequent source reads. Regression now
  checks every output member, RGB/mask preservation, and repacking.
- Install GIS and Pillow dependencies in the basic test workflow.
- Persist per-source AOI results with SHA-256 integrity, source registry and
  feature-budget keys, configurable expiry (default one day), and acquisition
  timestamps retained on cache hits. Partial/unavailable sources are retried,
  rather than cached as complete. This is acquisition caching, not an accepted
  reconstruction database.
- Separate HTTP sessions per worker, three transient HTTP/connect retries with
  backoff, bounded feature batches, and configurable 1–8 workers (default 3).
- Add `tools/acquire_gis_pilot.py` to reproduce acquisition, aligned context and
  a training catalog. `--require-complete` rejects partial/unavailable sources.

## Actual requests and results

WGS84 bounds: `[-1.903, 52.983, -1.88, 52.995]`. All seven configured
ArcGIS endpoints returned usable park-specific evidence. These counts are
clipped source records, **not independent observations or verified structures**.

| Source | IDs matched | Accepted | Status |
|---|---:|---:|---|
| OS OpenMap Local buildings | 186 | 186 | available |
| OS Open Rivers | 2 | 2 | available |
| Living England Phase 4 | 180 | 175 | partial |
| National Forest Inventory | 9 | 9 | available |
| Historic England listed points | 35 | 34 | available |
| Historic England listed polygons | 35 | 34 | available |
| Historic England parks/gardens | 1 | 1 | available |

Total: 441 features. Habitat object IDs 4988974 and 4989297 have invalid
geometry and remain rejected. Three other habitat records and one record
from each listed-building layer have empty/touch-only clipped geometry.
No geometry repair was silently accepted. Partial habitat areas remain unknown
outside accepted features in the context grid. Vector resolution, positional
accuracy, observation dates and real-world completeness are not established
by successful service queries; retrieval dates must not be used as capture dates.

The 2025 Sentinel-2 categorical export succeeded: 257 × 223 pixels in
EPSG:3857, nominal product resolution 10 m, requested projected spacing 10 m.
All 57,311 pixels were usable: water 466, trees 18,906, crops 5,558,
built area 14,002, rangeland 18,379. These counts include the rectangular
export extent, not an independently surveyed park boundary. Projected spacing
in Web Mercator is not ground spacing. The metric context grid has eight
source channels, 268 rows × 310 columns, at 5 m spacing; resampling adds
no source detail. The packer converts these into its fixed 25 contextual
channels alongside RGB, retaining unknown LiDAR masks.

A repeated run reused all six complete vector source cache entries and
reacquired the partial habitat source. SHA-256 checksums accompany the dataset
reports and acquisition summary; the delivered evidence ZIP contains the actual
GeoJSON, land-cover TIFF, aligned NPZ, catalog and service metadata.

## OS polygon download blocker

The official `https://api.os.uk/downloads/v1/products/OpenMapLocal/downloads`
API returned HTTP 200 and advertised the SK shapefile tile (137,251,364 bytes,
MD5 `91a53b418f347a6e80570deb74bb8f46`). Its signed redirect targets
`omseprd1stdstordownload.blob.core.windows.net`; the proxy refused the tunnel
with HTTP 403. A direct connection with proxy settings disabled also failed.
The environment reports unrestricted networking. No tile was acquired and
automatic OS water/woodland polygon processing remains unimplemented. The
listed ArcGIS registry does not expose equivalent OS polygon services; guessed
service names returned invalid-URL errors. Rivers are centre lines, not water polygons.

## Training and world integration gates

Neither georeferenced training ZIP, the offline experiment archive, nor a
baseline `.mcworld` exists in this workspace. Real chip attachment, full
benchmark/ablations and accepted prediction placement therefore did not run.
No production checkpoint was promoted; **zero Minecraft blocks changed**.
The 26-test local regression suite includes actual one-epoch synthetic paired
3/28-channel CPU training; that test is not a real park benchmark.

The PR stack and main contain only the small voxel-record exporter. Inspection
of the fetched branch `codex/alton-reference-world-v3` at
`e923af594a6685bbdc86af4448d5daa3565c19b6` found the existing
`voxel_mapper/bedrock.py::export_world`, `world_surface_layers.py`,
`surface_segmentation.py` and the Alton reconstruction pipeline. The Bedrock
writer composes feature/material records, requires 1 m voxels, writes native
LevelDB chunks with Amulet, and verifies written blocks and unwritten air.
It creates a fresh export and refuses an existing target; it is not an
incremental baseline editor. That branch requires NumPy <2 and rasterio <1.5,
unlike the current GIS stack's permitted NumPy 2 runtime. Do not duplicate it
or merge its dependency stack without isolated integration validation.

The existing training split is source-group based; geographical independence
and buffers must be checked against the actual archive before any benchmark.
The 320 Alton rotations must not be split as independent validation samples.

## Reproduction

```sh
python -m pip install -e '.[gis]' 'Pillow>=10,<13'
python -m pip install 'torch>=2.4,<3' --index-url https://download.pytorch.org/whl/cpu
python -m unittest discover -s tests -v
python tools/acquire_gis_pilot.py --config examples/alton_gis.json \
  --output output/alton-live --park-id alton_towers
# After the actual registered archive is supplied:
voxel-pack-multisource --dataset Alton_Towers_Georeferenced_Ground_Training.zip \
  --catalog output/alton-live/training-catalog.json --output output/alton-context.zip
```

The generated catalog includes GIS/land cover only. Matching dated DTM, DSM
and raw intensity rasters still need acquisition, validation and catalog entries
before any claim that all modalities have real evidence.
