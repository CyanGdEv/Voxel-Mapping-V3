# RGB aerial semantic learning

This stage trains a separate, small neural model to interpret Esri RGB imagery. Its classes are **paths/plazas**, **visible building roofs**, **car parks**, **landscaped/grass islands**, and **other visible surfaces**. Paths and plazas share one class; planting containers and grass islands are not separately distinguished. The existing planning/ride checkpoint remains separate.

## Real training performed

The initial dataset contains four retained aerial images from three parks: Alton Towers (Towers Street and Wicker-area images), Thorpe Park and Chessington. Source bytes, metadata, resized RGB images, masks and an annotation ledger are pinned by SHA256. There are 89 visually authored annotation polygons and 153,915 labelled pixels after ignoring a two-pixel boundary margin. Unlabelled pixels use 255 and are excluded from fitting and scoring.

**These are assistant visual-review research labels, not independent human ground truth or surveyed geometry.** They were authored while viewing the original imagery, rather than copied from the previous colour assignments, map polygons or model predictions. Some small islands, roof/paving distinctions and parking margins remain uncertain. The downloadable dataset includes an image/annotation comparison for review.

A 31-feature source-only RGB/Lab/texture representation measures local context at approximately 1, 4 and 12 metres. A two-layer, 24-hidden-unit neural network learns all its weights on CPU with class-balanced cross entropy and Adam. It is a small NumPy network, not a large pretrained semantic foundation model. No Torch/GPU dependency was added. The settings (60 epochs, batch 512, learning rate .01, regularization .0001, seed 137) were fixed before the held-out experiment.

Only RGB-derived values enter inference. Site IDs, names, coordinates, source/annotation IDs, map tags and target masks do not enter the feature vector. The image's ground-scale estimate sets the context-window sizes. The model can therefore produce image-wide class proposals without OSM masks, but the first model's generalization is weak.

## Evaluation: do not read the training preview as an accuracy result

Every image from one park is held out together. The two Alton images never straddle training/evaluation folds. The reader rejects duplicate originals in different sites and overlapping cross-site image footprints. Training-fold statistics alone normalize the network; training masks alone supervise it.

Five-class park-held-out mean IoU was **28.30%**, versus **17.93%** for training-set RGB class centroids. This is agreement on the provisional annotated pixels, not full-image accuracy, boundary completeness or surveyed physical accuracy. The unlabelled majority of each image is not scored.

| Requested target | Park-held-out IoU |
| --- | ---: |
| Paths/plazas | 5.23% |
| Building roofs | 28.60% |
| Car parks | 38.23% |
| Landscaped/grass islands | 5.83% |

The other-visible class scored 63.61% and is included in the five-class average. Paths and islands are particularly poor. Alton's held-out mean IoU was 17.96%. The comparison supports continuing research, **not** reliable autonomous reconstruction. More diverse, independently reviewed labels and stronger spatial models are needed before trusting these boundaries.

Final fitting uses all four records and 26,742 class-balanced sampled pixels. The actual weight-change L2 norm was 25.75; training cross entropy fell from 1.105 to .218. These training figures show fitting occurred, not generalization quality. The final all-data checkpoint has no untouched final test. Fold checkpoints are also retained so held-out visualizations can be reproduced.

## Desktop and CLI

Two desktop jobs are added:

- **Train RGB aerial semantics** accepts `examples/desktop/train-aerial-semantics.json` after setting the dataset path.
- **Predict RGB aerial semantics** accepts `examples/desktop/predict-aerial-semantics.json` with a source aerial directory and pinned model path/hash.

From an updated source checkout:

```sh
python -m voxel_mapper.aerial_semantic_learning train --dataset dataset --output model
python -m voxel_mapper.aerial_semantic_learning predict --image demo-source/source-image.bin --receipt demo-source/imagery-receipt.json --model model/model.json --output predictions
```

Output paths must be fresh. Desktop workers retain CPU/thread and memory scheduling. Feature data is capped at two million dataset pixels; a prediction uses an aspect-preserving image of at most 512 pixels on its longer side. Parameters, masks, source hashes, normalization and source resizes are checked. Checkpoints are plain bounded JSON, not executable pickle files.

Predictions include a labelled mask, class map, source overlay and polygon proposals. Low softmax score/margin areas are marked unknown. Softmax scores are not calibrated physical confidence. The report explicitly records whether the source image appeared in training. The HTML distinguishes training-source and held-out/unseen-source demonstrations. Model polygons do not become new supervised labels automatically.

## Save/reuse in the adaptive cycle

Optional cycle settings:

```json
{
  "aerial_semantics": {
    "dataset_directory": "aerial-semantic-dataset",
    "use_for_geometry": true
  }
}
```

The cycle checks the dataset, settings and feature/network versions, fits a changed semantic dataset into an atomic checkpoint, and reuses an unchanged checked model. A SQLite registry checks saved model/report hashes; modified checkpoints fail. The existing source-pair heads and the new semantic network have distinct status fields. Tests exercise new-data retraining and restart reuse. The saved class errors also prioritize public-site research queries for weak RGB classes; new downloads still require source-linked annotations before fitting.

For an imagery geometry request, `semantic_model: {"file": "model/model.json", "sha256": "..."}` enables an additional learned layer. The cycle can bind its saved semantic model automatically when `use_for_geometry` is true. Existing map/RGB regions remain separate. Learned polygons are clipped to the requested area and subtracted from protected plan coverage; raw predictions remain available for error review. The real Towers Street cycle registered/reused the trained checkpoint and produced the extra layer offline.

None of these outputs verify registration, ground footprints, building heights, parking capacities, planter construction or material identity. They do not write world blocks or replace accepted geometry. The default remains a research checkpoint (`production_eligible: false`). This is a source update; a new Windows EXE has not been rebuilt.

Imagery attribution: Esri World Imagery and its imagery providers. Original provider metadata/date/accuracy observations remain with each retained image. Chessington location context was checked against its [official directions](https://www.chessington.com/plan-your-visit/before-you-visit/directions/); this does not verify individual labels.
