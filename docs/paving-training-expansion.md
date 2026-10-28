# Expanded paving neural training

This stage actually retrains the CPU RGB/context neural network. It does not use the separate map-guided paving layer as supervision, and it preserves the previous checkpoint. The new research model recognises more paving, but false positives remain substantial and roof recognition regresses. It is not a general production replacement.

## Data and fitting

The expanded dataset contains **eight 512-pixel RGB images from five parks**: Alton Towers, Thorpe Park, Chessington, LEGOLAND Windsor and Drayton Manor. Four source images are newly acquired Esri imagery; existing originals are retained unchanged. There are **225 provisional assistant visual annotation polygons**, including new visible paving examples and source-visible roofs, parking, ride surfaces, vegetation and water as other-class examples. Three ambiguous circular ride-pad traces were removed during visual review before training.

These labels are not independently verified human ground truth. Neither OSM geometry, the map-guided paving mask nor previous model predictions were copied into the targets. The literal annotation ledger is `voxel_mapper/data/aerial-semantic-paving-expansion-annotations.json`. Downloaded data includes original source bytes, retained imagery metadata, masks and a source/annotation gallery.

Paving-labelled pixels increased from **17,353 to 43,790** (2.52 times); total labelled pixels increased from 153,915 to **249,423**. Unlabelled pixels and a two-pixel annotation boundary margin remain excluded. Each image contributes at most 1,500 samples per class. Actual final fitting uses **49,686 samples** across five classes. The dataset contains 2,097,152 total pixels, within the existing memory bound.

The 31 RGB/Lab/context features, 24 hidden units and optimizer settings are unchanged: 60 epochs, batch 512, learning rate .01, regularization .0001, seed 137. Every park's images remain together in each exclusion fold, including overlapping images at Thorpe and Chessington. CPU fitting updated all network weights (weight-change L2 **25.06**). Final training cross entropy fell from **1.0823 to .5085**. Training loss does not establish generalization.

Final checkpoint SHA256: `edaaad43ec6ee8488a2864443b33ca9a9a2fd16835009eb2514e40f55957130c`.

## Same-target comparison

The original four images' annotation masks are frozen separately. Before/after models are scored on exactly their same 153,915 annotated pixels. The scoring fold excludes the entire park from fitting, normalization and sampling. Checkpoint dataset, source, park and record lineage is verified; using an all-data final model in place of an exclusion checkpoint fails.

| Class | Previous IoU | Expanded-data IoU on the same targets |
| --- | ---: | ---: |
| Paths/plazas | 5.23% | 14.34% |
| Building roofs | 28.60% | 22.43% |
| Car parks | 38.23% | 44.61% |
| Landscaped islands | 5.83% | 7.57% |
| Other visible | 63.61% | 67.17% |

Paving precision increased from **9.35% to 18.40%** and recall from **10.60% to 39.43%**. False positives are still high; the model labels some roofs and vehicle surfaces as paving. Five-class mean IoU rose from 28.30% to 31.22%, while roof recognition declined. Original-image paving IoUs after expansion are Towers Street 21.35%, Wicker-area 8.12%, Chessington entrance 18.68%, Thorpe entrance 2.12%. Preserve the previous model for comparisons and broader roof work; do not silently replace it everywhere.

These are reused **development labels**, not an untouched blind test, independently surveyed accuracy or full-image boundary completeness. The original results informed the decision to add paving examples. Only originally labelled pixels are scored; the unlabelled majority's false positives are unmeasured. No map/OSM inputs enter this neural comparison.

The separate five-park cross-validation on all expanded annotations reports paving IoU **22.57%** and five-class mean IoU 32.27%. Those targets and park mix differ, so that paving number must not be presented as a same-target improvement from the original 5.23%. The final model fits all eight records and has no untouched final test.

## Reproduce and use

From the updated source checkout, using the download's relative directories:

```sh
python -m voxel_mapper.aerial_semantic_learning train --dataset dataset --output newly-trained-model
python -m voxel_mapper.aerial_semantic_comparison --reference-dataset frozen-reference --candidate-dataset dataset --previous-models previous-model --candidate-models model --output comparison-replay
python -m voxel_mapper.aerial_semantic_learning predict --image demo-source/source-image.bin --receipt demo-source/imagery-receipt.json --model model/model.json --output prediction
```

Outputs must be fresh. Desktop training/prediction can use the new `train-paving-expanded-semantics.json` and `predict-paving-expanded-semantics.json` examples. Existing prediction presets retain the previous model; the expanded one is explicit. The comparison CLI requires matching original and expanded datasets plus both sets of saved exclusion checkpoints.

Download previews use park-excluded models and the existing .6 score/.1 margin abstention settings. A blue paving-only overlay is provided for each original source. Softmax is uncalibrated; unmarked pixels can mean another class or abstention, and do not prove there is no paving. Before/after numeric scores use argmax on all frozen annotated pixels, matching the original experiment; they are not thresholded-preview scores.

The newly trained checkpoint was registered, verified and reused in the persistent semantic registry and an actual offline research-cycle replay. That replay reused weights rather than fitting again, left the separate source-pair heads unchanged, and retrieved zero network bytes. The map-guided paving extractor remains separate. No geometry was accepted, no world blocks were generated and no new Windows EXE was built.

Next accuracy work needs more reliable, independently reviewed pedestrian/roof boundaries, better spatial modelling and a genuinely new final test area. Training on the model's own uncertain paving masks would amplify these errors.

Source attribution: Esri World Imagery and its imagery providers. Capture/source-resolution/accuracy observations remain in each retained receipt. Location context for the two additional parks was checked against [LEGOLAND's mapped park location](https://mapcarta.com/25576386) and [Drayton Manor's mapped park location](https://mapcarta.com/W9712254); these do not verify annotation polygons or absolute imagery registration.

The next data stage supplies [native source-traced paving masks](paving-mask-review.md) for four crop areas. They use a distinct binary label contract with explicit unknown pixels, remain provisional, and have not yet retrained this checkpoint.
