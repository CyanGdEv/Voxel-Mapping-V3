# Source-traced paving masks

Use the [offline source-only polygon editor](paving-label-review.md) to submit
explicit per-outline corrections without changing original masks or exposing
the consumed reserved test to training.

The latest masks include the [roof corrections from user review](#roof-correction-after-user-review). The initial counts below are retained as the superseded baseline; use the corrected download and counts in that section.

This stage creates **four native-resolution binary paving mask crops across three parks**. The main visible paving boundaries are traced explicitly, rather than sampled as small rectangles or copied from model/map predictions. Roofs, raised features, grass islands and planter holes receive separate visible non-paving traces; occluded or unreviewed ground stays unknown.

These are **provisional assistant visual drafts requiring independent review**, not human-verified ground truth. They do not fix the model's accuracy by themselves. The five-class neural checkpoint is unchanged and no world geometry is accepted. A later binary training experiment is linked below.

## What was created (initial draft, superseded)

| Crop | Park group | Native crop size | Paving pixels | Non-paving pixels | Unknown pixels |
| --- | --- | --- | ---: | ---: | ---: |
| Towers Street plaza | alton-towers | 330 × 620 | 83,485 | 48,926 | 72,189 |
| Wicker entrance courtyard | alton-towers | 330 × 305 | 33,250 | 34,144 | 33,256 |
| Chessington garden paths | chessington | 350 × 380 | 18,976 | 10,260 | 103,764 |
| Drayton pedestrian route | drayton-manor | 240 × 555 | 14,474 | 14,376 | 104,350 |

The four crops contain 571,450 pixels: **150,185 paving**, **107,706 non-paving** and **313,559 unknown/unreviewed**. Only 45.1% are labelled; these are not fully labelled whole images. The large unknown fraction is deliberate: canopy, uncertain shadow and untraced margins are not guessed. The 54 explicit trace polygons include 10 polygon holes. Visible path shapes are more continuous than the earlier patch annotations, while remaining incomplete where the source is uncertain.

Crop rectangles refer to the retained original 1024-pixel aerial images. Images are neither enlarged nor resized. Georeferenced crop extents are computed from the provider's retained EPSG:3857 image extent and exact pixel offsets. This preserves raster coordinates, not independent survey registration or a guarantee of the provider's true ground resolution.

## Label contract

The format is `paving-mask-dataset-v1`:

- `1`: explicitly traced **visible pedestrian paving**.
- `0`: explicitly traced **visible non-paving** such as roof, grass, raised ride installation or water.
- `255`: **ignore**, including unreviewed ground, uncertain/occluded regions, trace-edge margins, conflicting labels or source nodata.

This binary label contract is different from the existing five-class aerial semantic dataset, where class 0 means paths/plazas. The five-class reader rejects these masks. Do not feed them into that model by simply renaming files or remapping every negative to a roof class. A future binary spatial learner must ignore 255 and use the declared legend explicitly.

Only literal polygon rings supervise the masks. Holes remain unknown unless separately traced as known non-paving. A one-native-pixel margin on trace edges is ignored. Explicit unknown polygons and transparent source pixels override labels. Overlapping positive/negative interiors remain ignored rather than silently selecting a class. After source-overlay review, broad paving outlines were refined against the explicitly traced roof/grass/object polygons; this is a vector correction using the authored traces, not a model-generated label. The final four masks have **zero conflicting interior pixels**.

A separate ignore-reason raster distinguishes labelled pixels (0), unreviewed pixels (1), explicit uncertainty (2), boundary margins (3), conflicting traces (4) and nodata (5). The review page includes a coloured rendering; the raw byte raster is machine-readable and will appear almost black in ordinary image viewers.

## Review and reproduce

The download contains:

- `dataset/index.html`: original crop/blue-positive/red-negative overlays and coloured ignore-reason previews.
- `dataset/annotations.json`: editable source trace polygons, holes and uncertainty reasons.
- `dataset/images`, `dataset/masks`, `dataset/ignore-reasons`: native RGB crops and byte label rasters.
- `dataset/originals`, `dataset/metadata`: unchanged original imagery and retained source receipts.
- `dataset/dataset.json`: SHA256 pins, crop geometry, counts, park groups and review policy.
- `sources.json`: portable pinned source paths for rebuilding corrected traces.

From an updated source checkout and the download directory:

```sh
python -m voxel_mapper.paving_masks validate --dataset dataset
python -m voxel_mapper.paving_masks build --sources sources.json --annotations dataset/annotations.json --output corrected-dataset
```

Build outputs must be fresh. Source-file paths in `sources.json` resolve relative to that file. To correct a draft, update the literal rings/holes/reasons and rebuild; a manually edited PNG alone is rejected even if its manifest hash is resealed. Validation reconstructs the original RGB crop and every label/ignore pixel from the pinned source and annotation ledger. Changed source bytes, altered crops, invalid polygons and claims of human/production verification fail.

Both Alton crops share one park group. Repeated originals or overlapping crop geography cannot be assigned to different parks. These source images were already used during earlier development, so **none is an untouched final test**. No train/test split or accuracy claim is created at this stage.

Independent review should check roof eaves, planter edging, paving in visible shadow, narrow passages and whether some apparent hard surfaces are ride pads or service routes. The masks then provide inputs for a binary spatial-model benchmark; they now feed the separate binary experiment linked below. Research training is explicitly provisional, while production training remains disabled. No Windows EXE was rebuilt.

Attribution: Esri World Imagery and its imagery providers. Source/capture/resolution/accuracy observations remain in the original retained receipts and do not establish exact physical registration.

## Roof correction after user review

The counts above describe the first draft, which **included some roof sections in the paving mask**. The corrected dataset supersedes that draft. At the mask-correction stage neither revision had retrained a model; the later binary experiment uses the corrected revision.

Source-overlay inspection identified missed diagonal roofs at both lower corners of the Towers Street crop, the right-hand pre-show gable and north-east roof at Wicker, and incomplete pavilion/curved-roof extents at Chessington and Drayton. Explicit non-paving outlines now include these sections. The north-east Wicker facade/shadow transition and a few ambiguous corners are unknown rather than guessed ground.

The combined source-traced roof outlines receive an explicit unknown ring extending two native pixels outward and one inward. Using the combined roof geometry avoids unnecessary guard seams between adjoining roof sections. Broad paving traces are re-cut against the corrected visible non-paving outlines. This is an annotation correction using the same source images, not an RGB threshold, map mask or model prediction.

| Crop | Corrected paving | Corrected non-paving | Unknown | Previously paving, now excluded |
| --- | ---: | ---: | ---: | ---: |
| Towers Street plaza | 76,601 | 60,300 | 67,699 | 6,884 |
| Wicker entrance courtyard | 29,865 | 40,310 | 30,475 | 3,385 |
| Chessington garden paths | 18,976 | 10,859 | 103,165 | 0 |
| Drayton pedestrian route | 14,426 | 16,505 | 102,269 | 48 |

In total **10,317 previously paving-labelled pixels are excluded**, with **zero newly added paving pixels**. Current totals are 139,868 paving, 127,974 non-paving and 303,608 unknown. All source bytes, crop coordinates, RGB pixels and georeferenced extents remain unchanged. Known roof interiors, uncertain eaves and neighbouring ground paths are pinned as explicit source-coordinate regression probes in `voxel_mapper/data/paving-mask-roof-review.json`.

The corrected download is named `Source-Traced-Paving-Masks-Roof-Fix.zip`, with its own standalone review page. The earlier download is retained for comparison. This revision remains a provisional assistant visual draft requiring independent review; it does not establish that every remaining roof or paving boundary is correct. The mask correction itself did not change neural weights.

The corrected masks now feed a separate [binary RGB/context training experiment](paving-binary-colour-training.md). This does not change their provisional status or replace the earlier five-class checkpoint.
