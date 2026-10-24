# Learning from retained reconstruction studies

The Wicker, north-range and Prospect studies now supply reusable drawing-level
supervision. The dataset also includes reviewed rock, planter, wall and building
footprints. Original source crops, exact trace coordinates, target masks and
review references remain bound to their source PDF and review-file checksums.

The first real export contains **127 examples from 17 verified PDFs**, with ten
source-connected evaluation groups and no missing source pairs:

| Drawing-level target | Examples |
| --- | ---: |
| Structural member profile | 63 |
| Wall outline or trace | 15 |
| Rock footprint | 14 |
| Window outline | 12 |
| Roof outline or trace | 7 |
| Door trace or outline | 5 |
| Opening trace | 4 |
| Building footprint | 3 |
| Retaining-wall footprint | 2 |
| Archway outline | 1 |
| Planter footprint | 1 |

These counts describe components. There are six named study identities (four
Wicker buildings, the north range and Prospect Tower), two other reviewed
building footprints, and six site-detail grouping contexts. Four Wicker
buildings share PDFs and therefore remain in one group. All Prospect storeys
remain one building. A source group is not a new independent building.

## Supervision scope

Wicker targets retain original pixel outlines, opening segments and vertical
traces. The provisional furniture-based plan normalization is excluded from
measured targets. North-range targets use the retained source-label-corrected
review seed and original trace geometry. Prospect targets invert the documented
nominal affine transform of 63 extracted floor profiles back to page coordinates;
these remain raster-derived, simplified source shapes, not exact original
vector vertices or surveyed member dimensions. Detail targets use explicitly
reviewed unrotated MuPDF page polygons and labels.

Conditional 3D models are retained as context assets. Estimated roof joins,
canopy attachment, rear/end closures, display thicknesses, station/preshow
apertures, palette choices and height estimates do not become verified training
targets. A drawing-level component can be learned while geographic placement
remains unresolved. No whole-building accepted/rejected feedback is inferred.

The exporter verifies original PDF bytes, pinned full-page raster samples where
available, review-file bytes and JSON pointers. It preserves source geometry and
creates an unmarked grayscale crop beside a separate mask. Target masks never
enter classifier inputs. Crop bounds are supplied by the reference geometry;
this experiment does not evaluate automatic object discovery. Page rotation,
holes, coordinate transforms, missing/stale evidence and resource budgets are
explicit. Outputs publish atomically. Original PDFs are never rewritten.

## Actual CPU image learning

`study-component-image-classifier-v1` is a separate small image recognizer:
16×16 grayscale input, a 16-unit tanh hidden layer by default and a softmax output.
It uses class-balanced Adam updates. Inputs are source crop pixels only; target
geometry, masks, names, source IDs and labels are not input features. Open JSON
checkpoints retain actual weights, normalization and source/building lineage.
This is separate from the existing six-feature building-candidate ranker.

Source-connected groups combine every shared PDF and every repeated building
identity. The trainer recomputes groups rather than trusting supplied split
labels. Each fold fits normalization and weights on its training groups only.
For this dataset it evaluates ten leave-one-group-out folds, then fits a
research checkpoint on all eligible examples. That final checkpoint has no
untouched test. Conditional and illustrative targets cannot silently enter
training. Checksums bind the complete dataset snapshot through publication.

The first real run at 150 epochs and 16 hidden units achieved **12/127 correct
(9.4488%)**, macro F1 **0.06826**. Its per-fold training-majority baseline scored
0/127; this unusual baseline reflects concentrated class coverage and does not
establish useful quality. **81 held-out examples have classes absent from their
fold's training set**, including all 63 Prospect profiles. Of the remaining 46
examples, 12 were correct (26.087%). These results expose insufficient independent
class coverage and weak transfer. They do not establish autonomous building
reconstruction accuracy. No hyperparameter tuning or resplitting was performed
to improve the reported holdout.

The model is **always research-only** in this version. It classifies already
proposed crops; it does not generate geometry, select accepted park objects or
replace the active building ranker. The next data work is to add independently
reviewed examples of the same component types across different buildings and
PDF sources, then assess transfer on newly reserved sources. Existing 3D
reconstruction methods remain reusable alongside this dataset.

## Reproduce or use on Windows

Prepare the source-paired dataset from the repository and checksum-named PDFs:

```bash
python -m voxel_mapper.study_dataset --repo /path/to/repository \
  --sources /path/to/checksum-named-pdfs --output /path/to/fresh-dataset
```

The portable dataset ZIP already contains source crops, masks, reviewed geometry,
review/context assets, manifests, an offline gallery and a ready-to-run training
request. It excludes the full original PDFs. Extract the ZIP, open `index.html`
to inspect examples, or use the updated Windows app:

1. Open **Advanced jobs / learning**.
2. Select **Train study component recognizer** and choose the included request JSON.
3. Start the job, then inspect its `model.json` and `report.json` in Results.

The request pins `dataset.json`; every crop and asset is checked again by the
trainer. Relative dataset paths resolve from the request file. Managed CPU jobs
retain the existing 16,384 MB configurable cap, cancellation and persistent
history. The real baseline used approximately 56.53 MB managed memory. There is
no background promotion of this research model and no generated geometry.

Frozen synthetic tests exercise real training, checkpoint reload/prediction and
restart. Synthetic pattern accuracy is an engineering test and is reported
separately from the real results above.
