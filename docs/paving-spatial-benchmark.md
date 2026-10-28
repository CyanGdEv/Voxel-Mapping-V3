# Frozen spatial transfer benchmark and reserved paving test

This stage benchmarks a pretrained spatial segmentation backbone against the saved RGB paving model, adds explicit test-only mask protection, and audits whether the imagery supplies genuinely finer detail. It does **not** establish an overall accuracy improvement or obtain a verified current higher-resolution replacement.

## Source quality comes before pixel count

The newly reserved area is the central half of a Paultons Park entrance export. Its park/bounds were reserved before fetching RGB; model architecture, feature classes and thresholds were frozen before viewing test predictions. The existing paving fit contains only Alton Towers, Chessington and Drayton Manor. No Paultons source entered fitting.

Esri returned an empty URL and zero dimensions for the requested 1024 export. The same area returned a valid **512 × 512** export, so the source amendment retains that native export without enlargement and uses the same central-half geographic crop (**256 × 256 pixels**). The acquisition code now rejects empty or differently sized exports with a clear error rather than treating the request size as delivered detail. New aerial jobs automatically write `capture-quality.json`, include it in their report/review page, and retain its observations in desktop memory.

The retained export samples approximately **0.348 ground metres/pixel**. Provider metadata at the queried point reports **0.5 m imagery dated 2 May 2025**, plus a coarser background source. Those point observations do not verify the whole mosaic's date, resolution or physical registration. Smaller exported pixels do not imply finer independent optical detail, so the source-quality audit explicitly reports **no verified intrinsic-resolution upgrade**.

The [Environment Agency vertical-photography catalogue](https://environment.data.gov.uk/dataset/dae203a8-ba24-4c54-bab0-866b9faadb58) and its public WFS index identify **10 cm RGBN coverage at Paultons from March 2012**. That is a historical coverage record, not a current image; the ECW image was not downloaded or used as current truth. The queried Towers Street and Thorpe boxes returned no index footprints, which is not proof that no other public source exists. The original capability/query responses and source-quality observations are retained in the download.

## Pretrained spatial model and fitted head

The backbone is [NVIDIA SegFormer B0 trained on ADE20K](https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512), using the [Xenova ONNX export](https://huggingface.co/Xenova/segformer-b0-finetuned-ade-512-512) at revision `d3e5499fa8701ff0453ca940a8dfeae39b2f1504`. The 15.3 MB FP32 model SHA256 is:

`3e5c18a4be395f16646438d54c42377ddc202edfa33d5eced0c9506de75c44c2`

The backbone weights remain **frozen**. A 24-unit binary tanh head is fitted on the existing roof-corrected development masks: 32,000 sampled known pixels, balanced per crop/class. Settings remain 60 epochs, batch 512, learning rate .01, regularization .0001 and seed 137. Only the head learns; there is no end-to-end backbone fine-tuning or GPU training.

Features combine exact RGB with 28 predeclared ADE semantic probability channels. The encoder processes overlapping **native 512-pixel tiles, stride 384**, normalizes with its pinned ImageNet processor, and averages overlapping outputs. Low-resolution semantic probabilities are interpolated onto the original image grid; this does not create optical detail. Target masks, park IDs, coordinates and map polygons do not enter the encoder or head features. A source/backbone/crop/feature-version cache is bounded, hash-checked and non-pickle.

The raw model's zero-shot paving map is the fixed summed probability of `road`, `sidewalk` and `path` at threshold .5. The fitted head uses the same fixed binary decision threshold. These ADE classes come from general scene segmentation, not a specialist aerial pedestrian-surface dataset; domain mismatch is a material limitation.

### Development results

All crops from each park are excluded together, and all methods use exactly the same 267,842 provisional known pixels:

| Method | Paving IoU | Precision | Recall | Mean park IoU |
| --- | ---: | ---: | ---: | ---: |
| Saved RGB model | 55.27% | 63.87% | 80.41% | 48.24% |
| Unadapted SegFormer class mapping | 17.90% | 94.73% | 18.08% | 18.65% |
| Frozen SegFormer + fitted head | 50.50% | 68.49% | 65.78% | 51.29% |
| Always-paving reference | 52.22% | 52.22% | 100% | 53.89% |

The fitted head reduces false positives but loses paving coverage. It does not beat RGB pooled IoU or the trivial reference averaged across parks. These are existing development labels, not a fresh final test. The backbone is not an automatic solution merely because it is pretrained.

## Newly reserved test area

The source-only Paultons annotations were authored and checked after freezing models and before revealing any test predictions. The mask uses explicit non-paving roofs, raised objects, planting and vehicular surfaces; the target is pedestrian paving, not every hard surface. Ambiguous eaves/shadows and a small unclear object remain unknown.

There are **60,390 known pixels** (21,281 paving and 39,109 non-paving), plus **5,146 unknowns**. These are still **provisional assistant visual drafts requiring independent review**, not independent human ground truth. This area is new to this paving fit; absence from upstream ImageNet/ADE20K pretraining is not proven.

| Method | Paving IoU | Precision | Recall | False-positive pixels | Known-boundary F1 | Recalled path pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Saved RGB | 51.56% | 62.29% | 74.94% | 9,654 | 8.43% | 1 / 3 |
| Frozen SegFormer + fitted head | 40.49% | 81.38% | 44.62% | 2,172 | 10.39% | 0 / 3 |
| Unadapted SegFormer mapping | 0% | 0% | 0% | 0 | 0% | 0 / 3 |
| Always paving | 35.24% | 35.24% | 100% | 39,109 | 0% | 3 / 3 |

The spatial head cuts false positives by **77.5%**, but misses more paving, lowers IoU and loses all three connection probes. Its conditional boundary score is still poor. The unadapted road/sidewalk/path mapping predicts no paving in this test. **Do not replace the RGB baseline or claim a general accuracy gain from these results.**

Boundary F1 uses a fixed two-native-pixel tolerance and only fully reviewed neighbourhoods; only 227 target boundary pixels qualify. Unknown eave bands and unreviewed regions are excluded. This is raster agreement with provisional traces, not surveyed physical boundary accuracy. The three source-authored endpoint pairs measure recalled connections within known true paving; false-positive bridges are not credited. As the always-paving result shows, connection recall alone cannot measure good extraction.

## Test protection and reproducibility

`paving_masks build --reserved-test` marks the dataset and each row as test-only, disables research training eligibility and preserves whole-park grouping. Both the RGB and spatial fitting readers reject it. Old development-mask manifests retain their existing hashes and default roles.

The training run writes `frozen-models.json`. A later annotation seal pins that freeze, the test manifest/trace hashes and the three endpoint pairs. The evaluator checks model/design hashes, source/park exclusion and the predeclared central-half crop before inference. A persistent consumed-test record rejects reuse with changed frozen inputs; an identical-input deterministic replay is allowed. The test is now consumed: future model selection needs a different reserved area, rather than presenting another run on Paultons as untouched.

Source records are under `voxel_mapper/data/paving-reserved-test-protocol.json`, `paving-frozen-spatial-design.json` and `paving-paultons-test-annotations.json`. The 1024-to-512 amendment and annotation seal are retained separately. No test score was used to alter models, thresholds, class mappings or the design.

From the updated source checkout and the download directory:

```sh
python -m voxel_mapper.paving_spatial_transfer train --dataset development-dataset --encoder encoder --rgb-baseline rgb-baseline --design frozen-spatial-design.json --output newly-trained --cache feature-cache
python -m voxel_mapper.paving_spatial_transfer evaluate --test-dataset reserved-test-dataset --encoder encoder --rgb-baseline rgb-baseline --training development --design frozen-spatial-design.json --annotation-seal test-annotation-seal.json --protocol reserved-test-protocol.json --output replay-test --cache feature-cache
```

Outputs must be fresh. Use the included original frozen training directory for the second command. A new training run has a new freeze and cannot be substituted into the consumed test without invalidating its original one-shot status. The dataset builder now offers `--reserved-test`; the existing binary/semantic label contracts remain distinct.

The real head-training benchmark ran on two CPU encoder threads in about **18.6 seconds**, peaking around **698 MB RSS**, without Torch or a GPU. The project desktop extra already includes ONNX Runtime. This is a CLI research benchmark, not a new Windows EXE or automatic world-generator update. No source geometry is accepted, no blocks are generated and the earlier RGB/five-class checkpoints are preserved.

## Licence and next accuracy work

The upstream [NVIDIA SegFormer licence](https://github.com/NVlabs/SegFormer/blob/master/LICENSE) limits use to **non-commercial research/evaluation** and requires the complete licence/notices with redistribution. The download includes the unmodified licence, upstream model card/configuration and provenance. The spatial experiment and head remain explicitly research-only.

The result supports testing an aerial-specialist segmentation backbone and improving independently reviewed training masks, especially roof/road/grass negatives and complete narrow paths. A genuinely finer current source still needs acquiring and verifying. The 2012 archive or a larger export cannot be silently treated as that upgrade.
