# Offline Mutiny Bay context pilot — 2026-11-24

This is a completed exploratory real-data experiment, not a test of the production 28-channel model. Public ArcGIS endpoints and GitHub DNS were unavailable from the local runtime. Archived EA LiDAR and clipped OSM lines were available. No new world or production checkpoint was produced.

## Evidence preparation
- Reopened the exact registered Alton training archive, paving expansion, Alton canopy archive, alton_lidar_geometry.zip and alton_registered_views.zip.
- Reassembled 80 unrotated source windows on their verified 267 × 211 BNG 1 m grid, west 407312, north 343671. Each RGB window was checked against the source crop. No conflicting target pixels. Rotated/overlapping variants were deduplicated: 3,202 distinct non-ignore pixels (1,198 stone, 1,986 brick, 18 asphalt), not 51,232 independent samples.
- Raw EA vegetation class 3/4/5 returns (survey 22-006, 2022-01-05, SK0540, OGL v3) were binned into positive log-scaled observation counts. No predicted canopy geometry or label masks were used as input.
- Archived class-2 counts, class-5/6 height above DTM and survey-known mask were warped to the source grid. Four conflicting survey overlap pixels were masked unknown. Class height is not DSM-DTM.
- Clipped OSM lines, not building/water polygons, were rasterized as positive-only context. No confirmed absence inferred. OSM archive attribution © OpenStreetMap contributors, ODbL; extraction 2026-11-22. No live ArcGIS input.
- Ten experimental context channels: low/medium/high vegetation counts, ground count, high-vegetation height, building-return height, survey known, OSM building/water/pedestrian lines. The last two building/water lines and building-return height had no positive cells in this crop; pedestrian lines had 323 positive cells but none on labeled pixels. Survey-known covered 2,066 cells, 49 on labels. Raw high-vegetation observations covered 13,106 cells, 325 on labels.
- Archive hashes: registered Alton 22522d22be8b63a9ffb482eab5e413f189cf29af2377abaad58b1f96f2235973; expansion a8da54f402ea9ac26cdd111d405ca1a682765b91661c613d2d510b733cb7e99b; canopy 787851d42c29665049220f6876de73802b8b8afe26f7cc17db9aabe2e09f547e; LiDAR geometry a14fd2b0c49cc8d45d0b823fefa59b05f0c7c3ae5be7d8607422a571ff235364; OSM registration 492ea934100b9e63116dc91cd367cecd3d54589285ed37536a0726df1dbb1c68.

## Experiment
Two-class small U-Net, RGB (3 channels) vs RGB + archived context (13 channels), same patch schedule, 10 epochs, 8 steps/epoch, batch 4, 32-pixel patches. Fixed spatial split chosen to keep both common classes: train x=0..133, validation x=166..266, 32 m buffer. Train 212 stone and 934 brick pixels, validate 690 stone and 535 brick pixels. Asphalt excluded because only 18 annotated pixels and none in train. 77 eligible training windows. No patch crosses partition. CPU torch 2.10.0, deterministic algorithms. Seeds 41/42/43 are repeat initializations, not independent spatial tests. Final epoch evaluated, no checkpoint selection.

| Seed | RGB mean IoU | Context mean IoU | Delta |
|---|---:|---:|---:|
| 41 | .4064988764 | .3538497295 | -.0526491469 |
| 42 | .4033121494 | .4991917388 | +.0958795895 |
| 43 | .2908384569 | .4919308023 | +.2010923453 |
| Mean | .3668831609 | .4483240902 | +.0814409293 |

Confusion matrices (rows true stone/brick, columns predicted stone/brick):
- 41 RGB [[600,90],[378,157]], context [[239,451],[126,409]]
- 42 RGB [[220,470],[31,504]], context [[357,333],[74,461]]
- 43 RGB [[107,583],[47,488]], context [[442,248],[168,367]]

This is a small within-capture validation comparison. One of three runs regressed; average IoU is still below .45. Not evidence of generalization to another park or of ArcGIS benefit. The local offline preparation and benchmark scripts, NPZ and JSON reports are delivered in a separate downloadable artifact; not committed as executable production code. Magic Kingdom remains untested; its three partial labels are generic paving only, and comparable GIS/LiDAR evidence has not been attached. Next steps: acquire actual open ArcGIS context, obtain independent reviewed material labels across multiple zones and parks, compare sources with ablations and an independent spatial holdout before any placement.
