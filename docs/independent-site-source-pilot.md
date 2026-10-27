# Independent-site source pilot

This pilot adds original evidence outside Alton Towers and performs a reserved-site
check of the small CPU crop classifier. It does not improve or promote the
production reconstruction model.

## Sources acquired and scoped

The pinned acquisition profile downloads seven original assets (13,351,192 bytes):
six drawing service JPEGs from the Library of Congress HABS MD-1080-A survey of
[Glen Echo Park's Dentzel Carousel building](https://www.loc.gov/item/md1366/),
and the official Runnymede [5 October 2022 planning committee pack](https://runnymede.moderngov.co.uk/documents/g798/Public%20reports%20pack%2005th-Oct-2022%2018.30%20Planning%20Committee.pdf?T=10)
containing Thorpe Park application RU.22/0374.

The original assets were downloaded twice and their exact byte counts and SHA256
pins reproduced. A changed or oversized response fails rather than replacing a
pin. Source files are external evidence, not Git binaries.

Glen Echo's selected drawings are the HABS field team's measured drawings,
credited in the survey and dated 1994. The LOC catalogue distinguishes Government-
made images from potentially restricted third-party copies. The pilot uses the
original drawing sheets, not historical copied photographs. The retained rights
advisory is scoped to those sources; it is not a blanket license for everything
in the collection. The 2022 Thorpe committee images are reduced planning-reference
material, not a new training collection with established reuse rights. No Thorpe
labels or as-built claims are generated.

## Reviewed drawing labels

Four original JPEGs supply 14 assistant-visually-reviewed source-pixel examples:

| Component kind | Examples |
| --- | ---: |
| Building plan envelope | 1 |
| Roof envelope or visible partial trace | 4 |
| Door leaf outline | 2 |
| Window assembly/outline | 3 |
| Masonry pier envelope | 1 |
| Building support/brace trace | 3 |

Coordinates and a three-original-pixel trace uncertainty are retained in
`evidence/glen-echo-source-review.json`. The whole building remains one connected
group, despite its multiple views and crops. Two decorative pier candidates
were excluded before evaluation because their boundaries were unclear at the
service-image resolution. The title/history sheet and machinery axonometric
sheet do not supply component labels for this task.

The new raster adapter verifies original image bytes, dimensions, explicit review
status, source state and target bounds. It retains unmarked grayscale crops and
separate target masks; targets never enter classifier inputs. Partial traces
stay open. No metric dimensions, geographic placement, user acceptance or current
physical reconstruction are inferred. JPEG service images are not described as
original CAD or high-resolution survey scans.

## First held-site result

The combined intake contains the existing 148 Alton examples and 14 Glen Echo
examples: 162 source pairs, 27 original source identities (23 PDFs plus four
rasters), two sites and 13 source/building-connected groups. Glen Echo's complete
site is reserved. Its review hash was frozen before predictions were generated.

The fixed 150-epoch, 16-hidden-unit, 16-pixel classifier fits normalization and
weights using Alton's 148 rows only. All Glen Echo source hashes and the physical
building identity remain outside the checkpoint's training lineage. The saved
checkpoint's predictions and training-only normalization were independently
recomputed.

| Held-site measure | Result |
| --- | ---: |
| Crop classifier correct | 2 / 14 (14.29%) |
| Training-majority baseline correct | 3 / 14 (21.43%) |
| Classifier macro F1 | 0.05195 |

This exposes poor transfer of the small crop recognizer. It is not a comparison
with historic cross-validation percentages on different examples, and not an
accuracy measurement of the whole reconstruction pipeline. One new building is
also insufficient for a broad cross-park benchmark. No tuning, relabeling or
production promotion follows consultation of this result. The research checkpoint
is retained for reproducibility; it is not a world-generation upgrade.

Next: add genuinely independent buildings/sites with the same component classes
and assess stronger existing visual features under the same site boundaries.
Reserve a fresh untouched site before later model selection. Do not train on this
Glen Echo holdout and continue calling it independent evaluation.

The subsequent [Denali expansion](denali-study-expansion.md) adds three buildings
on a third site, explicitly moves Glen Echo into development training, and
compares small and pretrained-feature models with Denali reserved.

## Replay

```sh
python -m voxel_mapper.study_source_acquisition \
  --profile evidence/independent-site-source-profile.json --output FRESH-SOURCES
python -m voxel_mapper.study_raster_dataset \
  --review evidence/glen-echo-source-review.json --sources FRESH-SOURCES \
  --output FRESH-GLEN-DATASET
```

Combine that dataset with the retained Alton package using `study_intake`, setting
`glen-echo-park` as the reserved evaluation site, then run `study_site_evaluation`
with 150 epochs and 16 hidden units. The portable review bundle contains the exact
source caches, original dataset, site intake, request, review, checkpoint and
report. A raster-only replay was byte-identical before publication. The real
source acquisition is separate from network-free synthetic engineering tests.
