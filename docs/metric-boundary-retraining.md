# Metric boundary checks and mixed UK/Dutch correction

This pass implements physical-distance boundary checks, source-reviewed error
labels, and a real mixed-source correction fit. It improves provisional region
scores on two new Walibi crops, but **does not improve held-out boundaries**.
The existing model is retained. RGB-only correction is disabled by class guards,
avoiding the previous UK transfer regression.

## Results and scope

The new excluded parks are Paultons Park and Walibi Holland. Walibi contributes
two correlated crops, one around the entrance plaza and one around a visible lake
bank. These are two parks, not three independent sites. Neither park supplies any
fitting pixels or setting-selection scores. All source references and interior
windows were sealed before correction fitting; the model and strengths were
sealed before any new-site baseline or corrected predictions were computed.

| Excluded source | Boundary samples | Mean boundary error before / after | Known-interior macro IoU before / after |
| --- | ---: | ---: | ---: |
| Paultons Park, RGB-only | 8 | 1.970 / 1.970 m | 97.80% / 97.80% |
| Walibi entrance plaza | 0 | Not sampled | 49.86% / 52.44% |
| Walibi lake bank | 5 | 0.362 / 0.382 m | 44.91% / 48.62% |
| All excluded boundary samples | 13 | 1.352 / 1.359 m | Not pooled across different class scopes |

Missing directed edges receive the same 4 m penalty at every image scale. Two
excluded edges are missing both before and after correction. The shoreline's
2 cm mean difference is far below its 32 cm reference uncertainty. No meaningful
boundary improvement or deterioration is established. The Paultons windows are
easy, homogeneous class interiors: their 97.8% IoU alongside 1.97 m boundary error
demonstrates why interior scores alone cannot establish precise geometry.
All new labels are partial assistant source-assisted drafts, not independent
human or surveyed truth. They do not measure whole-scene completeness, every
narrow path, every grass island or ground hidden beneath trees.

The raw declared 0.25 RGB-only candidate improves the consumed tight-garden mask
28.99% → 36.54% macro IoU and Towers Street/Mutiny Bay 54.58% → 56.77%. It also
reduces Lightwater Valley grass IoU by 5.52 percentage points and Gulliver's grass
IoU by 2.07 points. The per-source/class guards reject it. The selected RGB-only
strength is therefore zero; all seven RGB-only ground PNGs, including Paultons,
are byte-identical to the frozen baseline. Unselected development preview PNGs
and all rejected candidate scores remain in the bundle. They are fitted-source
diagnostics, not unseen improvements.

The RGB/CIR group selects strength 0.25. On consumed development masks, Efteling
macro IoU changes 78.41% → 80.97%, and Toverland 61.53% → 65.01%. These are not
independent validation scores. Both newly excluded parks are now consumed and
must not be reused as fresh tests for another fitting decision.

## Metre-based measurements and reviewed supervision

The old pixel sampler remains unchanged for historical results. This new sampler
uses a common ±4 m normal search, 0.5 m probes and explicit x/y ground sampling.
UK sampling is derived from the actual exported Mercator extent and geodesic
pixel distances; Dutch sampling uses the exact RD New grid. Anisotropic pixels
are handled by transforming the boundary normal in physical space. A 2 cm
computational profile step does not create 2 cm optical or surveyed accuracy.
Earlier Dutch-only numbers used different samples and a 3.2 m cap, so they are
not directly comparable to this run.

There are 39 accepted development transects and 13 excluded-check transects.
Source-only review removes roof seams, planter interiors, tree shadows, guides
inside surfaces and unobservable ground margins. Native coordinate crops and
colour profiles correct several small-path proposals that had landed on the
wrong strip. Rejected candidates and explicit source adjustments are retained.
The prior Dutch references keep their 0.40 m uncertainty; new sharp bank edges
use 0.32 m. UK bounds reflect sampling and source visibility, not an invented
sub-pixel precision claim. There is no independent human reference review.

Both capped absolute displacement and excess beyond the reference uncertainty
are reported. A missing edge never disappears from the average. Probe matching
requires the explicit opposite surface when known; probes inside the reference
uncertainty band are flagged. Unknown opposite surfaces do not become training
labels. No foliage-hidden ground is promoted to observed truth.

Every fitting pixel is excluded within a physical 4 m circle around a calibration
check, including old interior masks and new boundary bands. Boundary bands leave
at least the recorded uncertainty interval unlabelled. New-park footprints pass
a conservative 100 m geographic context separation from every development crop;
all 24 fresh/development source pairs are checked. Whole-park identities are
excluded from fitting and selection, including both Walibi crops together.

## Actual fit and selection

Eight development images combine the six prior UK sources with Efteling and
consumed Toverland. Duinrell and Flamingo Land remain excluded. The same frozen
20-channel baseline and FLAIR encoder are used. A 27 → 32 → 16 → 4 residual MLP
fits 71,394 samples for 600 steps, seed 137, batch 2048,
AdamW learning rate 0.003, weight decay 0.001 and residual penalty 0.002. The
1,492 learned parameters change from initialization.
Canopy predictions and base weights remain unchanged.

Inputs remain RGB, rendered CIR colours, frozen class probabilities, relative
height/slope/roughness/validity, chromatic ratios and local colour statistics.
Coordinates, site IDs and marker distances are never network features. Sampling
balances availability groups and then sources, with 35% observed boundary draws.
Baseline mistakes receive increased weights; CIR fields are dropped in 25% of
draws. Coarse draft interiors are eroded by a physical distance before sampling.

The declared strengths 0/0.25/0.5/0.75/1.0 are checked separately for RGB-only and
RGB/CIR inputs, with smoothing disabled. Selection minimizes calibration-check
uncertainty excess and capped error, subject to no development source losing
more than 0.5 macro-IoU points or one supported class losing more than one point.
These guards use consumed development masks and do not assert generalization.
Source and checkpoint pins prevent changed reservations from being scored under
a stale seal. Fresh labels and scores never select strengths. No production
checkpoint or world geometry is replaced.

## Sources

New Dutch RGB/CIR use fixed 2025 PDOK annual layers at 8 cm sampling; AHN4 retains
native 50 cm NAP rasters from 2020–2022. New Paultons imagery uses Esri World
Imagery at approximately 25 cm exported sampling. Point metadata, original RGB
bytes and provider URLs are retained; neither exact whole-image capture dates
nor whole-image optical resolution are inferred from export dimensions.
Matched EA dated DTM/DSM source rasters are native 1 m ODN cells. Datum grids,
survey identity, dates and no-data cells are preserved. Only relative heights
enter learning; absolute NAP and ODN heights are not mixed. These are raster
height cues, not raw point-cloud observations or proof of paths beneath trees.
RGB/CIR and height epochs differ. Missing height stays missing. CIR is a rendered
visual cue, not calibrated NIR reflectance. Tree-crown accuracy is not tested.

## Verification and replay

63 relevant tests pass, including physical scale invariance, anisotropic normals,
missing-edge penalties, uncertainty bands, metric check guards, source reservation,
stale-seal rejection, balanced fitting, strict class guards and prior source/model
behaviour. A repeat 600-step fit reproduces all weights and losses exactly. All
three new native height grids replay exactly; all RGB-only output PNGs match the
baseline exactly. Safe reload produces identical residuals for all 11 sources.
The successful main run used two CPU threads, no GPU, 102.8 s
and 819.0 MiB peak process RSS. It reuses source-only
development caches, so these timings exclude initial cache preparation,
acquisition, the verification repeat and the stopped disk-full attempt.

An earlier invocation exhausted workspace disk space before saving any checkpoint
or predicting a fresh park. Only regenerable temporary replay caches were cleared;
source data, annotations, model weights and downloads were retained. The same
fixed schedule and sources were then rerun. Its stopped log is included.

The offline review shows original RGB/CIR, reference interiors, before/after
regions, measured markers and display-only relative heights for all 11 sources.
All crops preserve source coordinates and aspect ratio, including the 1280 × 512
Towers Street image. It exposes every accepted marker and the negative findings.
The downloadable CSV lists all 52 paired measurements, including missing edges.

The bundle includes clean source bytes, source/height receipts, aligned relative
height arrays, all new raw source acquisitions, draft masks, protocol and seals,
review/rejections, safe base/correction weights, sampled fitting arrays, before/
after predictions, rejected development previews, tests and source patch.
Large frozen encoder weights remain the unchanged separate dependency
`Aerial-Encoder-Research.zip`; apply the source patch to this repository and use
the research Python dependencies. The two portable replay modes are:

```sh
python replay_bundle.py fit --bundle BUNDLE --output NEW_FIT_REPLAY
python replay_bundle.py predict --bundle BUNDLE --encoder PINNED_ENCODER --output NEW_PREDICTION_REPLAY
```

Fitting replay uses the recorded 71,394 transformed feature samples and checks
every weight/loss. Prediction replay regenerates full source features serially
and checks all 33 ground/canopy PNGs. These are consumed-data reproducibility
checks, not new independent tests. Neither command deploys a model.
Both commands were run successfully from the final bundle layout: the safe
weights file and all 33 prediction PNGs match exactly after replay.

The next geometry improvement needs supervision that separates correct region
classification from correct edge placement, with more dense native boundaries
and a spatial refinement model. The RGB-only grass/roof conflicts above should
be resolved on development data before reserving another fresh test area.

RGB/CIR © Beeldmateriaal / Het Waterschapshuis, CC BY 4.0; AHN heights CC0; EA
height OGL-UK-3.0. Esri/provider terms and attribution remain attached to its
imagery; it is not relicensed as open imagery. The frozen encoder and derived
checkpoints retain upstream NVIDIA non-commercial research/evaluation scope.
