# Mutiny Bay and Katanga Canyon source plans

The October 26 source handoff includes four Mutiny Bay PDF originals, one 23-page Katanga kiosk PDF bundle and one high-resolution Katanga restaurant JPEG. Two additional checksum-pinned Katanga restaurant booklets remain unavailable. The sources and portable analysis jobs are included in the project; no new blocks have been added to the retained Wicker Man/courtyard world.

| Area | Application | Recovered evidence |
| --- | --- | --- |
| Mutiny Bay courtyard | SMD/2017/0473 (also /0472) | Existing site 3023-01, AL05 existing ground-floor view, existing roof 3023-10 |
| Mutiny Bay lake | SMD/2013/0420 (also /0419) | Splash Battle fencing site plan 373/82 sheet 3.1; lake, courtyard frontage and mixed existing/proposed fencing |
| Katanga games kiosk | SMD/2007/0009 | Attachment 6172, titled Validation: 23-page scanned bundle containing site/location plans and elevations |
| Katanga restaurant | SMD/2009/0125 | Attachment 12134: original 6380 by 4770 JPEG of Proposed Explorers Restaurant Plan, TRC/1093-15, dated 10 December 2008, printed scale 1:50 |

Official links and exact source hashes are in `voxel_mapper/data/alton-mutiny-katanga-plan-review.json`. The kiosk bundle SHA-256 is `87438d135cb75ab0ff4112f31e0c99740ef595afbc90b3f6aca523421f47ed12`. The original restaurant JPEG SHA-256 is `4378e9b6ebb2c0cf8c00530bf496a82acb1b4b5ab4e1dcf5c357ff633d34a8f1`. These hashes were observed from live official downloads; the wider Mutiny Bay originals also match previously retained official checksums.

The kiosk page's three attachments are generically titled Validation, Validation and Decision Notice. Titles alone would have missed the drawings: pages 16, 17, 19, 20, 21, 22 and 23 were selected after viewing the complete 23-page contact sheet. They cover location/site plans, aerial context and elevations. Original bytes for the entire bundle are preserved, while the bounded analysis job selects seven pages. The JPEG is retained as an original raster, with a separate preview; it is not passed to the PDF worker or relabelled as native vector geometry. Its 200dpi scanner metadata and printed 1:50 label do not independently verify physical calibration or as-built state.

The restaurant page still lists legacy plan attachments 12965 and 15348, but those booklets failed HTTPS (503) and HTTP (timeout, then 500). Six other live-listed attachments were checked; one was recovered as the JPEG above, while the remainder failed. Failed responses were not accepted as PDFs. Both missing booklet references stay in the portable pilot request and remain explicitly unavailable.

A recovered sheet called Location of fencing in area 5 actually depicts the Upper Gardens/conservatory/bandstand. It is excluded despite sharing an application association. The existing courtyard site sheet has separate 1:200 and 1:500 views; its coordinate labels are not verified BNG. AL05 has an existing ground-floor view caption at 1:100 despite conflicting floor wording in its title block. Roof drawings remain roof context, and the lake sheet (1:250 on A3) has mixed retained/proposed fence styles.

The [historical Katanga/Gloomy Wood archive](https://www.towerstimes.co.uk/history/the-drawing-board/katanga-canyon-gloomy-wood/) identifies a 1992 concept but explicitly describes differences in built paths and theming. It remains a reference link, not accepted current-state geometry. The [courtyard restaurant retrospective](https://www.towerstimes.co.uk/history/the-drawing-board/mutiny-bay-courtyard-restaurant/) confirms that restaurant scheme was unbuilt; the existing courtyard selection is retained.

## Reproduce the handoff

Place the hash-named PDFs and original JPEG in a source directory, then run:

```sh
python -m voxel_mapper.planning_expansion_sources \
  --source-directory planning-originals --output a-new-source-pack
python -m voxel_mapper.planning_area_pilot \
  --config a-new-source-pack/mutiny-bay-pilot.json --output a-new-mutiny-review
python -m voxel_mapper.planning_area_pilot \
  --config a-new-source-pack/katanga-canyon-pilot.json --output a-new-katanga-review
```

The pack records available, missing and rejected originals separately, includes bounded previews and keeps relative source paths portable. Corrupt/oversized PDFs and changed raster hashes are withheld. The pilot can retry pinned PDF downloads with `--download-missing`; managed desktop planning jobs can load the two example requests in `examples/desktop`. No new desktop menu or automatic world merge is implied.

Actual analysis of the two newly recovered Mutiny Bay sheets completed: 238 closed outlines, 25 extracted surface labels and one surface-boundary candidate, but zero accepted nominal area-layout candidates, registered paths or reconstructed buildings. Katanga analysis completed all seven selected scan pages, with no native geometry candidates. The raster restaurant plan is available for source review but not automatic native-vector extraction. No training labels or model promotions result.

Next work is tracing and calibrating the raster plans, separating proposed and existing physical boundaries, and independently aligning the sheets to the retained Wicker/courtyard map. That registration is still required before expanding the world into Katanga or placing the wider Mutiny Bay geometry. The delivered source pack is not an expanded playable Katanga world.
