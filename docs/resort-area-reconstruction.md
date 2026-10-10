# Planning-led resort reconstruction

`voxel-resort-areas --job examples/alton-resort-area-job.json` selects a named
resort area before scheduling chunks. Each area lists its planning application
references and required reconstruction families. Wicker's SW8 application and
woodland-path amendment are the first target. The seed includes fifteen named
areas; areas without explicit application associations stay unresolved.

The default `extract` stage builds a dedicated source corpus, checks original
PDF hashes and extracts native polygon/line candidates. Supplemental catalogues
include the Wicker architectural and site-section documents. Existing/proposed
sheet state stays visible. This stage reports missing components and writes no
world geometry. Reusing an old park overlay is explicitly rejected as area
reconstruction. Extracted candidates are not automatically buildings or fences.

For reconstruction, give an area a `reconstruction_job` pointing to a normal
park-pipeline recipe, plus projected/geographic `bounds` and `bounds_crs` for its
target extent. Run with `--stage reconstruct --max-cycles 1`. Recipe asset paths
remain relative to the recipe. Its acquisition catalogue is replaced by the
selected area's documents, so broad resort discovery cannot change its scope.
The recipe retains the existing semantic, registration and native collision
checks. Every emitted feature must bind to available planning PDFs from that
area; unbound/foreign source geometry and geometry outside the area are rejected.

Only after source-driven compilation does the coordinator create ten-worker
100–200-chunk budgets inside the area. Every published preview carries the area
name in its parent receipt. A no-change recipe cannot count as a revamp. Missing
families keep the area partial, even if its current geometry batches finish.
Completion also requires an explicit `required_component_ids` semantic inventory
and generation of every listed component: one building of a family does not
prove that all buildings in an area were reconstructed. Without that inventory,
the result remains a partial area preview.
Following areas start from the last completed area's exact world, preserving
earlier improvements. Input and completed-world checksums bind resumption.

The seed job records expected component categories; populate `required_component_ids`
with source-bound identities after inspecting the plans. It does not ship
ready-to-build recipes for all fifteen areas.

Current integration is a local coordinator above the existing chunk runner.
The Actions workflow still consumes a prepared geometry bundle; native general
semantic reconstruction and area-controller dispatch are not automated by this
change. Wicker's remaining queue structures, track/support/tunnel components
need source-bound reconstruction recipes. It is deliberately not reported as a
fully rebuilt area merely because source sheets were scanned or old meshes exist.

Reproduce the real offline source pass by supplying checksum-matching retained
PDF directories in `source_directories`. Missing PDFs remain pending. A changed
area definition, catalogue or recipe requires a fresh reconstruction run.
