# Connected edge candidates and spatial surface segmentation

This stage converts the two user annotations into ordered edge candidates and
four-class semantic masks, then trains an actual spatial convolutional network.
It establishes the new data/model pipeline, **not reliable automatic park
reconstruction**. Keep the existing paving baseline: garden transfer improves,
but Towers Street path reconstruction remains poor.

## Geometry and mask evidence

The conservative graph connects mutual neighbours whose direction agrees with
the local boundary tangent. It does not join across gaps above 12 reference
pixels, force ambiguous branches, or treat a closed loop as paving. Parallel
edges remain separate. The actual graphs contain 329 candidate segments in 125
ordered chains and 123 review flags. No closed chain was recovered confidently;
these are incomplete boundary candidates, not finished path polygons.

Surface training therefore also uses **63 explicit source-assisted semantic
regions**, authored by the assistant using the clean aerial view, the user's
projected boundaries and retained source traces. They are not automatically
verified user polygons. Narrow route interiors are represented as conservative
corridors, with artificial end caps withheld. The formal garden paths retain
grass-island holes. A visible circular raised structure is excluded from the
Mutiny Bay path corridor. Visible lake interior receives a water label, without
inventing an exact shoreline from the open blue boundary.

| Mask | Paving | Building/structure | Grass island | Water | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Towers Street / Mutiny Bay | 27,737 | 12,178 | 7,687 | 718 | 607,040 |
| Gardens / lakeside | 24,796 | 3,951 | 11,539 | 21,779 | 986,511 |

Only 110,385 pixels, about 6.5% of the two clean images, are labelled. Unmarked
background is not silently negative. One-pixel trace margins, 530 conflicting
raw region pixels in the first image, uncertain corridor caps and assumed
canopy are ignored during fitting. Conflicting traces remain a review issue.

The user's tree rule is retained as a separate inferred ground layer. These
masks identify 766 path-footprint pixels under provisional canopy buffers,
excluding building, grass-island and water regions; those pixels do not become
observed training truth. Existing unknown canopy traces remain unknown. Tree
locations are not grass labels or measured canopy outlines.

The dataset has a separate version/legend: paving 0, building/structure 1,
grass island 2, water 3, unknown 255. It is incompatible with the existing binary
and five-class label contracts. Source hashes, recipe hash, mask bytes and class
counts are checked before fitting. Coordinates and map layers are not feature
channels; only clean RGB enters the networks.

## Spatial architecture and benchmark

The spatial model has full-resolution 3 × 3 convolutions, a pooled branch with
dilated convolutions, upsampling and a skip connection before four-class output.
It has 16,612 parameters and learns local surface context rather than predicting
each pixel independently. The 1 × 1 per-pixel control has 404 parameters; this
is not a capacity-matched causal experiment. Both use the same seeded patch
sampling, rotations/flips, optimiser, 120 steps, batch 4 and native 96 × 96
patches. Unknown targets are ignored by cross entropy.

Whole images are held out in turn. Labelled areas are 93.56 m apart, exceeding
the enforced 24 m geographic context guard. Both examples remain from the same
park and have already been used for development. No fresh unseen-park final
test was consumed and no independent surface review has been received.

| Image held out | Model | Macro surface IoU | Paving IoU | Paving precision | Paving recall | Connected pairs |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Towers / Mutiny | Per-pixel control | 0.37% | 0% | 0% | 0% | 0/3 |
| Towers / Mutiny | Spatial CNN | 16.29% | 1.84% | 11.53% | 2.14% | 0/3 |
| Gardens / lakeside | Per-pixel control | 9.99% | 39.95% | 39.95% | 100% | 3/3 |
| Gardens / lakeside | Spatial CNN | 22.81% | 61.73% | 81.32% | 71.93% | 1/3 |

Always-paving has macro IoU 14.35% and 9.99% respectively, and recalls all three
connection pairs while producing false paving over every labelled building and
water pixel. The per-pixel control collapses toward a single class on held-out
images. Do not treat beating this weak control as proof of general accuracy.
Both learned architectures have zero held-out water IoU in this experiment.

On narrow **labelled interior strips**, the spatial CNN recalls 4.86% of Towers
pixels and 56.18% of garden pixels. Those strips are not surveyed full path
widths. It misses six labelled Towers path components and three garden
components. User red-edge hint recall within two clean pixels is 10.37% and
32.76%, respectively. That is edge-hint recall, not full boundary precision.
Boundary F1 remains unavailable because uncertain edge bands are ignored.

The spatial final model fits both images; its previews are fitted-area outputs,
not the held-out predictions above. No model is adopted automatically. Two
examples, incomplete masks, source-assisted semantic choices, colour/material
shift and capacity differences limit what these scores establish.

## CPU use and safe checkpoints

The measured six-model experiment used two CPU threads, about 438 MB peak process
RSS and 77.13 seconds. No GPU or pretrained weights were used. PyTorch 2.5.1+cpu
ran this experiment. The new `segmentation` extra is optional; the default
desktop package is not changed to bundle Torch and no Windows EXE is built here.

For CPU-only installation, install a suitable official CPU PyTorch wheel, then
the project with its optional segmentation dependencies. The reproduction used:

```sh
python -m pip install torch==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e '.[segmentation]'
```

Weights use bounded NumPy NPZ arrays with `allow_pickle=False`, verified hashes,
known tensor names/shapes and finite numeric limits. Loading does not unpickle
Torch objects. Tiled inference uses a 16-pixel halo and preserves native pixel
dimensions. Both saved final checkpoints reproduce their stored predictions on
both clean images exactly after reload.

With the updated project installed, from the download:

```sh
python -m voxel_mapper.connected_surfaces \
  --examples examples.json --recipe surface-recipe.json --output new-dataset
python -m voxel_mapper.surface_segmentation \
  --dataset new-dataset --output fresh-spatial-training
```

The package includes original marked references, clean RGB/receipts,
registrations, region recipe, ordered chains/review flags, class masks,
inferred-ground masks, models, predictions and all scores. Region GeoJSON uses
explicit clean-image pixel coordinates, not geographic coordinates. Image
alignment does not establish survey accuracy. No accepted world geometry,
world blocks or production checkpoint replacement results from this experiment.

## Chessington extension

The next training intake adds user-confirmed purple building/roof boundaries and
whole-park holdouts. See [Chessington boundary training](chessington-boundary-training.md)
for the three-image dataset, missing-class handling and transfer limitations.
