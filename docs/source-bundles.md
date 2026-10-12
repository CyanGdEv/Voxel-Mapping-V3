# Retained planning sources and offline replay

`voxel-planning-bundle` (or `python -m voxel_mapper.planning_bundle`) preserves
original PDF and application-page bytes independently of council availability.
It packages exact input catalogue bytes, a provenance receipt and optional
native-page inventories. It accepts no drawing registrations or world geometry.

Keep originals and bundles outside Git. Store the bundle and its SHA256 receipt
in a durable location outside expiring Actions artifacts. A checksum without
the original bytes cannot recover a lost drawing.

## V1 bundle contract

The ZIP contains `bundle.json`, content-addressed JSON catalogues/provenance
under `metadata/`, originals at `files/<sha256>.pdf` and
`files/<sha256>.html`, and optional `inspection/page_inventory-<sha256>.jsonl`.
The manifest declares `voxel_mapper.planning_source_bundle/v1`, every member's
kind, SHA256 and size, and original retention states. Catalogue PDFs use the
existing `entries` format; application catalogues use `applications`,
`cached_page` and `cached_page_sha256`. Catalogue bytes are retained unchanged.
Provenance requires `evidence_kind` (`real`, `fixture`, `metadata_only` or
`mixed`) and an `origin` describing its source. These labels are assertions,
not independent authenticity or reuse verification.

An externally supplied archive SHA256 binds the entire bundle. Every present
original, catalogue, provenance receipt and inventory is also hash checked.
PDFs require a PDF header. HTML is retained as original bytes and parsed with
the existing bounded Alton attachment parser; a matching reference is required.
An imported application page is `retained`, not `discovered`, until that parser
succeeds. No JavaScript is executed.

Limits are 2 GB compressed and expanded bytes, 20,000 ZIP members, 10,000 PDF
catalogue records and 10,000 application records in total, 32 catalogues, 32
inventories, 8 MB per manifest/catalogue/provenance receipt, 64 MB per PDF or
inventory, 2 MB per HTML page, and 100,000 inventory rows. Replay defaults to
10,000 newly inspected pages per invocation. No archive paths are extracted.
Traversal, absolute/Windows paths, duplicate names (including case aliases),
links, special files, encryption and unsupported compression are rejected.
Only stored/deflated ZIP members are supported. Bundles reject unlisted members.

Absent originals appear individually in `missing_sources`; unpinned links
appear in `metadata_only_sources`. Strict mode rejects incomplete source sets.
`--allow-partial` permits these conditions and leaves their records pending.
It never permits corrupt bytes, conflicting pins or malformed metadata. A blob
declared retained but absent reports `declared_retained_member_absent`. Missing
and corrupt corpus PDFs are also reported separately, and their cached page
inventories are withheld. Completeness describes the supplied catalogues, never
every council application, present-day construction or complete park coverage.

## Feed Job 1's recovered source pack into this job

Job 1 should retain `files/<sha>.pdf` and `files/<sha>.html`, its PDF catalogue,
its application catalogue, and a recovery receipt identifying original locations,
observed acquisition/transport, dates where known, and original byte hashes.
Use the recovered catalogues where available; repository catalogues are a
historical fallback and cannot establish that the corresponding files exist.
Do not change pins to make altered bytes match, or label synthetic files real.

Make a provenance JSON alongside the recovered pack, replacing the descriptive
fields below with Job 1's actual recovery details:

```json
{
  "evidence_kind": "real",
  "origin": "Actual recovered archive/location and Job 1 recovery receipt",
  "recovery_receipt": "Original archive checksum, acquisition record and date where known",
  "qualification": "Original bytes only; geography, semantics and as-built state remain unverified"
}
```

Then run:

```bash
python -m voxel_mapper.planning_bundle create \
  --source /retained/recovered-source-pack \
  --catalogue /retained/recovered-source-pack/metadata/alton-planning-catalogue.json \
  --applications /retained/recovered-source-pack/metadata/alton-applications.json \
  --provenance /retained/recovered-source-pack/recovery-provenance.json \
  --bundle /retained/source-bundles/source-bundle.zip \
  --official-host publicaccess.staffsmoorlands.gov.uk
```

Use `--allow-partial` when the missing-source report is expected, including
while Job 1 has recovered only part of the pack. The command writes
`source-bundle.zip`, `source-bundle.zip.sha256` and
`source-bundle.zip.report.json`. Keep all three. The archive is deterministic
for identical catalogues, provenance and retained bytes.

If Job 1 supplies a legacy ZIP, import it with `voxel_mapper.planning_archive`
and its original archive pin first. Bundle the imported corpus using catalogues
retained under `corpus/bundles/<archive-sha>/metadata/`. The importer now
preserves pinned application HTML in addition to PDFs. Its default application
catalogue is `metadata/alton-applications.json`; use `--applications-member`
for another member. A legacy ZIP without it reports
`application_catalogue_available: false`. Absent originals never become downloads.

## Portable offline inspection

Copy the bundle and its independently retained receipt to another machine:

```bash
python -m voxel_mapper.planning_bundle replay \
  --bundle /retained/source-bundle.zip --sha256 ORIGINAL_ARCHIVE_SHA256 \
  --official-host publicaccess.staffsmoorlands.gov.uk \
  --corpus /offline/planning-corpus --output /offline/planning-inspection
```

Add `--allow-partial` for an intentionally partial pack, or `--max-pages 500`
to bound an invocation. Replay validates before changing corpus records,
restores originals atomically, parses retained pages without network requests,
and recomputes native text/vector counts in PDF page coordinates. Repeated replay
resumes unchanged originals and inventories. Conflicting original application
snapshots require a fresh corpus.

Outputs include `replay-report.json`, `page-inventory.jsonl`,
`replayed-catalogue.json`, `replayed-applications.json`, and any packaged
inventories under `bundled-inspections/`. Exported catalogue references are
relative to the replay corpus; re-parsing HTML preserves PDF pins. Newly
discovered unpinned attachment links remain pending in the availability report.
Repackage with `create --source /offline/planning-corpus`, the two exported
catalogues and `--inventory /offline/planning-inspection/page-inventory.jsonl`.

`replay --no-inspect` preserves and exports packaged inventories without opening
a PDF renderer. They remain `derived_evidence_only`; they are never loaded as
geometry decisions or proof that a missing original was retained. Reports list
unavailable originals for each inventory. `verify` checks without importing and
writes `verify-report.json`. Rejected verify/replay commands write
`rejection-report.json` and exit 2.

Park jobs also accept V1 bundles through `acquisition.retained_archives` with
`file`, `sha256` and optional `allow_partial`. Set `acquisition.offline: true`
to prevent download and Alton address discovery, including with
`provider: "alton"`. The source-bundle replay command additionally parses
retained HTML and exports portable inventories. Anchor audits still use
checksum-checked original PDFs and accept no world geometry.

## Supplied source artifacts in CI

Run **Alton Towers Wicker Man planning test** manually on the branch containing
this change with all three source inputs:

| Input | Value |
| --- | --- |
| `retained_source_run_id` | Same-repository Actions run containing the artifact |
| `retained_source_artifact` | Exact name, e.g. `alton-source-bundle-123456789` |
| `retained_source_sha256` | Original SHA256 of the inner `source-bundle.zip` |
| `allow_partial_sources` | `true` only for an intentionally partial pack |

The artifact must contain `source-bundle.zip` at its root; checksum/report
sidecars may accompany it. Inputs select the same repository using a read-only
Actions token. User input is passed through the environment, not inserted as
shell code. The pin is for the inner bundle, not GitHub's outer artifact ZIP.
Cross-run download requires the run ID and token
([download-artifact inputs](https://raw.githubusercontent.com/actions/download-artifact/v4/action.yml)).

Job 1 can hand the coordinator a local pack for `create`, or upload those three
files from an authorized recovery workflow using `actions/upload-artifact@v4`.
This bridge does not itself upload arbitrary local files to Actions. Diagnostic
archives without original bytes are metadata, not a recovered source artifact.

CI replays offline before using the verified corpus as
`wickerman --planning-cache`. The normal generator can still attempt live
acquisition for missing sources and other map providers; offline source replay
is independent of those requests. The genuine Wicker Man geometry command and
its failing exit code remain mandatory. Inventories, drawing annotations,
metadata-only packs and a baseline world cannot make that gate pass.

After generation or geometry failure, CI captures generator originals as
`alton-source-bundle-<run-id>`. A supplied bundle is also preserved as
`alton-supplied-source-bundle-<run-id>`, even when validation rejects it.
Replay/geometry diagnostics retain the existing 14-day policy; original bundles
request 90 days, subject to repository retention limits
([GitHub artifact retention](https://docs.github.com/en/actions/tutorials/store-and-share-data#configuring-a-custom-artifact-retention-period)).
Download and mirror originals before expiry; Actions provides transport and
temporary retention. An archive pin grants no authenticity, geography,
semantics, present-day verification or drawing-reuse rights.

## Evidence exercised by this implementation

Tests use explicitly labelled synthetic one-page PDFs and application HTML.
They cover moved bundles, network prohibition, original/catalogue retention,
deterministic creation, resume/repair, missing and metadata-only records,
outer/inner tampering, ZIP safety/budgets, portable inventory repack/replay,
corrupt-source exclusion and the unchanged geometry acceptance failure.
Real repository catalogues can be packaged as metadata-only evidence with every
unavailable original listed. Actual planning PDFs were unavailable for this job;
no real PDF inspection, new drawing frame or planning geometry acceptance is
claimed. Job 1's recovered bytes are required for real-source replay.
