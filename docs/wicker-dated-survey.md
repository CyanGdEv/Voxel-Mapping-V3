# Dated Wicker survey recovery

The original Environment Agency National LIDAR archives for SK0540, year 2022,
were downloaded again on 2026-10-10. Both archive raster filenames identify
survey P_10682, captured on 2022-01-05. Unlike the recovered mixed-epoch mosaic,
this paired crop comes directly from one matched dated survey with no fallback.
The local pixel-epoch blocker is resolved for this crop. Source archive hashes,
original raster hashes, crop hashes, native grid and datum-grid hash are retained
in `evidence/wicker-dated-landmark-audit.json`.

The new archives have different byte hashes from the historical downloads. They
are independently pinned as the current acquisition, not asserted to be
byte-identical to the earlier archive. Native CRS, resolution, date, survey
identity and paired-grid equality are checked before cropping.

## Reproduce

Download the two official URLs in the receipt to `dtm.zip` and `dsm.zip`. Keep
both below the script's 100 MB archive limit. Run:

```sh
python scripts/audit_dated_wicker_survey.py \
  --dtm dtm.zip --dsm dsm.zip \
  --grid uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --osm park-osm.json --output dated-wicker-crop
```

The grid and OSM are retained V15 evidence inputs. Archive and datum-grid pins
are enforced. The script uses mapped landmarks to bound the inspection crop,
not to fit the survey or alter its native coordinates. It uses the existing
paired-survey parser to reject mismatched grids/identities, insufficient terrain
coverage and out-of-coverage requests. Missing surface pixels remain missing.
Repeated crops, observation receipts and elevated-region feeds were byte equal.

## Usable evidence and remaining review

All three comparison footprints have full finite paired coverage: 58 pixel
centres for Burger Kitchen, 26 for FastTrack and 213 for Wicker Man Shop.
Independent survey surface observations now have a specific capture date.
Neither these counts nor DSM-minus-DTM values establish roof, floor or track
geometry automatically.

The crop contains 39 unclassified elevated pixel regions of at least 8 m² at a
3 m surface-above-ground threshold. These retain actual native pixel boundaries
without snapping, gap filling or reference-footprint fitting. Trees, supports,
roofs and other objects can all produce regions; threshold corners are not
surveyed physical building corners. Missing pixels keep regions disconnected.
A region budget hit refuses a partial result. Full geometry and source hashes
are in `evidence/wicker-dated-surface-regions.json`.

The next registration work is identifying precise corresponding attachment
points on the drawing and dated survey (or clearer imagery), with appropriate
pixel/edge uncertainty. Three reviewed noncollinear controls and two separately
sourced checkpoints remain required. Multiple pixels/corners from one region do
not establish independent objects. The audit accepts zero checkpoints and adds
zero world blocks. This 2022 observation also does not establish 2026 physical
construction state or materials.
