# Visual source and geometry review

The desktop review workflow displays a local building candidate beside its
original source PDF. Choose a review queue, select a candidate, bind a retained
original PDF, then choose its page and a local geometry projection. Original
PDF bytes must match the candidate's recorded source hash. The preview uses
local metres; it does not infer a geographic alignment from the drawing image.

Draw outline or opening corrections in the geometry pane, or record a dimension
or placement correction. Each annotation records the original source hash,
page, component and local coordinate frame. **Save draft** retains annotations
without creating training examples. Corrections are proposed replacements;
they do not silently rewrite the original candidate or accept a corrected model.

For an independently checked decision, supply a review basis and external review
reference, then review the **original** candidate as accepted or rejected. A
candidate with correction annotations must be rejected or left as a draft.
Review references are audit pointers, not authentication of the reviewer.
Importing reviewed feedback is a separate explicit step. Existing source,
identity, dimensions, topology and model-promotion requirements still apply.

## Included review inputs

The retained Wicker shop preset prepares its existing three-layer local study
through the same source-feed adapter used by the building pipeline. It checks
the bundled model against its retained asset pin. Matching original PDFs can
come from the selected retained-source folder or the desktop source cache; the
preset does not download anything. PDF filenames do not need to match their
hashes. Matching originals are staged in the new review result directory.

If originals are absent, the queue remains usable for inspecting the provisional
geometry, and missing source hashes are reported. A source-linked correction
requires binding its matching PDF. Orientation, floor level, physical identity,
materials and as-built status remain unresolved. Preparing the queue creates
zero reviewed outcomes, zero training labels and zero accepted park blocks.

The offline synthetic demonstration supplies a small, visibly labelled synthetic
elevation PDF and a local wall with a window hole. It is for checking the review
controls. Its dimensions and geometry are fixture inputs, not real planning
evidence; the demonstration includes no pre-labelled review outcomes.

Every preparation and review uses a fresh output directory. Existing source
files, previous reviews, memory and model checkpoints are preserved.
Use **Resume saved review...** to reopen a saved draft after restarting the app.
The original queue, candidate batch and bound PDFs must still match their saved
hashes. Reopening restores annotations and decisions without importing feedback.
Dimension corrections name the local X, Y or Z axis; placement rotations are
about the local Z axis before the recorded XYZ translation.

## Measuring improvement

The reconstruction benchmark compares supplied predictions against separately
reviewed references. It measures footprint agreement, boundary distance, height,
position and optional opening matches. Missing predictions and missing evidence
remain visible. Training and evaluation source/building lineage must not overlap
an untouched benchmark. See [benchmark contract](reconstruction-benchmark.md).

This release provides the review and measurement workflow; it does not publish
a trained real-park model or claim a completed real-building accuracy benchmark.
