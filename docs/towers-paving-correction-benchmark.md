# Towers Street correction and reserved-area benchmark

The source-only correction pass expands the Towers Street development mask and
re-trains the RGB and RGB/context binary networks. Development scores improve,
but the newly reserved LEGOLAND Windsor comparison regresses slightly. **Keep
the existing RGB baseline.** These are provisional assistant-authored labels,
not independent human ground truth or a production accuracy claim.

## Source corrections

Eight literal traces add the western pedestrian paving strip and conservative
visible brown/red roof interiors. Furniture, umbrella clusters, a tree crown
and dense shadow remain unknown. This changes 7,309 native pixels:

| Change | Pixels |
| --- | ---: |
| Unknown to paving | 2,940 |
| Unknown to non-paving | 3,818 |
| Previously labelled to unknown | 551 |
| Direct paving/non-paving class flips | 0 |

There are zero conflicting known-class interiors. Other development crops,
original images, georeferencing and crop offsets remain unchanged. Existing
planter/lawn exclusions are retained. The correction recipe reproduces the
complete new dataset exactly. The author is the assistant; no independent
review receipt has been received or fabricated.

## Training and development comparison

Both candidates use the prior fixed settings: 24 hidden units, 60 epochs,
512-sample batches, learning rate .01, regularization .0001, seed 137. Each
experiment samples 32,000 balanced known pixels across four crops and three
parks. A whole park is excluded in every development fold. Park names, raw
coordinates, map geometry and target masks are not input feature channels.
Georeferencing sets the metric scale of context windows. Original
baseline checkpoints stay unchanged. This trains small MLPs; no pretrained
backbone, large reasoning model or autonomous architecture is trained here.

All methods below are evaluated against the **same corrected known pixels**:

| Method | Pooled paving IoU | Macro park IoU |
| --- | ---: | ---: |
| Baseline RGB | 55.34% | 48.24% |
| Corrected RGB | 55.52% | 48.92% |
| Baseline context | 51.73% | 46.80% |
| Corrected context | 53.04% | 51.11% |

The report also evaluates the shared-known subset, preventing newly labelled
pixels from being mistaken for a model gain. On that subset pooled IoU changes
55.31% to 55.49% for RGB and 51.97% to 53.32% for context. Alton-excluded fold
weights remain identical because only Alton fitting labels changed; they cannot
improve that held-out fold through exposure to its new labels.

The measured training used two CPU threads, no GPU, about 501 MB peak process
RSS and 29.27 seconds in this environment. These measurements cover the training
process, not the RAM used by the entire desktop app or a Minecraft world.

## Newly reserved test

The LEGOLAND Windsor area was reserved before fetching its imagery. Crop bounds,
central-half extraction, model settings, threshold, methods and adoption policy
were fixed first. All four models were frozen before source-only test labels
were authored. The label/connection seal predates prediction evaluation. The
consumed Paultons area was not used for fitting or evaluation in this stage.

| Method | Paving IoU | Precision | Recall | False positives | Connections |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline RGB | 80.64% | 98.05% | 81.95% | 179 | 2/3 |
| Corrected RGB | 80.36% | 97.59% | 81.99% | 223 | 2/3 |
| Baseline context | 67.14% | 95.36% | 69.40% | 371 | 2/3 |
| Corrected context | 66.32% | 94.09% | 69.20% | 478 | 2/3 |
| Always paving | 89.39% | 89.39% | 100% | 1,306 | 3/3 |

The test has 10,998 known paving pixels, 1,306 known non-paving pixels and
53,232 unknown pixels. Only 18.8% of the 256 × 256 crop is scored. Do not
interpret the entire blue overlay as validated geometry. The high positive
class proportion lets always-paving beat every model on IoU, demonstrating why
precision and route checks must accompany that score.

Boundary F1 is **unavailable**, not zero or a successful check: no target
boundaries remain inside fully known neighbourhoods after the explicit unknown
regions and one-pixel edge-ignore margin. The fixed gate treats unavailable
boundary evidence as insufficient for adoption. Do not remove those unknown
bands after seeing predictions to manufacture a better test result. Numeric
IoU and precision also regress, independently failing the gate.

Connection recall is evaluated only inside known target paving. It cannot
reward false bridges through unknown/non-paving areas. An always-paving output
recalls all three pairs despite its false positives, so it is a recall measure,
not proof of correct path geometry. The test is now consumed. Identical frozen
inputs can be replayed; altered models, targets or probes require a new area.

## Reproduce

With the project and its existing dependencies installed, from the download:

```sh
python -m voxel_mapper.paving_correction_benchmark correct \
  --dataset original-dataset --recipe towers-paving-correction.json \
  --output reproduced-development
python -m voxel_mapper.paving_binary_learning train \
  --dataset reproduced-development --output fresh-training
python -m voxel_mapper.paving_correction_benchmark evaluate \
  --dataset test-dataset --freeze frozen-models.json \
  --seal annotation-seal.json --protocol reserved-test-protocol.json \
  --development development-comparison.json --output identical-replay
```

The last command evaluates the shipped frozen checkpoints, not `fresh-training`.
It is a deterministic replay of an already consumed test. The freeze uses safe
package-relative model paths. Every model, annotation, source and comparison is
hashed. This stage adds neither world blocks nor a Windows executable build.

## Imagery and physical accuracy

The native export is 512 × 512 and the fixed central crop is 256 × 256. Provider
point metadata reports 0.46 m GE01 imagery dated 17 August 2025; export sampling
is about 0.348 m/pixel. Neither point metadata nor extra export samples establish
a genuinely finer source, a single date across the full image, or surveyed
registration. No imagery resolution upgrade is claimed. Source receipts retain
Esri World Imagery/provider attribution. The [official area description](https://www.legoland.co.uk/explore/theme-park/lands/the-beginning/)
provides location context; it is not a source of pixel labels.

The remaining need is independently checked coverage and boundary evidence,
including difficult roof/paving transitions. This experiment measures a small
label expansion honestly; it does not resolve that ground-truth limitation.
