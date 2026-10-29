# Aerial marker error measurement and correction

The pipeline now samples source-bound surface edges, measures signed marker
displacement and missing edges, and uses the measured errors to weight correction
training. A real CPU fit and a prospectively excluded crop were completed.
The candidate gives a small overall image-relative error reduction, but its
per-surface and UK transfer results are mixed. **Retain the existing model.**

## Measured result

All distances below are normal offsets relative to assistant-reviewed aerial
pixels, not independently surveyed ground geometry. A missing directed boundary
gets a 3.20 m search-cap penalty and remains in the average. Detected-only medians
are reported separately so missing edges cannot improve the score by disappearing.

| Cohort | Samples | Capped mean before | After | Edges found before / after |
| --- | ---: | ---: | ---: | ---: |
| Fitting boundary samples | 19 | 1.076 m | 0.980 m | 15 / 16 |
| Nearby-excluded calibration checks | 6 | 0.343 m | 0.317 m | 6 / 6 |
| Excluded Duinrell crop | 12 | 1.198 m | 1.064 m | 11 / 11 |

Duinrell's detected-only median changes 1.01 m → 0.39 m. Its capped mean changes
by 0.133 m (11.1%), which is smaller than the 0.40–0.48 m reference placement
uncertainty. These small, spatially correlated samples do not establish a
statistically reliable or surveyed improvement.

| Duinrell surface | Samples | Mean before | Mean after |
| --- | ---: | ---: | ---: |
| Paving | 7 | 0.669 m | 0.726 m |
| Structures | 3 | 2.237 m | 1.490 m |
| Water | 2 | 1.490 m | 1.610 m |

The two additional RGB-only UK compatibility checks use already-consumed fitting
sources. Towers Street/Mutiny Bay macro IoU falls 54.58% → 53.06%; tight gardens
falls 28.99% → 25.38%. They are diagnostics, not independent validation, and did
not change any learned weights or selected settings. This Dutch calibration
does not support general use on the UK scenes. The release decision therefore
retains the baseline. There are no accepted positive tree-crown boundaries, so
tree accuracy is untested. Paving/grass interfaces test the two sides locally;
they do not establish lawn or grass-island completeness.

## Source review and split

The new Duinrell/Tikibad crop covers 81.92 × 81.92 m on an exact 1024-square
RD New grid at 8 cm sampling. Selection and source-only boundary review preceded
all Duinrell model predictions. Efteling and Toverland are calibration sources;
Toverland is explicitly consumed from the earlier experiment.

The final 37 observed normal transects consist of 19 fit, six calibration-check
and 12 excluded-check references. Assistant visual review rejects ambiguous
shadows, roof seams, vegetation-concealed shorelines and guides inside surfaces.
Source-gradient proposals are only candidates: explicit outer-edge adjustments
and rejected samples are retained. These are assistant source-assisted draft
references, not independent human annotations. Reference colours and coordinates
do not enter image features. Occluded ground is never inferred as observed truth.

The model trains on eroded draft interiors and observed boundary bands from the
two calibration crops. Every fitting pixel, including interiors and bands, is
excluded within four metres of each calibration-check point. A three-pixel band
around a reference remains unlabelled in fitting; opposite surfaces are labelled
only when explicitly identified. Boundary weights increase with baseline error
or a missing edge, capped at four. All 12 Duinrell references and every Duinrell
pixel are excluded from fitting and setting selection.

The original protocol was pinned before correction fitting and fresh predictions.
Source references, checkpoint and selection settings were sealed before scoring
Duinrell. Its scores did not select settings; it is now consumed and cannot be
reused as a new blind benchmark. A measurement-only replay corrected the explicit
opposite-class probe to require that class, rather than any different surface.
The original measurements are retained. All boundary positions, distances,
weights, candidate selection and final settings are exactly unchanged.

## Actual learned correction

The base checkpoint `c416a9016ee3465969e8e831abdc4b9f9d8829d097061378a386c096cd552449` and the pinned FLAIR
encoder remain frozen. A zero-initialized residual MLP, 27 → 32 → 16 → 4,
adds logits to the four ground probabilities. Its 1,492
parameters fit 31,552 guarded samples for 600 steps,
seed 137, batch 2048, AdamW learning rate 0.003, weight decay 0.001 and residual
penalty 0.002. Rendered-CIR fields are dropped for 25% of fit draws. That dropout
alone did not provide reliable RGB-only UK transfer.

Inputs are native RGB, rendered CIR colours, chromatic ratios, frozen base
probabilities, relative LiDAR height/slope/roughness/validity, local RGB mean,
standard deviation and gradient. Coordinates, site identifiers and reference
errors are never network features. Canopy inference remains exactly unchanged.

The eight declared candidates combine residual strengths 0.25/0.5/0.75/1.0 with
zero or five-step source-colour smoothing. Selection minimizes capped mean
boundary error on the six calibration checks, rejecting a greater-than-five-point
macro IoU drop on their guarded known pixels. Stronger correction improved these
few boundary checks but damaged their pixel scores, so the guard rejected it.
Selected settings: strength 0.25, smoothing off. There is no automatic promotion.

PDOK RGB/CIR use fixed 2025 annual layers. AHN4 retains native 0.5 m NAP height
rasters from 2020–2022. Valid height neighbourhood fractions are 31.44% Efteling,
40.52% Toverland and 60.40% Duinrell. Missing cells are never filled as terrain.
Relative heights enter learning; NAP absolute heights are not mixed with UK ODN.
CIR is a rendered visual cue, not calibrated NIR reflectance. No 8 cm height or
independently surveyed image registration is claimed. Aerial roof edges also
need not equal building ground footprints.

## Verification and review

47 relevant tests pass, covering signed/missing/reversed edges, explicit opposite
classes, unknown bands, source matching, guard exclusion, fresh-site rejection,
fitting, safe reload/tamper checks, selection regressions, optional base
probabilities and existing source/grid/LiDAR/reservation behaviour. An exact
600-step repeat fit reproduces every correction weight and recorded loss.
All three native height and descriptor grids replay exactly. Base weights and
prior calibration ground/canopy PNGs match their previous values exactly.
A clean replay from the downloadable bundle regenerates both calibration encoder
caches, exactly refits the correction and matches all nine prediction PNGs and
all cohort metrics. This is a reproducibility check on consumed data.
The main run used two CPU threads, no GPU, 65.6 s and
812.7 MiB peak process RSS, excluding acquisition, the
additional UK diagnostics and the verification repeat.

The offline review compares raw source pixels with before/after markers,
uncertainty rings and all accepted samples. Every remaining error is selectable;
the queue is sorted by remaining error. Original RGB/CIR, model ground overlays
and display-only relative height share the exact same pixel frame. The browser
checks 30 view combinations, all 37 marker selections and 15 decoded images,
plus source frame dimensions, mobile layout and absence of external requests.

The bundle contains the original three Dutch RGB/CIR/height sources and receipts,
draft calibration masks, references/rejections, protocol/seals, frozen base head,
learned correction safetensors, sampled fit arrays, predictions, measurements,
selection details, repeat checks, rights, source patch and this review.
Large encoder weights are a separate unchanged dependency in
`Aerial-Encoder-Research.zip`; apply the source patch to this repository and use
the research Python dependencies. No new Windows EXE, model deployment or world
geometry is part of this experiment.

Replay the recorded experiment after extracting the bundle:

```sh
python rebuild_marker_run.py --bundle BUNDLE --encoder PINNED_ENCODER --output FRESH_REPLAY
```

The helper regenerates the two calibration RGB feature caches, checks their pins,
and replays fitting, selection and consumed-crop scoring. It does not create a
new independent benchmark. For another improvement run, collect source-reviewed
narrow paths, shoreline and roof-overhang errors, broaden UK/RGB-only fitting,
and reserve a different source area before fitting. Independent human reference
review is needed to support stronger accuracy claims.

RGB/CIR: © Beeldmateriaal / Het Waterschapshuis via PDOK, CC BY 4.0. AHN height:
CC0 according to retained capabilities. The unchanged encoder and derived
checkpoints retain the NVIDIA upstream non-commercial research/evaluation scope;
data licences do not expand model rights.
