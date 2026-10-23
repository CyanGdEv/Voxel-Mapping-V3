# Windows desktop and persistent CPU learning

Voxel Mapper now has a Windows desktop application, isolated background workers,
a persistent SQLite memory and a genuine CPU neural candidate learner. The
Windows workflow builds a self-contained executable distribution and exercises
its native libraries, worker processes, saved-world readback and actual widgets.
The application does not require a separate Python installation.

This is the desktop and learning foundation for the reconstruction prototype.
The neural model learns which supported building interpretation to prioritize.
General drawing understanding, verified complete park reconstruction and an AI
that invents new program capabilities remain unfinished. No trained real-park
weights or language-model weights are bundled.

## Run the Windows build

Download `VoxelMapperV3-Windows-x64` from the Windows desktop executable workflow,
extract `VoxelMapperV3-Windows-x64.zip`, and keep the executable and `_internal`
folder together. Double-click `VoxelMapperV3.exe`. The distribution is unsigned;
its exact commit, file hashes and frozen test receipts accompany the build.

Start with **Generate an area**, choose the included real Alton preset and press
**Generate area**. No JSON editing or network is needed for that retained pilot.
The Wicker building/plaza studies can recover their exact original PDFs or use a
retained-source folder. See the [area workflow](desktop-area-pilots.md).

The **Advanced jobs / learning** tab retains the editable jobs in `examples`:

- **Inspect retained evidence** + `inspect-evidence.json` stores an explicitly
  synthetic source observation and demonstrates persistent memory.
- **Building batch / local previews** + `building-preview.json` generates local
  previews of a synthetic building fixture. It is not a real accepted building.
- **World pilot from retained inputs** accepts existing `world-pilot-v1` jobs,
  including their pinned terrain/map files and source-relative paths.
- **Full Alton draft from retained inputs** accepts `full-alton-draft.json` with
  the retained full-park acquisition and Wicker details directories. This runs
  the existing full-park draft generator under the same memory/cancellation
  controls; larger inputs may need more memory or separate chunked workflows.
- **Import reviewed training feedback** imports real review corrections and can
  automatically queue CPU training once the independent dataset is sufficient.
- **Train neural candidate ranker** runs an explicit reviewed training job.
- **Reason about evidence** connects to an already installed local Ollama model.

Outputs are created in fresh per-job folders under the selected data directory.
Existing results are never overwritten. The default Windows data folder is
`%LOCALAPPDATA%\VoxelMapperV3`. Copy/archive that complete folder to retain jobs,
observations, reviewed examples, dataset splits and open JSON model checkpoints
across application updates. It is local storage, not a cloud account or the
language model's hidden context.

## 6 GB RAM, no GPU profile

Defaults are two CPU worker slots, one heavy generation/reasoning job at a time,
and a 2,048 MB observed memory budget across managed processes. Worker settings
allow one to four slots and a 512–3,072 MB managed-process budget. NumPy/BLAS
threads are capped at one inside each managed worker to avoid oversubscription.
A running generation can coexist with lightweight neural training when two
slots are available. The GUI polls status asynchronously and remains responsive.

Memory monitoring cancels an over-budget process tree; polling is not an
instantaneous operating-system reservation. It includes the desktop's managed
process tree, but cannot budget an independently running Ollama server. Optional
reasoning is off until a user supplies a model job. Its CPU profile requests
2,048 context tokens, at most 512 output tokens, two inference threads and model
unloading after the request. Large models or large areas can exceed a 6 GB
machine's practical capacity. Training a large language model from scratch is
not supported by this profile.

The Linux source smoke generated a tiny synthetic terrain world, packaged it,
and passed the existing complete saved-world readback. Observed managed peak
memory was about 221 MB for that small test. This is not a measurement of a
full park or a guarantee for arbitrary Windows jobs. The Windows artifact must
pass its own frozen tests before upload.

## Durable workers and source memory

Worker subprocesses use an allowlist of operations, receive pinned JSON inputs,
and write separate logs, progress and result files. Frozen workers dispatch
through the same executable; they do not launch a system Python interpreter.
Cancellation terminates the managed process tree. Workers monitor their parent
and exit if the desktop disappears. Partial jobs never promote checkpoints.

A process-level data-directory lock prevents two desktop instances from changing
one memory store. SQLite connections are short-lived and never shared across
worker processes. Completed jobs and observations survive restart; queued,
running or cancelling work interrupted by a crash is retained explicitly rather
than reported as complete. Failed automatic training retries after completion, and interrupted training can
retry on restart, at most three attempts per unchanged dataset. Explicit cancellation is
retained; re-enable automatic learning or submit a manual job to resume it.

Evidence observations retain source hashes, status and numeric counts. Errors
and job outcomes are remembered separately. A remembered observation is not an
accepted physical fact. Reading a file checks its hash before and after parsing,
and changed training feedback or split files reject checkpoint persistence.
Storage is bounded: 10,000 reviewed records, 10,000 knowledge observations,
10,000 job records and the latest 20,000 log events. Archive a full data folder
when these quotas are reached rather than silently deleting learning evidence.

## Actual neural learning

`building-neural-candidate-ranker-v1` is a NumPy network with six inputs,
12 tanh hidden units and one sigmoid output by default. Training uses genuine
backpropagation and Adam updates. Open JSON checkpoints retain architecture,
weights, source/building lineage, evaluation results and an integrity hash.
The six inputs are the existing boundary support, cross-view agreement,
dimension agreement, opening support, topology quality and source coverage.
It is a candidate ranker, not a vision model or a language model.

Import `building-feedback-v1` records with their candidate/source hashes,
accepted/rejected outcome, declared `independent_review` or `source_verified`
basis and a nonempty external review reference. The existing
`building_pipeline collect-feedback` adapter can bind review decisions to an
exact source review queue. Those references are audit pointers, not authenticated
signatures. Generated predictions, remembered errors and successful mesh/world
exports do not automatically become correctness labels.

Automatic learning is on by default, and has a GUI toggle. A new reviewed dataset
triggers training when it has at least 100 training and 20 evaluation examples,
five independent buildings per split and both outcomes in each split. Explicit
split files are supported. Otherwise stable connected-source groups determine
the split; a shared source cannot cross training and evaluation. Warm starts
retain prior source/building roles.

Training is bounded to 10,000 records and the model's CPU work limits. Evaluation
must improve held-out Brier error, retain at least 95% accepted-candidate precision
at the confidence threshold and provide enough qualifying predictions. A worse
or undersized checkpoint is retained for inspection while the prior active model
remains selected. New feedback imported during an active training run is picked up after that
run finishes. The same evaluated dataset is not trained endlessly in the
background. Periodically supplying genuinely untouched evaluation examples is
still necessary; repeated use of one holdout does not prove generalization.

Eligible neural checkpoints now feed the existing building batch ranker. Source,
identity, dimension, topology, geometry and native-export gates remain in force.
A high neural score cannot turn an unresolved building into accepted park blocks.
The existing logistic ranker and CLI iteration defaults remain compatible.

The nonlinear learning tests use synthetic XOR data to demonstrate behavior
that a linear ranker cannot learn. Runtime tests exercise actual automatic
training, promotion, failed-promotion retention and restart. These are engineering
checks; no real trained Alton model is claimed or silently activated.

## Optional open-model reasoning

A user-supplied installed Ollama model can reason over a bounded prompt and
retrieved local observations. No server, model or weight download is implicit.
Connection/model failures, timeouts and cancellation are reported. Reasoning
receipts retain model identity, options, input hashes and structured proposals.

The supported proposals are evidence inspection, world generation and ranker
training. They are advisory and remain unexecuted; arbitrary shell commands,
source-code rewrites, physical acceptance flags and invented training labels are
rejected. This provides a local reasoning connection without claiming that the
application can expand its own supported geometry algorithms. Actual inference
quality/performance has not been benchmarked because no local language model
was available during this implementation.

## Build and verify

From source:

```sh
python -m pip install '.[desktop]'
python -m voxel_mapper.desktop_app
python -m voxel_mapper.desktop_app --check-dependencies
python -m voxel_mapper.desktop_app --self-test
```

On Windows:

```powershell
python -m PyInstaller --noconfirm --clean packaging/voxel_mapper.spec
.\dist\VoxelMapperV3\VoxelMapperV3.exe --check-dependencies
.\dist\VoxelMapperV3\VoxelMapperV3.exe --self-test
```

The Windows workflow checks out the exact PR head, runs desktop/neural tests,
builds the actual executable, tests the frozen native dependencies, exercises
persistent workers/neural learning plus native world readback, constructs the
actual UI, and uploads the ZIP with hashes and receipts. English OCR and PDF helpers are
included by default and exercised through the frozen executable. A manual
workflow can explicitly omit them.
