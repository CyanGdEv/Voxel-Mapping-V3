# Automatic planning document follow-up

The Web research tab's **Collect & analyse PDFs** button continues beyond the
first six-source batch automatically. Enter the application reference and public
application URL or search query once. The app collects discovered document
links in further small batches, exports original PDFs and runs the existing
drawing analysis. Individual drawing files and follow-up URLs need no selection.

Open `review.html` in Results for links to every completed batch, its drawing
previews and source gaps. `ledger.json` records queued URLs, completed sources,
read attempts and retry schedules. The top report distinguishes unresolved
sources from documents needing analysis/OCR review. Existing/proposed claims,
application membership, physical geometry and current as-built state remain
unverified. Known links being processed does not establish an exhaustive
application or park inventory.

Progress lives in the desktop data folder under `planning-collections`, keyed
by source scope and analysis implementation. Start the same request after an
interruption or budget stop to continue saved progress. Completed batch outputs
and original bytes are checked before reuse. Finished PDF analysis is not
repeated, including identical PDF bytes reached through a later URL. A complete
batch written immediately before worker interruption is recovered once; partial
outputs remain separate. Application restart does not initiate new website
requests on its own: resume by starting the same request. Offline cache misses
remain visible and become eligible when that scope is resumed online.

The scope includes application reference, query, source URLs, allowed hosts,
research question and drawing-analysis options/code. Changing execution limits,
offline mode, model choice or display title preserves that scope. Changed
analysis code/options/native PDF version gets separate progress. Changed saved
outputs or original source bytes block reuse rather than silently accepting
stale or corrupted evidence; use a fresh scope/cache for a changed source set.
Source hashes establish byte consistency, not physical correctness.

HTTP 408, 425, 429, 500, 502, 503 and 504, DNS failures and request failures are
retried up to three committed attempts per URL. Quota stops and offline misses
are deferred separately. The default delays are two and four seconds;
a supplied HTTP `Retry-After` is respected. Other HTTP errors, unsupported files
and source-byte limits remain explicit gaps. Exhausted retries remain unavailable
in that collection. A cached source retained after failed refresh is analysed
once while refresh failures are retried and recorded. Empty/unavailable search
results stay pending rather than being treated as a complete application.

Default execution limits are 12 batches, six sources per web batch, 64 queued
URLs, 64 MB streamed bodies across all batches and a 900-second cooperative
deadline. Failed downloads count toward bytes. A final received chunk can cross
the byte cap before rejection; subsequent requests stop. Original web host,
redirect, private-address, TLS and per-source 8 MB restrictions remain. Website
text or model proposals cannot expand host permissions or supply local paths.

The durable collection and each exported job snapshot are limited to 128 MB.
New batches receive only the remaining output space with metadata reserved.
These limits can be lowered in the collection configuration; global worker
memory is still monitored and one heavy desktop job runs at a time. A batch's
native PDF analysis and DNS calls use cooperative deadlines, so cancellation
through the managed desktop is the way to terminate a blocked worker. No hard
OS memory reservation or physical 6 GB PC acceptance result is claimed.

The collector follows actual discovered document links, not the whole website.
Batch, byte, time, URL and disk stops preserve the queue for resumption. A
document too large for existing page/output limits stays available for separate
review; source acquisition does not mean that every page was analysed. Scans,
mixed page roles and missing physical references retain the previous pilot's
gaps. Source observations create no reviewed labels, model-weight changes or
world geometry. Optional reasoning weights remain a separate installation.

Advanced jobs can load
[the Woodcutters collection example](../examples/desktop/alton-planning-collection.json)
under **Planning collection / automatic follow-up batches**. The earlier
**Web planning PDFs / automatic source pack** remains available for a single
bounded batch. Source CLI:

```sh
python -m voxel_mapper.planning_collection --config examples/desktop/alton-planning-collection.json --output /tmp/woodcutters-collection-run --cache /tmp/voxel-web-cache --state /tmp/woodcutters-collection-state
```

Packaged synthetic diagnostic:

```text
VoxelMapperV3.exe --planning-collection-smoke-test PATH_TO_FRESH_TEST_DIRECTORY
```

Tests cover multi-batch completion, reuse after restart, duplicate bytes across
batches, transient/permanent HTTP failures, retry caps and server backoff,
offline-to-online recovery, shared byte budgets, cancelled/interrupted batches,
changed source files, fabricated completion flags, scope validation, URL quotas
and unavailable search. The actual managed-worker diagnostic collects seven
synthetic PDFs from one index in two batches, restarts, and verifies zero new
analysis batches and zero reviewed labels.

The [Woodcutters development receipt](evidence/planning-collection/woodcutters-development-validation.json)
records acquisition of the application page and all 19 document attachments
discovered there. Final-code cached replay completed four automatic batches,
35 analysed pages and zero unresolved download URLs. Restart completed with
zero new batches and zero network bytes. It retained 14 visible drawing captions
and 20 surface labels, with zero supported enclosed surface candidates.
Fourteen documents still need analysis review, including oversized documents,
unknown roles and mixed elevation/section pages. Observed replay worker peak
was about 776 MB. These are source-coverage/development results; application
membership, exhaustive discovery, physical accuracy and 6 GB PC acceptance
remain unassessed. Blank PDF metadata titles use a bounded fallback title,
and saved output paths support both Windows and Linux separators.
