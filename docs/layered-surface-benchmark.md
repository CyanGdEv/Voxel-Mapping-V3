# Layered surfaces and aerial-model comparison

This research stage adds denser draft labels, an independent tree-canopy head,
class-balanced training and a pinned aerial-pretrained comparison. It improves
some park-held-out paving and roof results; it does not establish high-precision
automatic boundaries or replace the production baseline.

## Labels and review status

Three clean images from two parks retain the user's red path guidance, purple
Chessington building/roof guidance, tree locations and original water roles.
Eight explicit partition windows and twelve visible crown polygons extend the
prior source-assisted masks. There are 204,698 known ground pixels and
226,648 known canopy/non-canopy pixels. Most of each image stays unknown.

Labels were inspected by the assistant against clean RGB and user guides. They
have **not received independent human review**. The review page can export
region-specific decisions and notes; those notes do not automatically approve
labels or trigger fitting. The downloadable literal recipe can be corrected and
rebuilt after review.

Ground classes remain paving, building/structure, grass and water. The legacy
identifier `grass_island` covers both lawn and island grass; window polygons
retain lawn/island subtypes. No island-versus-lawn classifier or individual-tree
instance model is claimed. A separate binary head identifies tree canopy.
Crown polygons are traced on visible imagery, never from green glyph radii.
Ground below traced crowns stays unknown, and pre-existing inferred canopy
paths stay out of both observed-ground and non-canopy targets. Buildings, water
and bounded islands do not acquire paving through canopy filling.

The recipe's inherited `ground` lists are read-only provenance: changing them
requires rebuilding the source dataset. New edits belong in `dense_windows` and
`canopy`. Window bases are explicit semantic choices, not inferred from blank
imagery. Unknown margins, uncertain banks/objects and artificial window borders
are ignored. Original marker images and phone interface never enter features.

## Training diagnostic and fixed comparison

A fixed 96 × 96 clean Chessington tile containing roofs and paving was fitted
for 600 steps. Its fitted present-class macro IoU was
72.63% with plain loss and
70.79% with balanced loss.
This is a memorisation diagnostic, not validation or evidence that the balanced
loss always wins. The diagnostic crop targets were unchanged by the later
canopy-negative policy correction; its original dataset snapshot is retained.

The comparison uses the same small spatial architecture with four ground and
two canopy logits. Plain and balanced RGB models have identical parameter
counts, initialisation, patch sampling and 400-step schedules. Balanced loss
uses fitting-only inverse-square-root class weights, weighted labelled-interface
pixels and soft Dice. Unknown pixels have zero loss/gradient. Ground and canopy
losses are independent. Classes missing from a fitting image are not invented.
The fixed schedule is longer than the prior 120-step run; convergence is not
assumed. No held-out score selects a checkpoint or hyperparameter.

A third model consumes RGB plus thirteen frozen aerial-class probability layers.
Its input stem has additional parameters, so the RGB-versus-aerial comparison
is not capacity matched. The pretrained encoder is never updated. Its own
native class mapping is scored separately, with unmapped classes abstaining.
Paving maps strictly from impervious surface, grass from herbaceous vegetation,
water from water, roofs from building, and canopy from coniferous plus deciduous
probability. Native pervious surface is left unmapped; this conservative mapping
misses many aggregate/gravel paths. Abstentions count as missed known targets.

Every record from the held-out park is excluded from head fitting. Both Alton
images are held out together. The known-label geographic guard is
93.56 m, above the 24 m requirement. These are two-park development
checks, not a fresh blind test or evidence of general accuracy across parks.

| Record held out | Model | Paving IoU | Roof IoU | Grass IoU | Water IoU | Canopy IoU | Paving on roof pixels |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| user-towers-mutiny | rgb_unbalanced | 58.77% | 3.74% | 0.00% | 0.00% | 29.68% | 16008 |
| user-gardens-lake | rgb_unbalanced | 30.53% | 1.59% | 0.00% | 0.00% | 5.80% | 3392 |
| user-towers-mutiny | rgb_balanced | 58.75% | 3.88% | 0.00% | 0.00% | 43.94% | 15960 |
| user-gardens-lake | rgb_balanced | 53.97% | 0.90% | 0.00% | 0.00% | 10.27% | 3303 |
| user-towers-mutiny | aerial_balanced | 66.87% | 75.11% | 0.00% | 0.00% | 26.40% | 1378 |
| user-gardens-lake | aerial_balanced | 72.46% | 7.38% | 0.00% | 0.00% | 29.44% | 992 |
| user-chessington-courtyard | rgb_unbalanced | 63.36% | 0.00% | — | — | 0.00% | 23892 |
| user-chessington-courtyard | rgb_balanced | 63.73% | 0.00% | — | — | 7.80% | 21643 |
| user-chessington-courtyard | aerial_balanced | 83.60% | 69.82% | — | — | 34.90% | 5228 |
| user-towers-mutiny | aerial native mapping | 3.14% | 78.07% | 50.53% | 0.00% | 53.23% | 312 |
| user-gardens-lake | aerial native mapping | 2.34% | 66.65% | 57.95% | 99.69% | 35.96% | 0 |
| user-chessington-courtyard | aerial native mapping | 0.00% | 53.88% | — | — | 34.04% | 0 |

Aerial features improve Towers roofs from 3.74% to 75.11% IoU and garden paving
from 30.53% to 72.46%. Chessington paving improves from 63.36% to 83.60%, and roofs
from zero to 69.82%. These comparisons use the new common draft labels and the
same 400-step schedule. They are not comparisons with the previous stage's
changed dataset or shorter schedule.

Coverage remains a major limitation: the Chessington fitting example has no
grass or water labels, and all adapted models trained only there miss those
Alton classes. The native aerial model recognises the garden lake interior
well (99.69% IoU) but misses the small Towers pond; adaptation loses this water
strength when fitting data lacks water. Tree results are mixed: native aerial
canopy IoU is 53.23% on Towers versus 26.40% after adaptation. The models are
research alternatives, not an automatically selected winner.

## Boundary precision, connectivity and uncertainty

The benchmark now scores precision, recall and IoU per class, with support and
abstentions, plus separate canopy scores. Boundary F1 uses two native clean
pixels of tolerance and only interfaces surrounded by explicit known labels.
Unknown edges and artificial crop borders are excluded. This is **partial
assistant-draft boundary evaluation**, not full-scene boundary accuracy.
A class without supported labelled edges has a null score rather than zero or
a pass. The garden lake has no scored shoreline interface where its bank is
uncertain; its high water interior IoU does not establish shoreline precision.

Boundary results remain weak. For the aerial-feature model, partial paving
boundary F1 is 12.44% on Towers, 7.68% in the gardens and 6.98% at Chessington;
roof boundary F1 is 20.99% on Towers and 7.90% at Chessington. Better object-area
IoU has not solved exact edge placement. Three deterministic connection probes
come from the largest explicitly labelled path components in each image.
Narrow-strip recall measures labelled interiors near mask edges, not surveyed
full path widths. All raw scores and supports are retained.

Final fits see all three images and are labelled fitted previews, never
validation. The fifteen-region review queue uses high normalised entropy from
the fitted aerial-feature head. It is uncalibrated uncertainty, not an error
probability or automatic correction. Prioritise complete boundary review,
additional parks with labelled lawns/water and preserving pretrained class
knowledge before expanding use.

## Aerial source and execution

The source is [alanoix/segformer_b0_flair_one](https://huggingface.co/alanoix/segformer_b0_flair_one),
revision `ce3f996fd63489f9f9f40d1aea740e3fb9c3f90c`, trained on FLAIR aerial RGB.
Its card reports Apache-2.0 but its NVIDIA MiT upstream points to a
non-commercial research/evaluation licence. The stricter upstream use scope
is preserved; this is not a general commercial deployment licence. Cards,
licence and source hashes accompany the converted safe-tensor checkpoint.
The upstream repository provides no preprocessor file; standard ImageNet
normalisation is a recorded assumption. Inputs use native 512-pixel tiles with
overlap, without increasing their true optical resolution. All three original
Esri source receipts and image registrations remain pinned.

One-time conversion used CPU PyTorch 2.6 `weights_only=True`, strict architecture
matching and finite-value checks. Runtime loads only pinned safe tensors; no
remote Python code or pickle is loaded at inference. Optional dependencies are
in the `aerialsegmentation` extra and are not bundled into the default desktop
executable. No pretrained weights are committed to Git.

Nine comparison/final heads and two diagnostic heads were fitted, CPU only,
two threads. The environment interrupted training; explicit resume verified the
unchanged design and source/encoder lineage, reusing five complete checkpoints.
The resumed invocation took 284.34 seconds and peaked at
748.8 MB process RSS. Those measurements exclude
interrupted earlier work. Feature extraction took 19.33 seconds; the separate
two-model diagnostic took 115.52 seconds. No complete combined training-time
measurement is claimed.

Eighty-five relevant checks passed with optional dependencies installed. The
final recipe reproduces the exact dataset. Nine final image/checkpoint pairs
reproduce both heads after reload (18 exact mask checks).
Source hashes and inference dimensions are retained. Windows CI can skip
optional neural checks when the research dependencies are absent; no Windows
training run or executable is claimed. The existing RGB paving checkpoint stays
unchanged at SHA256 `096941b8b5a7ddd0c48f25b47359771d26ae4c4c82d7f1deb0a52cad866df8fc`. No world blocks or accepted geometry are
generated and no model is promoted.

## Reproduction

From the full repository at this revision, install the optional dependencies:

```bash
python -m pip install -e '.[aerialsegmentation]'
```

Then, from the extracted package:

```bash
python -m voxel_mapper.layered_surface_benchmark --source-dataset source-dataset --examples inputs/examples.json --recipe recipe.json --output rebuilt-dataset
python source/scripts/train_layered_surfaces.py --dataset rebuilt-dataset --encoder aerial-encoder --output fresh-training
```

Use `--resume` only with an unchanged matching experiment directory. Offline
runtime uses the supplied pinned safe-tensor encoder. Large derived feature
caches and uncertainty rasters outside the final aerial review layer are omitted
and can be recomputed from the supplied checkpoints. Source images are Esri World Imagery
and its providers; user annotation references retain their original provenance.
