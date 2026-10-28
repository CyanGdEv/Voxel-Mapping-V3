# Dense surface labels and boundary replay

Seven source-reviewed draft windows were added around paths/grass, pale roofs,
water and shoreline banks at Lightwater Valley, Gulliver’s World and Chessington.
Three real 400-step CPU fits completed. **Denser labels improve the tight-garden
development test; interface/path oversampling does not improve it.** Production
weights remain unchanged. No final checkpoint is automatically promoted.

## Fixed development results

| Development image | Variant | Paving IoU | Structure IoU | Grass IoU | Water IoU | Canopy IoU | Paving boundary F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| user-towers-mutiny | parent | 74.85% | 80.04% | 74.08% | 15.01% | 27.38% | 19.77% |
| user-towers-mutiny | dense_labels_only | 72.57% | 73.58% | 74.70% | 0.00% | 50.33% | 3.43% |
| user-towers-mutiny | boundary_replay | 57.97% | 80.04% | 43.97% | 0.00% | 44.25% | 12.19% |
| user-gardens-lake | parent | 58.87% | 53.40% | 51.61% | 89.63% | 11.26% | 6.66% |
| user-gardens-lake | dense_labels_only | 54.22% | 51.46% | 45.90% | 99.37% | 35.50% | 6.94% |
| user-gardens-lake | boundary_replay | 18.97% | 60.98% | 31.00% | 99.18% | 29.82% | 2.88% |
| user-tight-gardens | parent | 16.93% | 1.35% | 42.39% | — | 37.49% | 0.00% |
| user-tight-gardens | dense_labels_only | 30.32% | 57.74% | 45.56% | — | 73.68% | 0.00% |
| user-tight-gardens | boundary_replay | 11.42% | 32.38% | 36.63% | — | 72.28% | 0.00% |

All three Alton views stay excluded together from both development fits. Their
image, ground, canopy, dense-window and inferred-ground hashes are unchanged.
The parent is the previous expanded Alton-held-out checkpoint (#154), not the
older single-Chessington fit. All scores below are on previously consumed Alton
development labels, not a fresh unseen or independent human benchmark.

Local tight-path connections are **1/5 parent, 2/5 denser labels, 1/5 boundary
replay**. All three retain **0/2 false grass bridges**. Denser labels improve
paving IoU from16.93% to30.32% and structure IoU from1.35% to57.74% on that view.
Canopy improves from37.49% to73.68%. This recovers the older model’s2/5 path
result, not a new best connectivity result. Boundary F1 there remains0: these
few known interfaces still do not demonstrate accurate transferred edges.

The denser-label fit also improves garden-lake water IoU89.63%→99.37% and canopy
11.26%→35.50%, but reduces that view’s paving58.87%→54.22% and grass51.61%→45.90%.
Towers Street paving also declines74.85%→72.57%. Interface replay worsens paving
across all three views. Those regressions are retained, not tuned away. Its final
six-image fit was predeclared and completed before reading development scores;
it remains experimental, even though it is not the stronger development variant.

## Labels and exclusions

The seven crop scopes contain 48,343 known ground pixels (some revise existing
labels) and 950 paving-side interface pixels eligible for the partial boundary
metric. They provide adjacent path/grass and structure/paving labels, not
just isolated interior colour samples. An eighth mixed roof/court crop was
rejected before fitting. Literal polygons were traced against unmarked RGB and
cross-checked against the existing dated one-metre LiDAR context. Fine source
image pixels do not establish surveyed accuracy. These are assistant drafts;
independent human review is still outstanding.

Shadows, canopies and uncertain shore banks remain unknown. Water regions are
conservative visible samples separated from banks by unknown strips: they add
water context but **no water-edge precision claim**. All previous canopy-positive
pixels remain canopy-positive; inferred ground never becomes observed paving.
Only three training images have overlay changes; all labels outside the seven
window footprints are unchanged. Parent datasets remain untouched. The dataset
rebuild reproduces its complete manifest exactly, with27 unchanged-asset checks.

Flamingo Land is absent from the derived six-image dataset, feature reads,
fitting, evaluation and preview outputs. Its earlier scores were not rerun or
used for selection. This round has no new reserved park.

## Fixed training

The protocol SHA256 is `21c55d30d371d956ba95746df78e0b74a54c16ae00ee649445ec90b5616bfb18`.
Labels are source-bound and sealed before candidate fitting; all three fits and
checkpoint identities are sealed before development scoring. The two variants
share seed137,400 steps,batch4,96-pixel patches,learning rate0.002, two threads,
balanced loss and15% LiDAR dropout. They use the same18,482-parameter20-channel
head and unchanged frozen aerial encoder plus the existing four LiDAR fields.

`dense_labels_only` retains ordinary sampling. `boundary_replay` allocates40%
of patch anchors to observed class interfaces,30% to labelled narrow paving and
30% to ordinary class sampling, with fallback when an anchor family is absent.
Actual held-out-fit draws were639 interface,488 narrow and473 ordinary. Anchors
come only from fitting labels; unknown/crop edges never manufacture interfaces.
Narrow sampling uses source-specific ground sampling, not an assumed one-metre
image grid. The four-metre width setting is a sampling estimate, not surveyed
path width. Inherited defaults and the old narrow-only sampling sequence remain
unchanged. A zero-interface configuration gives exactly the default tensor fit.

There was no hyperparameter search, repeat seed search or selection based on
development scores. The final all-six checkpoint uses the predeclared replay
variant; fitted views are explicitly labelled training previews, not validation.
Each final prediction matches a safe checkpoint reload exactly. Total time was
183.9s, peak RSS1033.5MiB,CPU only.

30 relevant tests pass:8 dense-overlay/review/sampling tests,8 layered-learning,
6 LiDAR-context and8 reservation/source-pin tests. They cover stale review pins,
excluded source rejection, canopy/inference protection, default-fit equivalence,
real sampler updates, checkpoint safety and source-feature checks.

## Review and reproduction

The browser decoded52 source/layer/development images, matched native crop grids,
checked captions and mobile layout, persisted notes, and downloaded a test export.
There were no runtime errors or external requests. The automated export passed
backend source-pin validation without changing labels.

The self-contained HTML displays all seven RGB/label/LiDAR/fitted crop sets,
plus unchanged Alton source/target and all three development predictions. It
records per-window accept/reject/correction notes and exports source-pinned JSON.
Decisions are review notes only: they do not rewrite training masks or establish
independent truth automatically. `validate_review` rejects stale label/source
pins; `python -m voxel_mapper.dense_boundary_replay review-notes --help` exposes
the read-only validator. Browser-test decisions are marked automation, not human approval.

The download contains the pinned six-image dataset, literal annotations,
protocol/seals, three new safe checkpoints, parent held-out head, all scores,
source changes and licence/cards. Use the earlier Multi-Park-Native-LiDAR.zip
and Aerial-Encoder-Research.zip for unchanged source arrays/encoder. The included
`prepare_features.py` regenerates source-only caches without reading Flamingo.
The built dataset preserves its exact ID; rebuilding overlays requires the
previous parent dataset. The code patch requires the repository and optional
research dependencies. No Windows EXE or world geometry was rebuilt.

Next precision work should correct these draft boundaries with independent
review and add more shadowed/narrow examples before another fixed comparison.
The failed interface-replay result is evidence against promoting this sampler.

Imagery: Esri and its providers; retain applicable source terms. Contains
Environment Agency information © Environment Agency and/or database right,
OGL-UK-3.0. Original route-search provenance includes © OpenStreetMap contributors,
ODbL-1.0. Frozen FLAIR encoder and derived heads retain upstream NVIDIA
non-commercial research/evaluation scope; cards and licence are retained.
