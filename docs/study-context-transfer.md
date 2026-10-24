# Wider context and pretrained CPU visual features

Two separate research models improve on the earlier local drawing-crop CNN.
Both use the unchanged 148-example dataset, 23 verified source PDFs and twelve
connected source/building groups. Source pixels are inference inputs; reviewed
classes and masks supervise training. Building names, source IDs, geometry roles
and target masks never enter the visual encoder as features.

## Measured results

All rows use the same source-group folds. The majority-class and mask-template
baselines are fitted separately using each training fold only.

| Method | Component class accuracy | Mean binary mask IoU | Mean mask Dice |
| --- | ---: | ---: | ---: |
| Previous 16-pixel classifier | 10/148, 6.76% | Not a mask model | Not a mask model |
| Previous local CNN | 10/148, 6.76% | 0.26530 | 0.37541 |
| Training-only mean-mask template | Not a classifier | 0.30791 | 0.43948 |
| Whole-crop context network | 8/148, 5.41% | **0.43814** | **0.54325** |
| Frozen pretrained features with fitted heads | **15/148, 10.14%** | 0.37145 | 0.49759 |

The context network improves mask overlap while its component classification
remains weaker. The pretrained feature model improves class accuracy and macro
F1 versus the same-fold 16-pixel classifier (0.04538 versus 0.03524). Its macro
F1 remains slightly below the old local CNN's 0.04598, so classification does not
improve on every metric. Group-balanced class accuracy is 30.27% for transfer,
10.90% for the local CNN and 18.85% for the 16-pixel classifier. On the 61 examples
whose class is available during fitting, transfer gets 15 correct (24.59%) versus
10 (16.39%) for either old classifier. These are
different models with different strengths; no oracle chooses a model per example.
Mask IoU measures drawing-mask agreement, not physical building accuracy.

**The record-average gain is uneven.** Giving each of the twelve source groups
equal weight produces mean binary IoU 0.30790 for context and 0.30595 for transfer,
versus 0.14273 for the old CNN and **0.34020 for the template**. Context beats the
old CNN in eleven groups and transfer in all twelve; they beat the template in
only two and five groups, respectively. Excluding the 63 Prospect member examples,
context scores 0.27604 and transfer 0.30068 versus template 0.32089. The better
record average therefore does not establish a general win over simple templates.
Soft-coverage IoU tells a different part of the result: with equal group weights,
context scores 0.28664 and transfer 0.28410, above template 0.25524. The reports
show both metrics; the binary regression warning remains visible.

Path targets remain weak: mean binary IoU is 0.06687 for context and 0.08121 for
transfer versus template 0.06833. Plaza scores are 0.46538 and 0.07283 versus
template 0.45794, from just three examples in one source group. These task-level
limitations remain visible in the review and cannot support autonomous park paths.

The evaluation remains small and uneven: 87 examples have a component class
absent from their training fold. The separate all-data checkpoints have no
untouched final-model test. These are development cross-validation results,
not evidence of autonomous reconstruction on a new park or twenty buildings.
No checkpoint is automatically promoted and no accepted world geometry is added.

The [validation receipt](evidence/study-context-transfer/validation.json) retains
model/data pins, full class and mask summaries, group-balanced sensitivity checks
and the independent audit fingerprint. Future training reports and offline pages
show equal-group scores and warn when they trail the template, even when the
record-average score is higher.

## Whole-crop mask context

The earlier local mask head often followed drawing ink instead of recovering
filled component regions. The new network reduces the supplied 32/64-pixel crop
to a 16-pixel analysis grid, learns convolutional features and a dense global
decoder, and combines it with a local residual. Every decoded mask cell can use
information from the whole crop.

The spatial output bias starts from the current training fold's mean mask.
It is a declared train-only prior, not an inference input or a held-out mask.
Convolutions, context features and mask coefficients learn by backpropagation
and Adam. The fixed first experiment uses 40 epochs and four channels.
The 16×16 mask is upsampled for display; this does not supply finer independent
boundary precision. Tests include hollow outlines with filled targets, holes,
moving geometry and independent numerical gradients.

The actual 148-record managed run took 91.77 seconds and peaked at about 88.32 MB.
Saved weights and job history survived restart. This timing describes the tested
cloud CPU, not a speed guarantee for another PC.

## Frozen pretrained features

The separate model uses MobileNetV2 visual features from the official ONNX Model
Zoo. A reproducible extraction exposes its 1,280-dimensional pooled descriptor
and removes the ImageNet classifier. The derived graph is 8,844,908 bytes,
SHA-256 `674dc0911a76190cb956be54ab6190b260e9cb5b7ef758a4742cfeeaacdcf6eb`.
The source model, pinned repository revision, exact preprocessing, complete
Apache-2.0 license, attribution and modification notice accompany the weights.

The encoder runs with ONNX Runtime 1.20.1 using only CPUExecutionProvider.
It reads the entire supplied crop as RGB, resized to 224×224 with ImageNet
normalization. Its pretrained parameters remain frozen. Closed-form ridge
regression fits new component-class and 16×16 mask heads, using training-fold
feature normalization only. The fixed first experiment uses ridge alpha 100.
This trains project heads; it does not fine-tune the pretrained backbone.

Frozen source-only descriptors can be computed once for all examples because
the encoder is never fitted on this dataset. Each fold still fits its own
normalization, head coefficients, class balance and mask targets. No held-out
labels or masks contribute to those fits.

The managed real run took 25.49 seconds and peaked at about 168.38 MB. Its
encoder bytes stayed unchanged, and its saved checkpoint and history survived
restart. The generic pretrained image model is not an architectural reasoning
model and does not supply reliable dimensions or view correspondence.

## Use in the Windows app

Extract the research dataset/model bundle and keep its directory structure.
Choose **Advanced jobs / learning**, then:

1. **Train context-aware outlines (CPU)** for whole-crop mask learning.
2. **Train pretrained vision heads (CPU)** for frozen features and fitted heads.

Choose the corresponding included request JSON. Open the training Results
`index.html` to inspect source-held-out predictions and baselines. Source crops,
reviewed targets and predictions remain separate. Each final `model.json` fits
all eligible examples; the gallery displays predictions from separate fold fits.

The Windows executable includes the CPU inference runtime. The pretrained
weights are supplied in the separate offline research bundle and are never
downloaded or installed automatically. The bundled tiny ONNX runtime test is
explicitly synthetic and is not a pretrained model or a real accuracy benchmark.
The existing component and local-CNN trainers remain available.

The jobs retain the configurable 16,384 MB managed-process budget, cancellation,
persistent history and one-heavy-job limit. The measured runs fit comfortably
within that budget, but larger source collections and worlds have separate costs.

To recreate the descriptor from the pinned original model in a development
environment with ONNX 1.17 installed, use `scripts/prepare_study_encoder.py`.
The script verifies the source and derived graph hashes and writes attribution
alongside the weights. ONNX conversion tooling is not needed for Windows use.

## Remaining reconstruction work

These models recognize and propose masks inside an already supplied crop.
Automatic full-sheet discovery, verified scale and dimensions, plan/elevation/
section matching, 3D assembly and geographic placement remain separate tasks.
More independent buildings are needed for windows, openings, roofs, structural
members and other sparsely represented classes. Fine boundary accuracy and
small openings also need higher-resolution source targets and evaluation.
