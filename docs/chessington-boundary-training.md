# Chessington paving and roof boundary intake

The third user-marked example adds a second park to surface learning. Red marks
are projected path boundaries, green marks are tree locations, and the user
explicitly confirmed purple marks as building or roof boundaries. Purple is
opt-in evidence and cannot enter the water class. There are no water annotations
or grass labels in this example; training now samples only classes actually
observed in each image. Missing classes are not fabricated.

## Inputs and interpretation

The original 591 × 1280 phone screenshot is retained in the downloadable package.
A lossless crop `[0,172,591,1145]` removes the top and bottom browser interface,
leaving a 591 × 973 reference. The search overlay at `[0,80,380,135]` in the
cropped reference is explicitly excluded from glyph extraction. Other phone
controls contain no accepted markers and are outside drafted training regions.

Extraction retains **302 red path markers, 173 purple roof markers and 33 tree
locations**. A naturally blue pixel group is excluded because this image has no
user water annotations. Purple points remain a dedicated `building_boundary`
class, not surface interiors or path-boundary points. The conservative graph
produces 177 path edge segments in 46 chains with 15 review flags, and 130 roof
segments in 21 chains with two flags. These are candidate joins, not accepted
world geometry. Uncertain joins remain open.

Clean input is a separately downloaded, pinned 1024 × 1024 Esri World Imagery
raster. The model never receives the coloured annotation image or phone UI.
SIFT registration uses 883 inlier matches, median error 0.317 clean pixels and
95th-percentile error 0.974 pixels. This is image alignment, not surveyed ground
accuracy. Roof edges are not automatically projected down to wall footprints.
The receipt reports a 0.46 m source observation dated 17 August 2025; export
spacing is about 0.226 m. Export spacing does not establish additional optical
resolution or a uniform capture date across the mosaic.

Seventeen literal source-assisted regions produce 44,894 paving and 25,616
building/structure pixels. The remaining 978,066 pixels are unknown. The 2,846
raw class-conflict pixels, margins, uncertain tent edges and artificial corridor
caps are ignored. The 581 pixels of inferred paving beneath tree locations stay
separate from observed training truth. Green glyph radius is not canopy radius,
and green dots never supervise grass islands. Central tree/planter islands,
roofs and uncertain objects are kept out of visible paving targets.

The user supplied boundary guides and their colour meanings. Polygon vertices,
surface interiors and additional visible-roof negatives remain assistant-authored
interpretations requiring independent review. The new source pins, markers and
literal region recipe are in `voxel_mapper/data/user-chessington-*.json`.
The combined recipe and source files are in the downloadable package. Previous
Alton surface-mask hashes remain unchanged.

## Training and results

Before adding Chessington to fitting, the previous stage's exact pixel and
spatial checkpoints were frozen and evaluated on these new draft regions.
The spatial model achieved 63.80% paving IoU, 68.93% paving precision and 89.55%
recall, with two of three labelled connections retained. Its roof IoU was zero:
18,121 known roof pixels were predicted as paving. The pixel control predicted
all known pixels as paving (63.67% IoU, zero roof IoU). This is a newly supplied
transfer check, not an independently reviewed blind test.

The same architectures and fixed settings (seed 137, 120 steps, batch four,
96-pixel patches, learning rate 0.002, two CPU threads) were then fitted using
three examples from two parks. Evaluation now holds out every image from the
held-out park. Both Alton records stay out of fitting together; neither can leak
into the other's evaluation. Chessington is absent from the Chessington holdout.
No held-out score selects a checkpoint or hyperparameter.

| Held-out record | Spatial paving IoU | Spatial roof IoU | Fitting park |
| --- | ---: | ---: | --- |
| Towers Street / Mutiny Bay | 57.40% | 0% | Chessington |
| Gardens / lake | 39.95% | 0% | Chessington |
| Chessington courtyard | 63.80% | 0% | Alton Towers |

Both Alton predictions collapse to paving over known regions. The Chessington
fold reproduces the frozen prior-model transfer result. Training only on
Chessington cannot teach the absent grass/water classes. This demonstrates the
coverage gap; it does not establish improved generalisation. Four-class macro
IoU retains the fixed four-class denominator, including absent classes. Boundary
F1 is unavailable with the unknown edge bands; partial edge-hint recall is not
boundary precision. The stricter Alton holdouts are not directly comparable to
the earlier same-park image holdouts.

Final pixel and spatial models were trained on all three images. The spatial
weights changed by L2 3.299; its training loss fell from 1.580 to 0.858.
Its Chessington fitted roof IoU is only 5.35%, a training diagnostic, not
validation. More training data alone has not solved roof separation.
The production paving baseline remains unchanged. No checkpoint is promoted,
no world blocks are generated, and no Windows executable is built.

## Reproduction and checks

From the downloaded package, using this source revision and optional CPU
segmentation dependencies:

```bash
python -m voxel_mapper.connected_surfaces --examples inputs/examples.json --recipe surface-recipe.json --output new-dataset
python -m voxel_mapper.surface_segmentation --dataset new-dataset --output new-training
```

The literal recipe reproduces the exact dataset manifest and mask hashes.
All six final-checkpoint image predictions reproduce exactly after safe NumPy
weight reload; pickle is not used. The two architectures are not capacity
matched (404 versus 16,612 parameters). Eight models were fitted in this
experiment. Including the frozen-model checks, execution took 69.85 seconds and
about 460 MB peak process RSS, on CPU only. Seventy-seven relevant unit checks
passed with optional PyTorch present. Default Windows checks may skip optional
Torch tests when it is absent; no Windows training run is claimed.

The downloadable HTML compares the original marks, clean RGB, separate path
and roof graphs, draft masks, inferred canopy pixels, frozen-model outputs,
park holdouts and fitted previews. Its predictions also cover unknown regions;
those areas have not been validated. Source imagery remains attributed to Esri
and its imagery providers, with original receipts and capture audits retained.
