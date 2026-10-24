# Public web research

Use **Analyse planning PDFs** for the [automatic drawing-analysis handoff](web-planning-pilot.md).

The desktop **Web research** tab gathers public pages, native PDF text and plain
text as cited evidence. Enter an explicit search query, source URLs, or both.
The default source hosts cover Staffordshire Moorlands Council and Alton Towers;
edit that list when you deliberately want another public source. Search uses
DuckDuckGo's public HTML results, with no API key. Result links are filtered to
the listed hosts. Search-provider availability and indexing vary.

Leave **Installed local model** blank to gather evidence without loading model
weights. To let a reasoning model select discovered links and summarise sources,
install Ollama and a suitable small model separately, start its local server,
and enter its installed model name. This does not download a model automatically.
On the 6 GB CPU profile, evidence gathering is the default; language-model RAM
and quality depend on the selected model. Actual inference with installed weights
and acceptance on a physical 6 GB Windows PC remain untested for this feature.

Advanced jobs can load [the Alton example](../examples/desktop/alton-web-research.json)
using **Web research / cited source evidence**. Add `model` for the optional
reasoning controller. `endpoint` and `model_options` use the existing reasoning
adapter's validation; the default is `http://127.0.0.1:11434`. An explicitly
configured remote reasoning endpoint receives the question and bounded source
and memory context. Cache-only mode applies to website reads, not that endpoint.

For source runs:

```sh
python -m voxel_mapper.web_research --config examples/desktop/alton-web-research.json --output /tmp/alton-web-run --cache /tmp/alton-web-cache
```

Each run saves a report, individual source receipts and optional model rounds.
Original downloaded bytes are addressed by SHA-256 in the persistent `web-cache`;
immutable snapshots retain the retrieval time, final URL, redirects, original
byte hash, extracted text, truncation and citation ID. Offline reads check the
bytes and reconstruct the text and links before reuse. A failed refresh can
reuse an existing valid snapshot, explicitly marked `cached_after_network_failure`
with its original timestamp and the failure. Cache absence, HTTP errors, private
addresses, unsupported files and parse failures remain visible gaps. A valid
hash establishes byte consistency, not the truth or currency of a planning claim.

The managed worker retains short `web_source_observation` records in desktop
memory; these survive restart and are available through bounded reasoning
context. They are unverified observations. Web research creates zero reviewed
labels, updates no model weights, and adds no geometry to a world.

The optional controller can execute only `read_web` requests for exact links
actually offered in its current context. It performs at most two model rounds
and reads at most six sources. Other model proposals remain advisory. Model
round receipts still say `proposals_executed: false`, because the reasoning
adapter itself executes none; the separate controller records its performed
read-only requests. Unknown citation IDs suppress the report's model summary.
Citation content is not fact-checked, and a fluent summary is not a measurement.

Reads use GET, no browser login, script execution, form submission, or origin
credentials from `.netrc`. Every redirect must remain within the explicit host
list; private/special addresses and nonstandard ports are rejected. DNS is
checked before each request but is not pinned into the transport. Existing TLS
certificate/proxy settings are preserved. Website text cannot change the source
host list or authorize file, training or world operations. Only the explicit
public search query is sent to the search provider; local memory is not appended.

Default limits are 8 MB per source, 16 MB streamed response bodies per run,
12,000 extracted characters, the first three PDF pages, two reasoning rounds,
and a 300-second run deadline. Byte limits count actual streamed data, including
failed reads; the final received chunk can cross the cap before rejection.
The cache is limited to 256 MB and 2,048 entries; archive it or choose another
data directory when full. These settings can be lowered, not increased, through
the job configuration. Managed cancellation terminates a blocked subprocess;
DNS/native parsing deadlines in the direct Python API are cooperative. Scanned
PDFs are marked as requiring OCR: this reader does not run OCR or extract
measured/vector geometry. Reuse the original-drawing planning pilot for that
separate analysis and its reconstruction checks.

Validation uses synthetic transport/model protocol fixtures, the real managed
offline worker, cache tamper checks, and frozen Windows packaging checks. A live
2026-10-24 check retrieved `example.org` over HTTPS, verified its offline cache,
and found four scoped official council search results including the Woodcutters
application. Alton Towers' home page returned HTTP 403 from this environment.
The application page itself was retrieved over HTTP; its first attempted
attachment timed out and was retained as an explicit source gap. HTTP sources
have no transport authentication.
These checks establish transport/controller behaviour, not model reasoning
accuracy, permission to bypass blocked sites, or autonomous park reconstruction.

Packaged offline diagnostic:

```text
VoxelMapperV3.exe --web-smoke-test PATH_TO_FRESH_TEST_DIRECTORY
```
