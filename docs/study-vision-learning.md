# CPU component masks from retained planning studies

This research training path uses higher-resolution source crops to learn both
component types and two-dimensional masks. It reuses the retained study dataset
and adds a compact, trainable convolutional network using the existing NumPy
runtime. It needs no GPU, external model server or downloaded pretrained weights.

## Evidence and task

The expanded dataset contains **148 component examples from 23 original planning
PDFs**, with **12 connected source/building groups**. It preserves the original
127 catalogue targets and adds four reviewed CBeebies path polygons, eleven
garden path centrelines, three garden paving polygons and three source-labelled
Wicker plazas. Related garden sheets remain in one context. These are components
from the retained studies, not 148 buildings or 20 complete reconstructions. The dataset retains
unmarked original crops, reviewed source geometry, separate masks, assumptions,
source states and review-file checksums.

Source pixels are the only inference input. Component names and masks are
supervised targets; source IDs, building identities, geometry and target masks
are not image features. Crop regions are still supplied by reviewed references.
Finding those regions on a full planning sheet remains a separate task.

The network uses two trainable 3×3 convolutions, a spatial component-class head
and a sigmoid mask head. At the default 64×64 input size, its mask head predicts
a 32×32 grid and upsamples it by two for display. This is not 64-pixel independent
boundary precision. Training uses separate fractional mask coverage, preserving
thin traces when crops are reduced. Masks describe proposed drawing regions; they do
not supply real-world dimensions, height, correspondence between views, complete
building meshes or park placement. Thin trace targets and filled polygon targets
remain distinct kinds of supervision in the review materials.

## Evaluation

Shared PDFs and repeated building identities stay in the same group. Each
evaluation fold fits preprocessing and all learned parameters using its training
groups only. The trainer compares component recognition with the existing 16×16
classifier and a training-majority baseline. It compares masks with a mean-mask
template computed using only the training fold.

Mask overlap and Dice scores measure agreement with the supplied drawing mask.
They are not physical building accuracy. The report keeps individual predictions,
source-group lineage, unknown classes and baseline results so that concentrated
class coverage and easy crop-frame priors remain visible.

The final saved checkpoint fits all eligible examples after evaluation. Its
training loss is not an unseen-building result, and the final checkpoint has no
untouched test. Research checkpoints never replace the active building ranker.

## First fixed-snapshot result

The unchanged 127-example, ten-group comparison used 64-pixel inputs, four
channels and 30 epochs. Component accuracy was **9/127 (7.0866%)**, below the
same-fold 16-pixel classifier's **12/127 (9.4488%)**. The mean predicted-mask
intersection-over-union was **0.29503**, below the training-only mean-mask
template's **0.41648**. Dice scores were **0.41395** and **0.55966**, respectively.
Soft-coverage mask scores also favoured the template. These results do not show
an accuracy gain and do not justify production activation.

Joint training loss decreased from 3.10518 to 1.00365, with genuine convolution
weight updates. The managed CPU job used approximately 79.27 MB and retained
its checkpoint and history across restart. Fitting loss reduction and passing
software checks do not establish reconstruction quality. The expanded dataset
is a separate experiment; its results must be reported against baselines fitted
on its own source groups.

The [retained source and first-experiment receipt](evidence/study-vision-learning/validation.json)
records dataset/model hashes, real scores, source acquisition identities and
independent review checks.

Coverage diagnostics on the expanded dataset still find seven single-group
classes and 87 examples whose class is absent from their training fold when
that complete group is held out. Windows, structural members and several other
classes still need additional independently reviewed buildings.

## Windows use

Extract the portable dataset alongside its training request. In **Advanced jobs /
learning**, choose **Train component outlines (CPU)**, select the request JSON and
start the job. Results retain the open JSON weights, source-separated evaluation
and predicted-mask review files. Training history and the saved checkpoint survive
restart.

Open `index.html` in the training Results folder to compare held-out crops,
reviewed targets, CNN masks and training-only templates. The page explicitly
warns when learned scores fall below a baseline. Its source and target pictures
are separate; predicted masks never overwrite original drawing pixels.

The request uses these settings:

```json
{
  "dataset_directory": "dataset",
  "dataset_sha256": "RAW_SHA256_OF_DATASET_JSON",
  "epochs": 30,
  "channels": 4,
  "input_size": 64
}
```

Relative dataset paths resolve from the request file. Input grids are 32×32 or
64×64, channel counts are 4 or 8, and epochs are bounded. Jobs also obey the
existing managed-process memory budget, cancellation and one-heavy-job limit.
The default profile retains its configurable 16,384 MB budget; this does not
reserve that amount of RAM for the application.

The existing **Train study component recognizer** operation and its checkpoints
remain compatible. The two model formats are separate research experiments.

Generate the coverage and independent-intake report from a portable dataset:

```bash
python -m voxel_mapper.study_training_coverage --dataset /path/to/dataset \
  --output /path/to/fresh-coverage.json --min-groups 3
```

The requested group count is an acquisition goal, not an accuracy or readiness
guarantee. The report separates named building studies from footprints and
site-detail contexts and identifies missing height and view-correspondence tasks.

## Remaining work toward autonomous reconstruction

Repeat each target component type across independent buildings and planning
applications. Add paired plans, elevations and sections for the 20-building pilot,
with checked dimensions, openings, roof profiles and view relationships. Broader
path and plaza coverage needs reviewed geometry and independent site contexts;
component-type labels alone cannot reconstruct them.

After crop-level mask evaluation, add full-sheet region discovery and measure
missed objects and false detections. Connect supported component predictions to
the existing source-linked geometry builders, then evaluate footprint boundaries,
heights, openings and cross-view consistency on untouched buildings. Independently
checked corrections can become versioned labels for later training runs.
