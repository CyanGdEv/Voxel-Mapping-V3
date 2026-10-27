# Station and preshow world extension

The [station access update](wicker-station-access.md) supersedes the entrance-flight dimensions and block counts below: the current generator produces a five-column half-step connection to retained paving. The original v1 dimensions below document the earlier PR #113 export.

This conditional world adds the station, lower preshow gable and taller pyramidal preshow section to the corrected shop scene. The earlier shop's 576 blocks retain their materials, positions and native vertical offset. Roofs use native oak top/bottom slabs as illustrative thatch proxies; no full-block roof layer is added.

## Original sources and measured heights

All four original proposed P1 PDFs are checksum checked:

| Drawing | Official attachment | Role |
| --- | --- | --- |
| 2967-30 | [163938](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163938) | Preshow elevations and ride-building section |
| 2967-22 | [163936](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163936) | Undercroft and inspection reference levels |
| 2967-48 | [163940](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163940) | Roof-plan bounds and component arrangement |
| 2967-21 | [163935](https://publicaccess.staffsmoorlands.gov.uk/portal/servlets/AttachmentShowServlet?ImageName=163935) | Overall floor-plan context |

The original elevation render is pinned at 1888 × 1334 pixels. Manual eave/ridge samples are converted through the rotated-page native transform and referenced to the printed Preshow Top Level +183.30 datum line. The station section is not mistakenly raised from its lower inspection reference. Four original preshow roof-boundary stroke bounds are replayed from each retained plan component.

| Component | Proposed roof span, m | Eave above selected source reference, m | Ridge above selected source reference, m |
| --- | ---: | ---: | ---: |
| Station gable | 9.218 × 17.952 | 3.124 | 5.395 |
| Lower preshow gable | 7.844 × 8.522 | 2.811 | 5.082 |
| Preshow pyramid | 7.844 × 7.844 | 5.350 | 7.955 |

Manual endpoints have ±2-pixel sampling bounds, approximately ±0.178 m for a two-endpoint height. These bounds do not describe total physical accuracy. Roof surfaces are quantized to half-block heights, with bounded display smoothing; timber wall tops take priority at incompatible slab/wall cell aliases. Palette and voxel thickness are display choices.

The existing rigid drawing-to-landscape transform is retained without rescaling or refitting OSM. The station's separately traced wall dimensions are centred under its roof as an explicit local assembly hypothesis; its offset is recorded. Preshow wall inset, aperture dimensions and connecting strips retain the earlier V12 review assumptions. The later partial-gable cap alternatives, rail-tail hold and source ambiguities remain unchanged; the complete lower-roof span is a prototype display hypothesis, not an accepted complete source mesh.

## Floors, undercroft and connections

The retained station landscape FFL is 183.25 and the preshow top-level claim is 183.30. Both upper display floors round up to **184 m**, with +0.75 m and +0.70 m grid errors respectively. The preshow's provisional lower floor uses **178 m**. Printed levels are conditionally treated as ODN; physical datum and as-built roles remain unverified. Station inspection level **181.25** stays a separate reference and is not assigned as a passenger floor or constructed inspection floor.

The undercroft is hollow: 365 interior air cells are checked below the upper preshow floor. Its provisional enclosure follows the upper preshow footprint and connecting strip. The actual basement wall outline, lower openings, internal stairs and excavation design are not reconstructed. Station support piers/plinths and the lower stone palette remain illustrative.

Two connecting floor strips and re-carved compound portals connect all three upper sections. A four-neighbour check finds 214 connected clear upper-floor columns with two-block headroom. Exact architectural doorway dimensions and circulation roles remain review estimates.

The main preshow entry receives a collision-free **estimated 4 m approach**, 1.5 m wide, with seven verified walking columns and four oak-fence rail columns. The narrow-path oak-fence rule is retained. Native half-step/full-step surfaces connect existing ground to the upper floor; the largest orthogonal grid step is 1 m. This is not an accessibility or full queue-layout certificate. Other external entrances and undercroft access remain unresolved.

## Preservation and checks

The generation adds 1,302 structure records, retires 212 obsolete station display-plinth blocks, and supersedes six gap-inferred boundary columns (seven blocks) beneath the new footprint. These were user-default rock/fence inferences, not verified architectural boundaries. Their original columns remain in the receipt. The 1,203 other source edging blocks are retained. Existing source terrain outside the new building and former station-floor regions is preserved; the corrected shop scene and original archive are not overwritten.

Eighteen focused station/preshow, shop-shell, native-slab and facade tests pass. Native readback checks all 39,250 terrain columns and written blocks/unwritten air, 71 compound-portal air cells, 365 undercroft air cells, 14 entry-flight headroom samples and all seven actual stair-surface block shapes. Archive CRC/file-byte checks and cold reopen of all 187 chunks pass. Minecraft import and gameplay testing of this revision remain pending.

## Replay

```sh
python -m voxel_mapper.planning_station_preshow_world \
  --config alignment-request.json \
  --base-directory corrected-shop \
  --geographic-directory geographic-base \
  --pdf-directory original-pdfs \
  --evidence-directory evidence \
  --output fresh-station-preshow-world \
  --allow-provisional
```

The profile pins the exact corrected-shop world, voxel records and report, geographic baseline records, architectural review and original PDFs. Missing or changed inputs fail rather than falling back to a different placement. The opt-in flag authorizes a conditional local review; it does not establish physical acceptance. The review pack contains these portable inputs, original annotated height view, block/portal receipts and source changes. No frozen GUI action, accepted survey control, model training or as-built reconstruction is added.
