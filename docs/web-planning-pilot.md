# Automatic web PDFs to drawing analysis

The **Web research** tab now has **Analyse planning PDFs**. Enter an application
reference and a public application URL or search query, then start the job.
The app gathers sources, verifies cached original bytes, copies original PDFs
into the job's `originals` folder, creates a drawing manifest and runs the
existing building-view and surface discovery pipeline automatically. No file-by-file
PDF selection, drawing roles, page numbers or view rectangles are required.

The [Woodcutters example](../examples/desktop/alton-web-planning-pilot.json) can
also be loaded under **Web planning PDFs / automatic source pack** in Advanced
jobs. The example uses the public HTTP council application page that was reachable
in development; HTTP supplies no authenticated transport. HTTPS can be entered
when the council endpoint is available. The collector preserves its existing
host restrictions, private-address checks, redirects, TLS settings and quotas;
it does not silently downgrade an entered HTTPS URL.

Open `review.html` in the Results folder. It links to the web sources and
failures, the original-PDF handoff/classification ledger and the nested drawing
review with previews and extraction evidence. `planning-manifest.json` is also a
replayable input for the original planning pilot using the exported `originals`
directory. All completed outputs have hashes in the report.

Page classification uses literal native caption text. Roles and printed
existing/proposed claims are hints, not confirmed physical scope or current
as-built state. Mixed states remain `unknown` at document level, with every
page's claims retained. Mixed page roles remain `unclassified`. Catalogue/link
titles never override the page's native role. Page-specific roles keep elevations,
roof plans, details and unclassified pages out of ground-surface discovery.
These pages still receive the building drawing discovery pass. A PDF with no
native text carries an explicit OCR gap; this bridge does not perform OCR.

The supplied application reference names the selected research scope. Parent
links retain whether that reference appeared in their source text. Neither that
observation nor an AI summary verifies that an attachment belongs to the selected
application. Application membership, source claims, drawing scope and physical
identity remain unverified throughout the resulting pack.

Before handoff, the app reopens and validates the exact web snapshot reported
by research, verifies its original-byte hash and derives local filenames only
from that hash. Identical PDF bytes at different URLs are analysed once.
Original cache and exported bytes are checked again after drawing analysis.
Changed cache snapshots become explicit handoff gaps; originals changed during
analysis prevent a completed top-level report. The source PDFs are not rewritten.

The existing web stage reads at most six sources including index pages, so
this pilot is not an exhaustive application crawl. Unattempted discovered links
and drawing links are listed explicitly in the reports; unattempted documents
remain a reconstruction blocker. Six sources can include fewer PDFs due
to timeouts, non-drawing documents and navigation. A complete PDF must fit the
page budgets; excessive documents are withheld without silently selecting a
subset of pages. Analysis limits can only be lowered through `analysis_options`.
The default maximum is 32 total pages, eight per document. The combined output
budget is 128 MB, including exported originals, web receipts and analysis files;
the analysis pass receives only the budget remaining after source acquisition.
The managed desktop still allows one heavy job at a time and monitors its worker
memory. Cancellation keeps partial outputs separate from a completed report.

The optional installed reasoning model operates only in the web stage. Its
read requests cannot alter drawing roles, supply file paths or approve geometry.
Ollama/model weights are not bundled; actual model quality and acceptance on a
physical 6 GB Windows PC need separate validation.

This step produces an analysed source pack. It supplies no measured reconstructed
building, registered path network, world additions, correctness labels or model
weight updates. The next reconstruction work is measured outlines, heights,
surface boundaries, cross-view correspondence and geographic registration
against independent references.

Source invocation:

```sh
python -m voxel_mapper.web_planning_pilot --config examples/desktop/alton-web-planning-pilot.json --output /tmp/woodcutters-web-planning --cache /tmp/voxel-web-cache
```

Packaged synthetic diagnostic:

```text
VoxelMapperV3.exe --web-planning-smoke-test PATH_TO_FRESH_TEST_DIRECTORY
```

Tests cover a single cached application link becoming an original two-page
drawing analysis, per-page surface gating, mixed states/roles, roof plans,
unknown captions, missing native text, deduplication, source mutation,
cancellation, total output budgets and durable worker memory. The frozen Windows
workflow runs the same application-to-drawings diagnostic with the actual EXE.

The [recorded Woodcutters development run](evidence/web-planning-pilot/development-validation.json)
retrieved the application page and five original PDFs live, then verified and
analysed all five pages automatically. A final-code offline replay preserved
the same source bytes and produced eight visible drawing captions and 20
surface labels, with zero supported enclosed surface candidates. Fourteen
discovered document links remained unread under the six-source budget. The
proposed elevations/sections page retained mixed roles as unclassified while
still supplying its building caption inventory. The replay's observed worker
peak was about 775 MB. These are development/source-coverage results, not
physical reconstruction accuracy or a 6 GB Windows acceptance result.
