# Generate a retained Alton area from the Windows app

The desktop now opens on **Generate an area**. Choose a preset and press
**Generate area**. There is no JSON setup for this workflow. Generation runs in
an isolated worker under the existing CPU/memory controls. The job is selected
automatically; once it finishes, **Open world** opens its `park.mcworld` and
**Compare geometry** opens the source/native-material overlay.

## Included presets

- **Alton terrain and paths — included offline:** the real retained EA DTM,
  OSM surfaces, acquisition receipts and explicit OSTN15 crop are packaged with
  the EXE. This approximately 128 by 62 metre scene needs no network. It retains
  7,936 terrain, 178 road and 90 path voxel records. Planning structures remain
  awaiting evidence; these are not counts of independently verified objects.
- **Wicker building and plazas — study A/B:** the existing 192 by 192 metre
  provisional study, with its building, mapped paths, source-linked planning
  paving, three plaza footprints and estimated half-step joins. The two
  orientation hypotheses remain separate. Neither becomes accepted geometry.
  Placement, floor height, materials, drawing reuse and as-built status remain
  unresolved. Ride layouts are not reconstructed by these presets.

These are reproducible retained-area workflows. They do not select arbitrary
new park boundaries or independently interpret every planning application.
The study building uses its existing reviewed model, not a newly trained vision
model. Successful exports create no training labels and do not promote models.

## Original planning PDFs

The Wicker studies need four original PDFs. They are not included in the data
bundle. Either select a folder containing retained originals, with any file
names, or leave **Download missing original council PDFs** enabled. The app
matches retained files by content hash and caches matching originals locally.

Only the recorded public council attachments are requested. HTTPS is tried
first; a recorded HTTP transport fallback may retrieve the same attachment.
Every original must match the existing SHA256 before use. Redirects, HTML/error
pages, changed versions and different attachments cannot substitute evidence.
Requests have byte/time budgets and remain cancellable through the job worker.
Source searching is bounded to 4,096 entries and 256 MB of PDFs; choose a small
source folder rather than a whole disk.

If a provider is unavailable, the job stops before world generation. Its
`area-inputs/area-source-report.json` records missing originals and download
attempts. Supply the originals or retry later in a fresh job. No guessed world
or successful fallback scene is published. The shared `source-cache` retains
checksum-matching originals so later jobs can run offline.

The sources are the three shop drawings from SMD/2016/0315 and the proposed
woodland-path site plan from SMD/2017/0111. Source hashes and URLs remain those
of the existing pilot jobs. On 23 October 2026, the site plan's HTTPS endpoint
returned 503 while its HTTP endpoint returned the exact original, SHA256
`1c5dc5b43ddf14de2d0b96d7970cee8197d115c46d6919ad74aa484c77a61a1d`.
Later cold retrievals also timed out, so fresh acquisition of all four originals
is not reliably available. Retained originals and the cache remain necessary
when the portal is down. Recovery does not establish physical acceptance.

## Windows runtime and validation

The Windows build includes English Tesseract OCR and Poppler PDF helpers by
default. A manual workflow can explicitly omit them. Frozen dependency checks
actually recognize a small English test image, extract a PDF's text and render
its page; executable lookup alone is insufficient. OCR availability does not
make ambiguous drawing geometry or physical identity resolved.

The self-test now also exercises the bundled **real Alton area** through the
same worker/preset path, checks native saved-world readback and retains zero
accepted planning components. Source tests cover portable bundles, changed
assets, missing evidence, recorded transport fallback, incorrect checksums,
redirect rejection, cancellation and persistent worker outcomes. The real UI
check presses Generate area with the advanced JSON field empty.

The default profile still targets a 6 GB RAM CPU-only PC: two worker slots,
one heavy generation at once and a monitored 2 GB managed-process budget.
Tests on development/CI hardware measure that budget; a physical 6 GB Windows
PC and Minecraft gameplay remain separate validation. Large-area streaming,
generation resume and a trained general drawing model remain further work.
