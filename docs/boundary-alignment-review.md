# Alignment diagnostics and boundary review queue

This stage examines the four retained mapping areas before changing surface
labels. A new **Alignment / boundary review queue** desktop job and CLI produce
relative image checks, map/LiDAR diagnostics, a prioritised review queue, and
source-bound note export. The source RGB, observed ground/canopy masks, inferred
path footprints, models and world geometry remain unchanged.

## What was actually measured

The reference aerial and two retained Wayback images share each area's exact
export grid. Mutual SIFT ratio matches are selected near generalised OS buildings,
excluding green-coloured reference pixels. Fitting and checking use different
24 m cells with a four-metre guard from cell edges. Feature centres are separated;
large descriptors may still share context, and no physical corner identity is
established. These are image correspondences, not independent surveyed controls.

A robust translation is fitted only from fit points. Check points do not select
the translation or fit inliers. Results include all check-match residuals, not
just check inliers. Twelve fitting matches, eight checking matches and spatial
support in several cells are required. Weak or inconsistent fits emit no applied
transform; **no transform is applied in any case**.

Local ground sampling is computed geodesically rather than treating Web Mercator
metres as ground metres. It converts diagnostic displacements/distances; it does
not improve the native source resolution or accuracy. SIFT comparison uses an
approximately 0.5 m sampling scale where the export grid is finer. Native image
sizes and original RGB files remain unchanged.

| Area | Layer | Diagnostic result | Fit / check pairs | East / north shift, ground m | Check median / p95, m |
| --- | --- | --- | ---: | ---: | ---: |
| user-towers-mutiny | wayback-63116 | relative_translation_supported | 250 / 128 | -0.039 / 0.143 | 0.052 / 0.215 |
| user-towers-mutiny | wayback-4756 | insufficient_spatial_support | 3 / 2 | — | — |
| user-gardens-lake | wayback-63116 | relative_translation_supported | 202 / 103 | -0.054 / -0.140 | 0.132 / 0.505 |
| user-gardens-lake | wayback-4756 | insufficient_spatial_support | 1 / 0 | — | — |
| user-chessington-courtyard | wayback-63116 | relative_translation_supported | 186 / 63 | -0.046 / -0.032 | 0.033 / 0.154 |
| user-chessington-courtyard | wayback-4756 | insufficient_spatial_support | 1 / 0 | — | — |
| user-tight-gardens | wayback-63116 | relative_translation_supported | 41 / 12 | -0.060 / -0.004 | 0.055 / 0.308 |
| user-tight-gardens | wayback-4756 | insufficient_spatial_support | 0 / 0 | — | — |

The newer Alton layer and reference both report 27 May 2023 at the sampled point.
The newer Chessington layer also shares the reference capture date at that point.
Their close agreement is consistent with differently rendered versions of the
same acquisition. It is **not independent positional verification** or evidence
of centimetre/sub-metre absolute accuracy. Dates from one metadata query do not
establish a single capture date for an entire mosaic.

The older layer reports April 2018 at the Alton sample and March 2014 at the
Chessington sample. It has insufficient reliable spatial support here and stays
unshifted. Different vegetation, image detail, illumination, scene changes and
potential positional differences can all affect matching. Failed matching alone
does not identify a physical map offset. No surveyed horizontal controls were
available in these inputs.

OS building boundaries are also compared descriptively with nearest valid
LiDAR-height edges. An elevated edge may be a tree, roof or another object, not
the same physical wall represented by OS. Those distances are not identity-matched
errors and cannot be used as an estimated map shift. The numeric image grid is
finer than the native one-metre LiDAR. Invalid height neighborhoods stay missing.

## Review windows and selection

The current run flags these categories:

- grass predicted paving: 14 queued windows.
- path prediction miss: 65 queued windows.
- path building overlap: 33 queued windows.
- water map disagreement: 1 queued windows.
- inferred tree path: 12 queued windows.
- unknown path margin: 51 queued windows.
- path canopy check: 16 queued windows.

These cover narrow labelled paths missed by a park-held-out prediction; grass
near paths predicted as paving; paving/building/elevated-return conflicts; path
and overhead canopy checks; mapped water disagreements on known labels; low,
RGB-similar unknown margins within 1.5 m of known paths; and separately inferred
paths under canopy. Unknown pixels are not treated as known grass/water and
invalid LiDAR is not interpreted as low flat paving. Inferred ground is not
promoted to observed supervision.

Unknown-margin colour uses CIELAB Delta E76 ≤12 relative to nearby labelled paving,
with low valid LiDAR, vegetation/building/water exclusions. This is a search
heuristic, not a material classifier or a proposed paving polygon. High returns
and canopy have separate review reasons; they do not automatically erase a path.

Components smaller than 0.5 m² are not queued. There is a 48-window cap per area,
with category diversity preserved before filling by priority and area. Priority
is a heuristic ordering, not a calibrated error probability. Smaller components
and capped cases remain in the unchanged source evidence. The run is not an
exhaustive map of all possible errors.

| Area | Eligible components ≥0.5 m² | Queued | Omitted by cap |
| --- | ---: | ---: | ---: |
| user-towers-mutiny | 131 | 48 | 83 |
| user-gardens-lake | 214 | 48 | 166 |
| user-chessington-courtyard | 127 | 48 | 79 |
| user-tight-gardens | 93 | 48 | 45 |

The 192 windows prioritise Towers Street / Mutiny and the tight garden example.
Every window retains reference/mask/prediction/model hashes, native pixel bounds,
flagged pixel area and a WGS84 review-window polygon. The exported GeoJSON contains
**review rectangles, not physical path/building boundaries**. Four full-resolution
crops show original aerial, current draft labels, park-held-out prediction, and
OS/LiDAR context. Display JPEGs have diagnostic rectangles; original inputs and
masks remain lossless and unmodified.

## Initial assistant triage and the training gap

Six selected windows have assistant source-assisted notes in
`evidence/boundary-review-assistant-triage.json`. They are not independent human
review or correction instructions. Visible lawns and narrow walks support keeping
some current drafts despite contradictory predictions. A small water feature's
absence from generalised mapping does not justify removing the user-guided label.
Thin building-edge conflicts remain unresolved; the user-confirmed circular
structure role is preserved. Similar path-adjacent colours include terraces and
planted features, so unknown margins are not filled automatically.

The Alton-held-out model was fitted on Chessington labels with paving and
structures but **zero grass and water target counts**. This is recorded per area
in `model_training_ground_counts` and `unseen_training_classes`. It helps explain
these held-out lawn errors; it does not mean every model in the project lacks
those classes. More independently sourced grass/water examples in other parks
would address that coverage gap. Changing correct Alton lawn labels to fit this
prediction would conceal the problem.

No source-bound boundary correction was justified by these automated diagnostics.
No masks were changed and no training was run. A future research refit needs an
explicit, reviewed draft correction recipe and a frozen comparison protocol.
Production accuracy still requires independent controls/labels and evaluation.
The four current images are development data and cannot be relabelled as a new
blind test after their results have been inspected.

## Viewer and notes

Open `index.html` or `Boundary-Alignment-Review.html`. Filter by area and issue;
use Previous/Next to compare windows. Decisions and notes save locally in the
browser and export as `boundary-alignment-review-notes-v1`. Notes retain the
exact queue ID, parent mask and source image hashes. `validate_notes(notes,queue)`
rejects stale/wrong source pins, duplicate/unknown windows and invalid decisions.
Validation does not approve geometry, establish reviewer independence, apply
transforms or add labels. The browser test note is explicitly not a human review.

Crop colours: paving blue, structures red, grass green and water dark blue.
Context shows OS building edges magenta, mapped water cyan and valid relative
LiDAR height ≥3 m amber. Elevated returns may include vegetation. Reference
hashes and the issue boxes are available in Source pins and review window.

## Reproduction and desktop job

The bundle contains `boundary-review-inputs/`, retained original RGB/masks,
aligned LiDAR fields/receipts, inferred footprints, precomputed park-held-out
predictions and their model metadata, compact comparison metadata, retained
Wayback PNGs and vector observations. Model weights are not needed or included
for this review job. Original survey rasters and source acquisition tools remain
in the preceding Mapping-Source-Layers / LiDAR packages.

With a full repository checkout at this revision, install the optional image
matching dependencies and run a fresh output directory:

```sh
python -m pip install -e '.[mappingreview]'
python -m voxel_mapper.boundary_alignment_review --config boundary-review-inputs/review-request.json --output new-review
```

Without OpenCV, image alignment is explicitly unassessed; queue generation remains
available with the normal geospatial/SciPy dependencies. The actual run used
OpenCV 4.10.0 with two CPU threads. No GPU or network access is required. There
are at most eight one-megapixel areas and 48 queued windows per area.

For the desktop example, place `boundary-review-inputs/` at repository root, choose
**Alignment / boundary review queue**, and submit
`examples/desktop/boundary-alignment-review.json`. No Windows EXE was rebuilt.
The portable source config is an analysis input manifest; use the earlier layer
job/package for live acquisition or a complete source-layer viewer.

Portable inputs preserve every area/window payload exactly. Relocating input
paths changes the raw source-config file hash and therefore the newly generated
queue ID. Review notes remain tied to the exact queue they were exported from;
keep the shipped `queue.json` with its HTML/notes. A repeated original request
reproduces the complete current queue byte-for-byte in the same environment.
OpenCV/platform differences can affect matching, so cross-platform bit equality
is not claimed. Source patches alone are not a standalone installation.

## Validation and limits

41 relevant tests passed: 14 boundary/alignment tests, 15 mapping-layer tests and
12 desktop runtime tests. They cover spatial fit/check separation, rejection of
weak fits, geodesic sampling, missing height, tree/roof separation, unknown-label
handling, capped diverse queues, park-exclusion lineage, source pins, deterministic
outputs, stale-note rejection and a real desktop subprocess without training.

The browser decoded 768 crops across all 192 windows, tested 40 filter combinations
including five empty filters, persisted and exported source-pinned notes, and
checked a narrow-screen layout. It reported no runtime errors or external requests.
The exported test note passed backend source-pin validation. Software checks and
assistant triage are not independent physical validation.

Imagery: Esri and its providers. OS layers: applicable Crown copyright/database
rights and OS OpenData attribution. LiDAR: Environment Agency, OGL-UK-3.0. User
annotations remain source-assisted draft labels. The prediction models retain
the frozen aerial encoder's upstream research/evaluation scope; relevant model
cards and licence are retained in the download. No new model weights, accepted
geometry, world edits or production accuracy claim are created in this stage.
