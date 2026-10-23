Voxel Mapper desktop jobs

Start without external data:
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
