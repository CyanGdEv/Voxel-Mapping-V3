# Multi-source evidence intake and independent-site evaluation

The new intake packages existing reviewed component datasets with site identity,
reference assets and feedback. It does not convert world exports, passing checks,
LiDAR, photographs or accepted world reviews into source-geometry labels.

The first real pilot retains the existing 148 reviewed drawing examples from 23
PDFs, with the original crops, masks, target coordinates and review documents.
They all belong to Alton Towers. The landscape PDF, dated LiDAR crop, a rejected
546-member support world and the unreviewed denser prototype are reference assets.
The rejection concerns support density/crossing treatment; it does not relabel
all other source components as failures. The newer export is not an accepted
training target. This pilot has no independent evaluation park and trains no new
weights. Earlier crop/model metrics remain separate historical experiments.

## Intake request

`python -m voxel_mapper.study_intake --request request.json --output FRESH-DIRECTORY`

The request has `version: multi-source-study-intake-v1`, a `datasets` list,
`evaluation_sites`, optional `context_assets` and optional `feedback`.
Each dataset declares `id`, `site_id`, `directory` and `manifest_sha256`.
Directories point to existing `retained-study-dataset-v1` packages, verified by
the existing strict reader before copying. Relative inputs resolve against the
request file. Optional `record_ids` selects cases. Optional `record_decisions`
maps selected original IDs to `accepted`, `rejected` or `unreviewed`; rejected
and unreviewed rows stay out of training. The default retains upstream reviewed
eligible labels. Synthetic datasets require their own experiment and cannot be
mixed into real-source intake.

Each context asset declares `id`, `site_ids`, `kind`, `path`, `sha256`, `source`
and `license`; optional `epoch` and `source_state` preserve dated/proposed status.
Supported kinds are planning PDF, LiDAR, photograph, orthophoto, CAD, Minecraft
reference and correction review. These files remain `reference_context_only`.
Their metadata describes provenance and declared reuse status, not independently
verified copyright or physical identity. In particular, publicly viewable plans
are not automatically declared an openly licensed training collection.

Feedback declares `id`, `result_asset_id`, `decision`, `reason` and `review_basis`.
An accepted context result still generates zero training labels. To introduce a
new positive label, first create an appropriately reviewed source-paired dataset.
Images/point clouds do not become interchangeable with plan-crop labels; adding a
new prediction task needs a matching label schema and task-specific evaluation.

The portable output contains an offline index, copied unchanged source packages,
a combined readable dataset, explicit exclusions and site reservation. Fresh
outputs only; failed validation leaves no partial published directory. Files,
record counts, decoded images and CPU work use the existing bounded readers.
Original packages are never rewritten.

## Hold out complete parks

Set `evaluation_sites` to the site IDs that must remain untouched by optimization.
The intake rejects a split sharing building identities, original PDF hashes,
identical input crop bytes or reference asset bytes between training and
reserved sites. Asset identity is checked by content hash, not filename. Shared
inputs must be resolved before reporting independent-site performance.

The existing all-data/CV trainers refuse datasets containing reserved evaluation
rows. The site-aware CPU command is:

```sh
python -m voxel_mapper.study_site_evaluation --dataset PATH/INTAKE \
  --output FRESH-EXPERIMENT --epochs 150 --hidden-units 16
```

It recomputes the reservation, fits normalization and the small neural classifier
on training sites only, scores the untouched evaluation sites and writes a
checkpoint that is **not** refit on evaluation rows. Reports include classes
absent from training and a training-majority baseline. Results remain research
crop classification, not complete building or world generation. Repeatedly
consulting a holdout can still overfit later design decisions; reserve another
new site before claiming a final generalization result.

A one-site intake remains usable as a reference/review library, but this trainer
refuses to claim an independent evaluation without a second site. Next data work
is to acquire reviewed examples of the same component classes from separate
sites, with appropriate source rights and review evidence.

First independent evidence and held-site check: [Glen Echo source pilot](independent-site-source-pilot.md).
