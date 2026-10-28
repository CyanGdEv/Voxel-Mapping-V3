# Labelled RGB paving training

This stage actually fits **two binary neural models** from the corrected native paving masks, exports their labelled RGB samples and saves both checkpoints in desktop memory. The existing five-class aerial model remains unchanged. The new checkpoints have a separate label contract: 0 non-paving, 1 paving and 255 ignore.

## Source samples and features

The input is the roof-corrected `paving-mask-dataset-v1`: four crop areas across Alton Towers, Chessington and Drayton Manor. The 139,868 positive and 127,974 negative labelled pixels are provisional assistant visual drafts, not independently reviewed human ground truth. Another 303,608 unknown pixels are excluded from fitting and scoring.

A deterministic sampler chooses at most 4,000 pixels per class per crop, producing **32,000 samples**: 16,000 paving and 16,000 non-paving. `rgb-samples.csv` records the exact source RGB bytes, binary label, crop/original coordinates and source/mask SHA256. Coordinates, names, park IDs and hashes are provenance fields, **not model inputs**. Validation reconstructs targets from the literal roof-corrected traces before sampling.

Both neural heads have 24 tanh hidden units and two output classes. All weights learn with Adam, class-balanced cross entropy, 60 epochs, batch 512, learning rate .01, regularization .0001 and seed 137. Settings are fixed across the two feature modes and park exclusions:

- `rgb_only`: only normalized R/G/B enter the network. Remaining input slots are zero, so changes in context cannot affect this model.
- `rgb_context`: the existing 31 RGB/Lab, luminance, local-edge and approximately 1/4/12-metre texture features enter the network.

Context is calculated on the full original RGB image before extracting the labelled crop, avoiding artificial crop-edge neighbourhoods. Normalization is learned only from fitting samples. The implementation is a small NumPy network; **it is not a convolutional segmentation model and does not explicitly learn global path connectivity or complete building shapes**. No map geometry enters either mode.

The common optimizer now accepts an explicit two-class head; five classes remain its default and retain the existing architecture. Binary checkpoints have their own format and validator, and cannot be loaded as five-class semantic models.

## Whole-park development comparison

Every crop from a park is excluded together. Both Alton crops stay in the same fold. Models are evaluated at the fixed .5 argmax decision on exactly the same 267,842 known target pixels, including known negative roofs/grass. Unknown targets remain unscored. No pixel-random split is used.

| Features | Paving IoU, pooled pixels | Precision | Recall | Mean of park IoUs |
| --- | ---: | ---: | ---: | ---: |
| Always paving reference | 52.22% | 52.22% | 100% | 53.89% |
| RGB only | 55.27% | 63.87% | 80.41% | 48.24% |
| RGB + context | 52.08% | 55.34% | 89.85% | 46.97% |

| Excluded park | RGB-only paving IoU | Context paving IoU |
| --- | ---: | ---: |
| Alton Towers | 58.38% | 54.05% |
| Chessington | 56.08% | 53.28% |
| Drayton Manor | 30.25% | 33.56% |

The always-paving reference assigns every known target pixel to paving without learning. RGB-only is only 3.05 percentage points above its pooled IoU; neither trained model exceeds it when averaging parks equally. The reference scores 51.41% at Alton, 63.60% at Chessington and 46.64% at Drayton. This is a modest development result, not reliable general separation.

**Adding context did not improve pooled IoU or precision in this experiment.** It recovered more paving but confused more known negative surfaces with it. RGB-only also makes substantial errors: the held-out Alton preview includes roof and lawn pixels as paving. Drayton transfer is weak. The two large Alton crops contribute most labelled pixels, so pooled scores are higher than the mean across parks. Neither model is ready for accepted world geometry.

This is a three-park **development experiment on previously inspected provisional annotations**, not an untouched blind final test or surveyed/full-image accuracy. The binary targets, native crop sizes, exclusions and task differ from the earlier five-class model's 14.34% paving IoU. **Do not present 55.27% as a direct improvement from that score.** These are different evaluation tasks.

The sampled RGB distributions overlap by 47.125% after quantization into 32-level/channel bins. This descriptive histogram statistic illustrates shared colour ranges; it is not an accuracy score, theoretical error bound or proof that every similarly coloured pixel has the same material.

Numeric scores use threshold .5. Blue review overlays abstain below .6 maximum softmax probability; these scores are uncalibrated, and thresholded previews are not the same as the scored argmax masks. Preview models exclude the pictured park. The final all-data models have seen every supplied crop and have no untouched final test.

## Saved models and desktop jobs

New source desktop jobs:

- **Train paving RGB / context models**: `examples/desktop/train-paving-binary.json`.
- **Predict binary paving**: `examples/desktop/predict-paving-binary.json`.

The real training job completed under the existing worker memory/thread controls with a 6,144 MB configured budget; observed peak worker memory was about **0.5 GB**. No GPU or Torch is required. A repeated deterministic fitting run reproduced identical model hashes. The final job saves both model paths/hashes and park-excluded scores as `paving_binary_checkpoint` memory. Restarting the desktop can reuse the saved files for prediction; it does not need to fit again. This is a source update, not a newly built Windows EXE or installation on the user's PC.

Checkpoint SHA256:

- RGB-only: `096941b8b5a7ddd0c48f25b47359771d26ae4c4c82d7f1deb0a52cad866df8fc`.
- Context: `a6eaa7dacc73778637f7b1cbef120a85449405db5636d2c4343c322be9d6dca4`.

From an updated source checkout and the download directory:

```sh
python -m voxel_mapper.paving_binary_learning train --dataset dataset --output newly-trained
python -m voxel_mapper.paving_binary_learning predict --image demo-source/source-image.bin --receipt demo-source/imagery-receipt.json --model training/models/rgb_only/model.json --output prediction
```

Outputs must be fresh. Originals are limited to one megapixel for this feature extractor; mask datasets stay bounded at two megapixels of crop data. Inference uses only the source RGB, retained image scale and saved model; it requires no target mask or map references. Training datasets require at least three distinct parks, preserve source-pinned whole-park grouping, and keep binary unknowns out of sampling. Cancellation is checked during feature extraction and optimizer batches.

Review `training/index.html`, the source-linked CSV, all exclusion fold models/previews and `training/report.json`. Preserve both the old five-class model and both binary feature variants. Further work needs more independently reviewed negative examples, especially varied roofs and visible grass in additional parks, plus a spatial segmentation architecture and a genuinely unseen final test area. Automatically treating these predictions as new labels would reinforce the remaining errors.

No inferred geometry is accepted, no world blocks are generated, and the general research cycle's five-class checkpoint is not replaced. Source attribution remains Esri World Imagery and its imagery providers, with original receipts, crop coordinates and source hashes in the input mask dataset.

The next [frozen spatial transfer benchmark](paving-spatial-benchmark.md) preserves these RGB weights and adds a newly reserved test area. The spatial prototype reduces false positives but does not improve overall paving IoU; current higher-resolution replacement imagery remains unverified.
