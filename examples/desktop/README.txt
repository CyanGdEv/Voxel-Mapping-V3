Voxel Mapper desktop jobs

The Generate an area tab runs the included real Alton terrain/path preset
without JSON setup. Wicker building/plaza presets accept retained PDF folders
or bounded checksum-pinned council downloads. Open world and Compare geometry
use the selected completed job. The jobs below remain in Advanced jobs / learning.

Start without external data:
Open Review and accuracy and choose Try correction demo for the synthetic
source drawing and geometry editor. Review Wicker building prepares a real
provisional building review using matching PDFs from your folder/cache.
Correction drafts create no training labels. Reviewed outcomes apply to the
original candidate and require an external reference plus explicit import.
The correction demo now deliberately uses a 6 m frontage against an 8 m source
drawing. Add an X dimension correction of 8 m, save the draft, then press
Regenerate saved corrections. A new candidate and native world are generated,
with a frozen synthetic before/after reference. New candidates require their
own review; original decisions and models remain intact.
Choose reconstruction-benchmark-synthetic.json to exercise accuracy reporting;
its exact, wrong and missing geometry cases are all explicitly synthetic.

- Select "Inspect retained evidence" and inspect-evidence.json. This adds an
  explicitly synthetic observation to persistent memory, not a training label.
- Select "Building batch / local previews" and building-preview.json. This
  creates local GLB previews of an explicitly synthetic building fixture.

Real learning:
Use collect-feedback from the source review queue to obtain
building-feedback-v1 records with source/candidate hashes, accepted/rejected
outcomes and independent review references. Put that file here as
reviewed-feedback.json. Supply reviewed-split.json with training_buildings and
evaluation_buildings arrays, with no building or shared source in both splits.
Do not convert generated predictions or a successful export into positive labels.
Select "Import reviewed training feedback" and import-reviewed-feedback.json.
Continuous learning queues a new CPU neural training run when the reviewed
memory contains sufficient new independent data. The active model changes only
when evaluation passes; otherwise the last active checkpoint is retained.
Alternatively select "Train neural candidate ranker" and train-reviewed-ranker.json.
No trained real-park weights or fake reviewed-feedback examples are bundled.

Optional reasoning:
Install/run Ollama separately and install a small CPU model suitable for your
machine. Edit local-reasoning.json with its exact installed model name, then
choose "Reason about evidence". The application does not download a model or
train a language model. Reasoning proposals are stored for review and do not
execute arbitrary code or authorize geometry.

World generation:
Choose a retained world-pilot-v1 JSON job and "World pilot from retained inputs".
Its original terrain/maps, source hashes and relative paths must still exist.
For the existing full Alton draft, edit full-alton-draft.json with the two
retained acquisition/detail directories and choose "Full Alton draft from
retained inputs". Large jobs may exceed the observed memory budget and will be
cancelled instead of exhausting the machine.
The self-test builds a tiny synthetic terrain world without external sources:
VoxelMapperV3.exe --self-test

To compare public mapping and survey layers, choose "Compare mapping / survey layers" and load compare-mapping-layers.json. Extract the Mapping-Source-Layers package mapping-layer-inputs folder into the repository root and retain its cache folder. The shipped request is offline; see docs/mapping-source-layers.md for live requests and local vector imports. Results include index.html with layer toggles, opacity, source details and review-note export.

For alignment diagnostics and a prioritised boundary queue, choose "Alignment / boundary review queue" and submit boundary-alignment-review.json after extracting boundary-review-inputs into the repository root. See docs/boundary-alignment-review.md. This reviews precomputed source-pinned predictions; it does not edit labels or train.
