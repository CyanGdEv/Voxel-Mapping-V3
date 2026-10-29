# Tight-path and hidden-detail training

The user reference marks structures in purple and paving with red/light-red dots. These meanings are bound to this image's checksum, without changing purple track, barrier or roof examples elsewhere. They supervise projected guide locations, not complete paving polygons, structural dimensions or object heights.

The image was located against the full-park aerial and registered to a separate 1,536 × 1,536 clean Esri image with 460 inlier features and a 1.70-pixel 95th-percentile residual. Pinned OSTN15 georeferencing and the park's matched native one-metre DTM/DSM provide height context. Image residuals are not independent physical accuracy. Export spacing is also not proof of finer optical imagery detail.

## Source-quality filtering

Both red tones share the paving-guide class, and purple uses a generic structure-guide class. Broad colour components are rejected using a configurable stroke-radius bound. The clean source is warped into the annotation frame, then each candidate ink pixel is compared with a local five-by-five clean neighbourhood. Candidates matching a natural colour within 18 RGB RMS units are withheld. This suppresses naturally red/orange theming, cars and roofs while retaining many pale guide dots. Automatic extraction remains unverified; this is an explicit digitisation rule, not human confirmation of every pixel.

The filter was added after visual inspection and an initial development fit exposed natural-colour contamination. The corrected reference has 12,858 projected paving-guide pixels and 7,391 structure-guide pixels. Gaps remain ignored. Original reference bytes, source receipts, labels, class mappings and rejected-candidate counts are retained. No missing path is closed or polygon filled from a dot alone.

## Actual experimental training

Two 48-hidden-unit neural heads are fitted for 80 epochs from clean input: 31 RGB/Lab/metre-context features, and those features plus six native-height descriptors. The latter use height above ground, slope and local height statistics/validity. Absolute coordinates, absolute ODN levels and annotation RGB are excluded from model features. Feature extraction uses tiles with full physical halos, so narrow details retain the original clean-image samples without a park-sized feature cache.

Sampling retains one guide location per BNG metre cell and class. Of 6,104 samples, 3,205 fit the networks, 2,033 are held for development scoring, and 866 in the guard are ignored. The first predeclared easting split with sufficient class coverage is selected using labels only. Minimum train-to-held separation is 30.24 m, exceeding both twelve-metre feature contexts.

These heads distinguish **paving guides from structure guides**. They are not full paving/non-paving segmenters or general path detectors: unmarked grass, water and background are not fabricated as negatives.

| Development guide score | RGB | RGB + height |
|---|---:|---:|
| All held guide macro F1 | 0.5969 | 0.6077 |
| Raised/canopy-context held guide macro F1 | 0.4705 | 0.3828 |

The raised/canopy subset contains 190 held guides, including 104 paving and 86 structure guides. Height features worsen this subset despite a small overall gain. The **RGB checkpoint is retained**. Its held structure recall is only 16.0%, so neither checkpoint establishes reliable general structure capture or hidden-path geometry. Both new parameter sets are saved for inspection; existing production weights and world blocks remain unchanged.

The original overall-only selection design is preserved. A post-fit acceptance review rejects the height candidate after observing the canopy regression, without refitting or modifying its weights. Future runs encode this guard before fitting: height must avoid overall and canopy-subset regressions, with at least 32 examples of each class in the latter subset. The label revision and acceptance-rule review mean these same-image scores are development diagnostics, not an untouched blind test or evidence of new-park accuracy.

## Replay and checks

```sh
python -m voxel_mapper.aerial_feature_supervision \
  --reference user-reference.jpg --clean clean-rgb.png \
  --receipt imagery-receipt.json --frame frame.json \
  --legend voxel_mapper/data/tight-path-paving-aerial-legend.json \
  --dtm ea-national-dtm.tif --dsm ea-national-dsm.tif \
  --output FRESH-REFERENCE
python -m voxel_mapper.tight_trace_learning \
  --dataset FRESH-REFERENCE --frame frame.json --output FRESH-TRAINING
```

The semantic network fitter now accepts an explicit bounded feature count, retaining the default 31-feature fit exactly. Other checkpoint validators keep their original dimensions; these 31/37-feature research trace checkpoints have a distinct version and checksum contract.

Both saved networks, loss histories and all sample probabilities replay exactly from cached clean features. Tests cover tile-edge equivalence, physical holdout guards, old-fit compatibility, height checkpoint dimensions, natural red versus pale annotation ink, thin strokes, image-local roles and rejection of canopy regressions. Existing semantic/paving/path-supervision tests pass. No model probabilities are converted into new paving polygons or world edits.

Attribution: user-supplied guides, Esri World Imagery/providers and Environment Agency information (OGL-UK-3.0). Source dates differ, projected hidden guides lack independent survey truth, and height features retain native one-metre resolution.
