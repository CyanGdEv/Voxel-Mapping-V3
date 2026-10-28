# Source-only paving label review

The subsequent [Towers Street correction benchmark](towers-paving-correction-benchmark.md)
applies eight source-only assistant corrections, retrains both candidates, and
compares them on a newly reserved area. It does not constitute an independent
human review and does not replace the baseline model.

The spatial benchmark reduced false positives but lost paving coverage. Before
more training, check the existing development labels against their original
imagery. This stage provides a self-contained offline editor for four crops,
85 draft polygons across three parks. It supplies no new verified labels and
does not train or replace a model.

Open `Paving-Source-Label-Editor.html` from the download. Choose an area and an
outline, toggle outlines to inspect the original pixels, and zoom as needed.
Drag outer vertices to correct boundaries. The JSON editor supports class,
reason, vertices and polygon holes. New outlines default to unknown. Use
**Keep outline**, **Apply edits**, or **Mark unknown**, then **Next unreviewed**.
Every outline requires an explicit decision before export. Unknown regions
override other labels; opposing known-class interiors remain ignored by the
mask builder. The page displays polygon previews; the importer generates the
authoritative masks with the original edge-ignore policy and conflict rules.

Review roofs, grass islands, planter holes, vehicle surfaces and raised objects
as explicit non-paving where visible. Pedestrian routes and plazas are paving.
Keep canopy, roof overhangs, ambiguous shadows and hidden ground unknown rather
than guessing. Native source pixels stay unchanged. Display zoom adds no detail.
No model output is shown, to reduce prediction-driven label bias.

Enter a reviewer name, attest to source review, and download the review JSON.
Save before closing; there is no automatic persistence. Resume the JSON in the
same source-pinned editor. Import on a machine with the project installed:

```sh
python -m voxel_mapper.paving_label_review apply \
  --dataset development-dataset --review paving-review.json \
  --output reviewed-development
```

The importer requires the original dataset ID, annotation SHA, original source,
metadata and crop-image hashes and exact crop offsets. It rejects incomplete
decisions, changed traces marked “keep”, invalid geometry, altered boundary
policy, and reserved-test datasets. Original trace IDs remain present; uncertain
traces become unknown. New IDs require an explicit correction/unknown decision.
It writes a fresh mask dataset, the submitted review receipt, and a report of
changed pixels, class flips and changes to/from unknown. Original masks and
checkpoints remain unchanged. No training starts automatically.

A reviewer attestation is evidence of a submitted review, not independent
verification of identity or accuracy. Outputs retain `human_labels_verified:
false`, `geometry_verified: false` and `production_eligible: false`. The tool
cannot manufacture independent ground truth. A real review has not yet been
submitted for this release. The consumed Paultons benchmark is excluded.

To create another source-only editor:

```sh
python -m voxel_mapper.paving_label_review create \
  --dataset development-dataset --output review.html
```

## Finer imagery investigation, 28 October 2026

Fresh Environment Agency coverage queries using the exact four crop extents
returned no features in the vertical photography index queried. These bounded
negative results do not establish that all archives lack imagery. The earlier
Paultons 10 cm record dates to 2012 and is not current ground truth.

[EA vertical aerial photography](https://environment.data.gov.uk/dataset/dae203a8-ba24-4c54-bab0-866b9faadb58)
describes 10–50 cm project coverage with per-survey dates. Check the actual tile
and date before treating archive detail as an improvement for a current park.
[Bluesky](https://bluesky-world.com/aerial-photography/) advertises national
12.5 cm orthophotography and finer city coverage with licensing options. Local
park availability, capture date, licence and training/export rights have not
been established. No purchase or restricted-data download was made.

The download includes fresh coverage query receipts and the prior capture
quality audit. No genuinely finer current imagery was acquired in this stage.
Independent label review and suitable current source pixels are still needed
before claiming greater reconstruction accuracy. Windows packaging includes
the editor template, but no Windows executable was built in this release.
