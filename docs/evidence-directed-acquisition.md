# Evidence-directed planning acquisition

Area jobs can now use the missing-evidence queue to acquire relevant **known
official attachments**, recheck their original text, refresh native extraction,
and rerun architectural interpretation before registration and recipe generation.
An empty source corpus bootstraps from catalogue drawing titles. Users do not
need to upload the first PDF or provide a per-object acquisition recipe.

This closes the acquisition/rematching portion of the evidence loop. It does
not discover new application URLs, interpret every ordinary drawing, resolve a
physical requirement by keyword, or authorize estimated geometry automatically.

## Enable an area job

```json
{
  "offline": false,
  "architectural_interpretation": {"enabled": true},
  "evidence_acquisition": {
    "enabled": true,
    "max_documents": 8,
    "max_file_bytes": 16000000,
    "max_run_bytes": 32000000
  }
}
```

The existing official-host list, catalogue and area/application associations
remain required. This setting is opt-in; other jobs retain their acquisition
behavior. With it enabled, initial acquisition only reconciles retained sources;
network requests happen through the requirement-directed pass. Unrelated
catalogue attachments do not fill unused request slots.

Requirements select title candidates for view scope, physical exterior,
plan/elevation correspondence, relative dimensions, horizontal registration and
vertical datum. Common title plurals and `GF Plan` are recognized as search hints.
Candidate records retain original titles, requirement kinds and exact task IDs.
No retained pages means catalogue bootstrap: it records zero invented page tasks
and starts with known drawing titles. Application membership and title wording
remain unverified physical context.

The selector first favors candidates covering requirement kinds not yet covered
in this pass, with stable URL order breaking ties. It does not declare the first
or highest-scoring source correct. Only the selected known URL is eligible for
each download; redirects, changed expected hashes and HTML/error responses retain
the existing acquisition failures. An explicitly recorded same-resource HTTP
transport is allowed only with an exact original PDF hash. No transport downgrade
or alternative URL is invented.

## Bounded attempts and recovery

The document and run-byte limits apply across restarts of this acquisition
output, not anew on every invocation. Limits are 1–32 resource attempts,
1–64 MB per PDF and 1–128 MB for the run. Each resource has a durable intent
bound to its URL, expected hash, transport, originating queue and task IDs.
Successful and failed receipts are checksum checked before reuse. Same-resource
failures are not retried just because another document or requirement appears.

A process interruption leaves the request outcome uncertain. On restart, pinned
retained bytes and committed corpus state are reconciled. The resource is not
blindly requested again, and its reserved byte allowance is charged
conservatively. Unstarted resources can continue within the remaining budgets.
An interrupted attempt can therefore consume capacity without a successful
download. Source outages remain visible blockers rather than an endless loop.
To deliberately retry, create a new output/run under an explicit new budget;
the existing corpus's maximum-attempt checks still apply. The acquisition output
must not be used by concurrent writers.

Requests use the existing streaming byte counter. `run_network_bytes` records
bytes charged by that counter, rather than HTTP headers or total wire traffic.
As with the underlying downloader, a read chunk can arrive before a budget
failure is detected. Per-file format/hash failures never become retained evidence.

Offline mode writes a candidate plan, makes no request and spends no attempt.
Changed acquisition policy requires fresh output. Source/queue, intent, receipt
and published-report changes reject replay. Incomplete intent/receipt publication
can require a fresh output; it is not reported as a successful completed attempt.

## Refresh after source acquisition

The area runner re-extracts the current corpus and rechecks survey-source leads
before downstream alignment, registration, component and recipe stages run.
Architectural reviews and their queues have content-addressed directories bound
to the source inventory, drawing feed, extraction contract and interpretation
options. Earlier evidence remains available when new documents arrive.
Text-only additions change the source identity even if their geometry feed is
empty. This prevents an old review being reused for a larger corpus.

Area reports and full sweeps expose `evidence_acquisition`, including before/after
text matching, byte counts, attempts, errors and remaining candidates. The
refreshed `retained_evidence_matching` and missing-evidence queue describe all
currently retained sources. Requirements stay unresolved until actual view,
identity, dimension and registration evidence passes the existing checks.

The area contract is now v4 and the controller contract v2. Start fresh work
directories for older controller jobs; retain previous world packages separately
as pinned baselines. Existing accepted geometry is not changed by this feature.

## Real Wicker cold-start test

`examples/wicker-evidence-acquisition-job.json` starts without retained PDFs.
Its small historical catalogue names three exact Wicker shop originals from
SMD/2016/0315. No new application or URL discovery is claimed. In the live test
the runner downloaded all three through their previously recorded official
transports and verified the original hashes: **749,166 bytes**, three requests,
three native pages. It automatically prepared **six missing-evidence tasks** and
**25 retained text leads**. Replaying with HTTP explicitly blocked made zero
requests and reused all three resource receipts.

This is a source-acquisition test. Proposed source state is preserved. It creates
**zero accepted planning components, zero world blocks and zero training labels**;
view identity, geometry interpretation and independently supported placement
remain unfinished. The source-specific building and paving previews are not
treated as new automatic reconstruction evidence.

From a fresh checkout with `.[planning]` installed, use a fresh output root:

```sh
python -m scripts.audit_evidence_acquisition_replay \
  --job examples/wicker-evidence-acquisition-job.json \
  --output output/wicker-evidence-acquisition-validation.json
```

Or run the area CLI normally with `--stage extract`. The audit works with one
configured area, records actual download outcomes and then blocks HTTP during
the unchanged replay. Missing PDFs remain failures; the example has no synthetic
or cached fallback. Council availability can change. A validation receipt saying
the replay invariants passed does not mean every download succeeded; inspect
`new_downloads`, attempt outcomes and source counts.

Original consultation PDFs stay outside Git. The repository retains catalogue
pins, attempt/refresh summaries and validation receipts under
`docs/evidence/evidence-acquisition/`.

The full local suite passes **1,526 tests**. Eleven added tests exercise exact
URL selection, cold bootstrap, live-byte and document budgets across restarts,
pinned-PDF mismatch, offline mode, source/queue/output changes, interruptions
before and after acquisition, and refreshed area interpretation. Existing native
generation checks remain in the same regression suite. A successful source pass
does not bypass the remaining physical reconstruction checks.
