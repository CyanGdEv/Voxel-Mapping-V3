# Dated Wicker point-cloud classification audit

The official Environment Agency search catalogue advertises the 2022 SK0540
National LIDAR point-cloud tile. Its downloaded ZIP contains exactly
`SK0540_P_10682_20220105_20220105.laz`, matching the dated terrain/surface survey.
The native metre BNG header is checked before cropping. ODN is based on the
published dataset declaration, not inferred from the horizontal CRS.

Source: https://environment.data.gov.uk/tiles/collections/survey/national_lidar_programme_point_cloud/2022/1/SK0540

The 384,483,857-byte archive has SHA-256
`2bd911d556739978915046d94037c206cdb60811c2e2dfd6da48b24ce83135dc`.
Scanning 98,342,681 returns retained 68,237 in the exact dated raster crop bounds
407461–407603 E, 343478–343627 N. Raw XYZ, classifications and flags are preserved.
No spatial interpolation or building extrusion is performed. The archive is
external evidence; neither it nor the binary crop is committed to Git.

## What the classifications resolve

The crop contains 8,776 class-6 building returns overall. Counts below use the
retained mapped outlines as comparison windows, with the checked OSTN15 grid.
Eligible means neither withheld nor synthetic. The three-metre margin excludes
the inside of the outline. It is a search window, not a physical error bound.

| Comparison landmark | Eligible class-6 inside | Eligible class-6 in margin | Other inside returns |
| --- | ---: | ---: | --- |
| Wicker Man Shop | 442 | 107 | 2 unclassified, 22 ground, 1 high vegetation |
| Burger Kitchen | 0 | 0 | 4 unclassified, 171 high vegetation |
| FastTrack | 0 | 0 | 14 ground, 49 high vegetation |

The shop therefore has directly classified building support for subsequent
roof-edge analysis. Burger Kitchen and FastTrack do not provide equivalent
class-6 support, even within the margin. Vegetation classification is evidence
of the source labels; it does not prove these buildings are absent, or that every
label is correct. Classification accuracy, physical roof identity, roof-to-wall
offsets and edge uncertainty remain unverified.

Zero controls, checkpoints or world geometry additions are accepted. This
survey is dated 2022, not a claim about current park construction. Next, analyse
the shop's building returns for a stable roof boundary, and obtain independent
physical checkpoint evidence for registration. A three-landmark registration
cannot be justified by this classification audit alone.

## Replay

Download the source ZIP to `cloud.zip`, then use the pinned retained catalogue:

```sh
python scripts/crop_wicker_point_cloud.py \
  --archive cloud.zip \
  --catalogue evidence/wicker-point-cloud-catalogue.json \
  --receipt evidence/wicker-point-cloud-crop.json --output cloud-crop

python scripts/audit_wicker_point_cloud.py \
  --cloud cloud-crop/ea-point-cloud.las \
  --crop-receipt evidence/wicker-point-cloud-crop.json \
  --survey-receipt evidence/wicker-dated-landmark-audit.json \
  --osm park-osm.json --grid uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output audit.json
```

The retained V15 OSM and grid hashes must match the dated survey receipt.
Cropping verifies archive/catalogue bytes and the survey-matched filename,
then requires the same crop checksum and point count. The audit verifies crop,
grid, OSM, survey identity and bounds before recording classifications. Replays
do not contact a mutable catalogue or silently select a newer survey.

Receipts: `evidence/wicker-point-cloud-crop.json`,
`evidence/wicker-point-cloud-audit.json`, and
`evidence/wicker-point-cloud-validation.json`.
