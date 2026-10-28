# Second user example: garden paths and shoreline

The next [connected surface segmentation stage](connected-surface-segmentation.md)
adds ordered edge candidates, explicit four-class region masks and an actual
spatial CNN benchmark. The original sparse-boundary experiment remains below.

The new annotated image is now a second training example alongside the user's
Towers Street / Mutiny Bay reference. The importer retains **635 red projected
path-boundary marks, 68 green tree locations and 93 blue shoreline marks**.
Green glyph size remains separate from canopy extent. Blue marks in this image
are explicitly shoreline points; the earlier image's six blue pond-location
hints are not relabelled as a complete shoreline.

The new photograph is rotated relative to north-up. A coarse locator image
established its geographic placement, followed by a separately retained
1024 × 1024 clean aerial source. Registration has 921 supporting feature
matches, median residual 0.340 and p95 residual 0.990 clean pixels. The original
reference remains 761 × 1280, unchanged. Registration transfers the labels;
no coloured annotation enters neural model features. These residuals measure
image alignment, not surveyed ground accuracy or a resolution upgrade.

## Training and evaluation

`user_path_supervision --examples examples.json` now supports two to four pinned
examples. Each record declares its ID, site, reference, clean source, receipt,
registration, water-marker role and optional fine-dot extraction mode. Fine
mode retains small saturated dots supported by nearby markers while rejecting
isolated micro-specks; the original extraction mode is unchanged.

Path-boundary training uses 30,704 sparse samples from both images, a 64-unit
network, 90 epochs and the existing clean RGB/context feature extractor.
Unmarked pixels remain unknown. Negative examples are derived offsets from
local boundary tangents, not independently labelled negative ground truth.

Whole images are held out in turn. A 24 m geographic guard prevents overlapping
feature neighbourhoods from entering training and evaluation on opposite sides.
The closest labelled samples between these examples are 86.90 m apart, so none
needed removal. Both examples are at Alton Towers: this is same-park development,
not a new-park or independent blind test.

| Whole image held out | Precision | Recall | Boundary F1 | Always-boundary F1 |
| --- | ---: | ---: | ---: | ---: |
| Towers Street / Mutiny Bay | 21.86% | 32.37% | 26.09% | 33.12% |
| Gardens / lakeside | 19.34% | 20.34% | 19.83% | 33.50% |

These checks remain weak and below the constant reference. Adding data has not
established better automatic precision. The combined checkpoint fits both
examples and its displayed predictions are fitted-area previews, not the
whole-image holdout scores above. It stays separate from the existing paving
classifier, whose checkpoint is unchanged.

A **separate water-boundary checkpoint** fits 3,918 sparse samples around the
93 new shoreline points. It has no independent water-boundary validation and
does not classify the whole water surface or close the open shoreline into a
lake polygon. The task/version contract prevents either boundary checkpoint
from being loaded as a paving classifier.

## Trees and ground paths

The user's rule is retained: an established path may continue under overlapping
tree canopy, with inferred ground kept separate from visible paving and trees
kept overhead. Buildings, water and bounded grass islands remain exclusions.
This image does not supply complete connected path polygons or measured canopy
outlines. Green tree points alone do not label grass, and the open shoreline
does not authorize filling an invented water polygon.

## Inspect and reproduce

The download contains both original marked images, both clean RGB sources and
receipts, registrations, extracted points, projected EPSG:3857 guidance, sparse
targets, whole-image fold models/reports, the combined path checkpoint and the
separate shoreline checkpoint. The viewer can switch between original markup,
clean input, mapped markers and the two fitted probability previews.

With the project installed, from the package root:

```sh
python -m voxel_mapper.user_path_supervision \
  --examples examples.json --output fresh-training
```

Paths in `examples.json` are package-relative; source hashes and registration
are checked before fitting. The original single-example CLI remains supported.
The image-matching preparation used optional OpenCV; importer/training require
no new OpenCV runtime dependency. User input and clean sources remain distinct.
No Paultons/LEGOLAND test labels, world blocks, production adoption or Windows
executable build are part of this experiment.

Clear path-side/interior labels and further diverse annotated areas remain
necessary to learn continuous geometry reliably. More epochs on these examples
alone would not demonstrate that improvement.
