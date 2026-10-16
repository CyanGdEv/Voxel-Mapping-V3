# Replaying placement evidence before world generation

The normal reconstruction path now recalculates saved horizontal registration
reviews from their control/checkpoint pairs before applying a placement. This
closes a reproducible stale-review bug: changing a saved translation by four
metres left its accepted status and near-zero checkpoint summary intact. The
previous consumer could still place geometry inside the original review domain.

The fix does not establish real control identities or a building floor. Source
provenance, permitted source use, source-view/component identity, current or
as-built state and the vertical datum still require their existing checks.

## Registration contract

New reviews contain `version: independent-registration-v2` and `fit_parameters`
with the original `expected_scale` and `scale_tolerance`. The control and
checkpoint records are copied when the review is made, including nested source
metadata, so later caller mutations do not change saved evidence.

Before a review can be used, the consumer:

* requires the original three or more controls and two or more distinct
  checkpoints, their full numeric point pairs and matching identity lists;
* recomputes the orientation-preserving similarity fit with the recorded
  tolerances and expected scale;
* checks that the serialized transform itself satisfies the declared point-error
  tolerance and matches the recomputed pose;
* checks the stored scale, rotation and control/checkpoint residual summaries;
* applies the existing validated-domain restriction to placement.

The pose comparison uses an absolute numerical bound of `1e-7` metres at the
evidence points, rather than a relative tolerance on large BNG coordinates.
This is a floating-point consistency allowance, not a survey accuracy claim.
The serialized pose must also satisfy its declared accuracy tolerance when that
tolerance is smaller than the numerical comparison bound. Unknown, malformed,
inconsistent or incomplete reviews are rejected; their transforms are never
silently repaired or promoted by changing an accepted flag.

`Feature.validate`, local buildings and `apply_registration` use the same check.
The domain is built from the replayed evidence without redundantly fitting it
again inside one registration operation. An inconsistent source review withholds
the feature before any voxel cells are committed.

Legacy reviews without the complete replay contract require regeneration from
their original evidence. Drawing analysis is now `drawing-batch-v6` and frame
qualification `drawing-frame-qualification-v4`, which also changes the batch
bridge's cached input contract. Use a fresh work directory when an old job's
contract differs. Regenerating a review still requires valid source identities,
independent survey evidence and all separate component/state/height checks.

## Retained real-source checkpoint

The new `examples/wicker-placement-evidence-job.json` exercises the normal
planning bridge with the exact retained **2016 Existing Site Plan**, SHA256
`bfca0863216de7d3fe5667190286c7c639cd084730965c3f89984504bd3dd953`.
Its companion files bind the PDF, source policy and survey-reference registry.
They deliberately record unknown source-use/state/datum evidence and an empty
landmark registry. No artificial coordinates or accepted survey claims are
supplied.

Restore the original PDF to:

```
retained-source-input/wicker-placement/files/bfca0863216de7d3fe5667190286c7c639cd084730965c3f89984504bd3dd953.pdf
```

That source directory is ignored by Git. The local evidence bundle retains the
original bytes for replay. Run:

```sh
python -m voxel_mapper.park_pipeline \
  --job examples/wicker-placement-evidence-job.json --stage compile
```

With the supplied evidence, the bridge is withheld and reconstruction reports
`awaiting_normalized_geometry`. It emits no accepted features or world. This is
the expected real-source result, not a successful reconstruction example.

The retained audit has no independently accepted horizontal controls or
checkpoints. The existing site plan describes its drawing-date state; that alone
does not verify the current Wicker building. The shop's proposed 182.50 m label
does not establish an independently verified ODN floor, and the review world's
184 m clearance experiment remains provisional. A self-fit to roof/terrain or
selection of the preferred orientation cannot supply that missing evidence.

On 16 October, the checked council application URL and two Smiler PDF URLs still
returned HTTP 503. The receipt records the exact checked URLs and responses;
this is not a claim that every possible public source was exhausted.

Before this can become the first real accepted component, the input evidence
must establish:

* three identified controls and two separately sourced checkpoints, with source
  bytes, coordinate frame, physical identities and accuracy;
* verified source policy, drawing view and component identity/state, including
  the source's relevance to the intended park date;
* independently supported floor/height and datum where the component needs them.

The source-to-world tests still demonstrate the positive route using explicitly
synthetic surveyed PDFs. They also demonstrate that a changed cached pose emits
zero geometry through both the PDF bridge and local-building compiler. Those
tests do not turn the retained Alton sources into accepted measurements.

See `docs/evidence/placement-replay/` for the before/after reproduction, source
inventory, live recovery result and normal-pipeline outcome. Accepted real park
planning components and new training labels remain zero.
