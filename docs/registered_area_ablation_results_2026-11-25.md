# Real-data registered-area ablation results

Training-only continuous input scaling substantially improves the full-context
model, but does not establish a reliable replacement for RGB. Full context with
fixed physical scaling loses to RGB in every held-out area. With fitted scaling,
it wins in two areas and loses in the third. Retain the existing RGB baseline;
promote no checkpoint and change no Minecraft blocks.

Code: `4620bae3a21cb2f5632942945ccd9f2126af0022`, PR #171 stacked on draft #170.
The two PRs remained open/draft when inspected. GitHub Tests (45593333073) and
GIS evidence checks (45593332985), including training smoke, passed. Local
regression suite: 48 tests passed.

## Executed comparison

72 completed runs: eight modes, three areas, seeds 41/42/43, 20 epochs each.
All 63 source-versus-RGB pairs pass the existing comparison checks for identical
training/validation samples, source hashes, class maps, seeds and hyperparameters.
Standalone candidate inference reproduces all 72 validation confusion matrices,
including checkpoints with fitted scaling and the zero-context control.

Three-seed mean validation IoU, averaged over classes with reviewed pixels:

| Input | East | South | North | Equal-area mean |
|---|---:|---:|---:|---:|
| RGB | 95.29% | 93.48% | 85.37% | 91.38% |
| 28-channel zero context | 91.48% | 88.23% | 92.91% | 90.87% |
| RGB + vectors | 68.67% | 58.31% | 51.92% | 59.63% |
| RGB + satellite land cover | 97.09% | 84.56% | 87.08% | 89.58% |
| RGB + height | 96.40% | 91.47% | 85.41% | 91.09% |
| RGB + intensity | 96.74% | 93.91% | 75.57% | 88.74% |
| Full context, fixed scaling | 82.56% | 71.23% | 61.26% | 71.68% |
| Full context, training-only p95 scaling | 97.77% | 86.95% | 92.19% | 92.30% |

Equal-area mean weights areas equally despite unequal label counts. These are
validation-selected checkpoints, on conservative grass/unspecified-paving
interiors from one RGB acquisition. They are not park-wide, fine-material or
cross-park accuracy. There is no independent final test. Multiple ablations
provide diagnostic evidence and cannot themselves establish deployment fitness.

## Coverage and source conflicts

| Holdout | Unique training cells | Unique validation cells | Minimum image buffer |
|---|---:|---:|---:|
| East | 2,097 | 236 | 335.21m |
| South | 985 | 1,170 | 36m |
| North | 438 | 827 | 46m |

The three holdouts cover 2,233 distinct reviewed cells: 474 grass and 1,759
unspecified paving. Another 100 paving cells belong to a one-class area and are
not a binary holdout. Repeated seeds and overlapping training windows do not
increase the number of independent reviewed locations.

At reviewed validation cells, height validity is 69.1%, 75.0% and 76.4%; intensity
validity is 92.8%, 89.0% and 90.0%. Unknown cells remain unknown. Water context is
unavailable. Habitat presence and satellite class are constant in the eastern
holdout; available does not imply informative. Raw intensity values occupy a
small part of the fixed 0–65535 range. Fitted p95 caps use positive training
inputs only, including overlap observations, and persist for inference.

Visual overlay review shows the generalized 5m building-context mask spanning
an open courtyard: it covers all 113 reviewed eastern grass cells and 64/123
paving cells. Building presence covers no grass cells in either other holdout,
and 28/879 and 235/757 paving cells respectively. This is contextual disagreement,
not permission to relabel reviewed ground or manufacture refined footprints.
The poor vector-only results are consistent with this conflict, but the
experiments do not isolate a causal contribution for each vector channel.

The zero-context control changes sign across areas. Different input widths and
initialization can affect small-data comparisons, but do not explain away the
large full-context regression. No single contextual source improves every area.
Scaling helps full context in all three areas, yet the southern mean remains
6.53 percentage points below RGB. Its equal-area advantage is only 0.92 points.

## Crop-edge diagnostic and confidence

Existing eastern checkpoints were also evaluated without retraining on a crop
expanded by 64 pixels. Checks confirm identical bytes for all 46 training RGB,
label and context inputs, identical 236 reviewed validation coordinates/labels,
and unchanged inference tile phase. Fixed-checkpoint RGB mean changes from
92.37% to 94.23%; full context from 80.88% to 81.17%. Individual effects are
mixed. Crop edges do not account for the contextual weakness. The new matrix
selects checkpoints against the expanded protocol, so its results differ from
this fixed-checkpoint diagnostic.

Per-class precision, recall, IoU, false-positive rates, unsupported-class
predictions, and confidence reliability are retained in the machine-readable
results and held-out evaluation artifacts. Mean 15-bin top-label ECE for scaled
full context is 0.321 east, 0.276 south, 0.308 north. This is descriptive
validation reliability, not evidence of calibrated confidence. No confidence
threshold has been approved for material placement. True boundary accuracy
cannot be measured from eroded interiors; missing reconstruction geometry
cannot be measured from these classification rasters. Neither metric is invented.

## Preservation and next development gate

The environment restart interrupted three unfinished runs. Completed artifacts
were retained; source hashes/configuration were checked before those three runs
were restarted. Partial output was quarantined and not reused as a checkpoint.
All 72 final checkpoints have completed training reports and exact inference
confusion-matrix agreement.

The original Bedrock archive still hashes to
`0cf1c7712eb4d57f79425fc706a25afc6d521dc1c8f98deb192a6b605ecb6431`.
No production model replacement, world save or block placement occurred.
Unspecified paving remains without an invented fine material.

Next development should test a conservative context-fusion mechanism against
these fixed area splits, retaining RGB behavior when context is weak or
conflicting. It needs a new independent reviewed area for final selection,
fine-material labels, and calibration before accepted AI-to-block changes.
World integration should then produce a bounded block diff against the preserved
baseline and verify a native Bedrock round trip. Shared lineage, unknown RGB
acquisition/licensing scope, missing Magic Kingdom data, the 19 unregistered
views, partial habitat acquisition and OS download proxy failure remain open.

Method/reproduction: `registered_area_ablation_method_2026-11-25.md`.
Exact hashes, settings, coverage, per-seed statistics and diagnostic matrices:
`registered_area_ablation_results_2026-11-25.json`.
