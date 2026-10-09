# Mutiny Bay source integration

Mutiny Bay evidence is exposed in the Alton acquisition report's `mutiny_bay` inventory. The ordinary council acquisition path can inspect the new checksum-pinned drawings through `application_references`. Source acquisition and world correction are separate: no geometry is approved by an application title, a historical approval, or a material word alone.

| Area | Application references | Evidence |
|---|---|---|
| Courtyard / Ingestre Court | SMD/2017/0472, SMD/2017/0473 | Existing/proposed site plans, floor plans, roof plans, elevations, canopy drawings, design/access and heritage documents |
| Battle Galleons boating lake | SMD/2007/1172 | Original boat ride and ancillary structures; legacy drawing bundles and location plan |
| Sharkbait / replacement attraction | SMD/2008/0940 | Replacement indoor attraction and alterations to existing store and Mutiny Bay shop |
| Earlier cinema demolition | SMD/2008/0988 | Demolition in association with replacement indoor attraction; generic legacy plans require sheet-by-sheet role review |
| Lake / bridge safety fencing | SMD/2013/0012, 0013, 0419, 0420 | Site/block plans, heritage fence details, decisions and supporting records |

Official application HTML is checked against retained hashes. Existing/proposed roles follow attachment titles, with unknown legacy titles preserved. Identical PDF contents share one cached file while retaining links to each application. Retained new PDFs are added to the main planning catalogue. Supporting RTF documents and raster attachments, when available, remain in the area source inventory and pack; they are not fed into the PDF geometry reader. Unavailable documents retain their URL and failure reason.

The existing courtyard site plan includes surveyed surface levels, SEA LIFE CENTRE context, materials and walls. The Splash Battle fencing site plan includes lake water levels, ramps, timber platform/weirs, wall heights and railing/fence labels. These remain dated local drawing evidence. In particular, the courtyard sheet's printed coordinate labels must not be assumed to be British National Grid without checking the survey basis.

The proposed courtyard smokehouse scheme is reported as unbuilt in the TowersTimes retrospective:
https://www.towerstimes.co.uk/history/the-drawing-board/mutiny-bay-courtyard-restaurant/
This is a secondary-source caution, not proof of the exact current building condition. Existing/proposed drawings remain separate and no proposal is silently used as the present-day layout.

## Next correction gates

Use identifiable existing courtyard corners, lake edges and paths as independent controls against current mapped geometry/orthophoto evidence. Check sheet scale, rotations, panel frames, survey datum and date before estimating a transform. Retain residuals and an explicit validated domain. Then review bounded path widths/materials, ground profiles, walls, fences and ride footprints; rail/ride mechanism heights require separate evidence. This integration does not move the world or assert that the reported Mutiny Bay discrepancy has been measured.

The saved source pack contains acquired PDFs, council pages, full native-text inspection and availability records. The repository area inventory contains compact page metadata/text hashes and selected review cues; full source text is not a physical geometry record. `source_inventory()` always reports zero world geometry additions until independent registration is implemented.

## Courtyard alignment review

`voxel_mapper.mutiny_bay_review` now retains four reviewed inner roof/eaves corners from the checksum-pinned existing roof sheet 3023-10. At its printed 1:200 scale they enclose approximately 971.35 m². The drawing also shows an existing central canopy: the courtyard perimeter is not permission to clear every object inside it.

A simplified diagnostic envelope around the four main wings measures approximately 44.40 × 44.13 m at the printed scale. It excludes complete corner/entrance/annexe detailing and is not an exact building footprint. Its best similarity fit against the single mapped Courtyard Tavern BBQ polygon differs from the printed scale by 14.02% and has 2.75 m corner RMS. This fit is rejected. These may be different physical extents; one object also cannot establish independent registration. The rotated/ambiguous candidate is retained only for diagnosis and cannot drive world replacements.

A separate read-only V20 native audit checks 787 channel columns inside Battle Galleons member 453985982 over geographic Y 168–194 m. The 790.69 m² channel footprint is fully within mapped water. The scan contains water, estimated bed/fill and air, plus 16 protected iron cells, and no stone-brick cells. This rejects the initial suspicion of a stone-brick channel extrusion in that bounded scan; it does not establish ride geometry or whole-area visual accuracy.

```bash
python -m voxel_mapper.mutiny_bay_review --cache MUTINY_SOURCE_PACK \
  --osm park-osm.json --source-output V20_OUTPUT --output REVIEW_OUTPUT
```

The source pack must retain its `files/SHA256.pdf` paths. Five focused tests cover the inventory and the rule that even a perfect one-object fit cannot approve placement. Next registration work must match individual existing wings and independent landmarks rather than resizing or translating the entire area. No park-world geometry changed in this review. See `evidence/mutiny-bay-alignment-review.json`.
