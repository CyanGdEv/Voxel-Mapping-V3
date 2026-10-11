# Planning-led resort reconstruction

`voxel-resort-areas --job examples/alton-resort-area-job.json` selects a named
resort area before scheduling chunks. Each area lists its planning application
references and required reconstruction families. Wicker's SW8 application and
woodland-path amendment are the first target. The seed includes fifteen named
areas; areas without explicit application associations stay unresolved.

Use `--area mutiny-bay` to switch the active work area explicitly. The selected
area persists for subsequent runs without `--area`. Earlier unfinished areas
keep their status and evidence; switching does not mark Wicker complete or
relax source, registration or component-inventory checks. Once the active area
is complete, an untargeted run returns to the first unfinished area.

For a handoff from a partial review download, set `initial_base_world` to its
native bundle directory and `initial_base_sha256` to the package hash. Every
run verifies that package, and reconstruction inherits it until a completed
preceding area supplies a newer cumulative world. A review baseline does not
make its source placement accepted or mark its area complete.

The default `extract` stage builds a dedicated source corpus, checks original
PDF hashes and extracts native polygon/line candidates. Supplemental catalogues
include the Wicker architectural and site-section documents. Existing/proposed
sheet state stays visible. This stage reports missing components and writes no
world geometry. Reusing an old park overlay is explicitly rejected as area
reconstruction. Extracted candidates are not automatically buildings or fences.

The coordinator also writes `components/component-mentions.jsonl`. Queue,
stair, fence and pre-show text labels are indexed in the same native PDF
coordinate frame as the extracted geometry. Each mention retains its document
hash, page, printed wording, label bounds and a stable identity. Nearby
line/polygon IDs are review suggestions, never accepted geometry bindings.
Fence descriptions and printed height values are retained; omitted units are
explicitly unspecified. A canopy label alone does not establish a queue shelter,
and inspection levels cannot become passenger floors. Missing stair labels do
not prove that there are no stairs on a drawing. These mentions do not populate
the required physical component inventory or emit any world blocks.

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

## Full park area cycle test

Run `--all-areas --stage reconstruct --max-cycles 1` against a separate test
work directory to exercise every named area. `sweep-report.json` is saved after
each area, so missing applications, recipes, boundaries, inventories and source
files remain visible. A blocked or failed area does not stop later areas and
does not count as complete. `--area` and `--all-areas` are mutually exclusive.
Existing cumulative world and native acceptance checks still apply when a
recipe reaches generation. The cycle limit is per area, not the whole resort.

The real October 11 run tested all fifteen seed areas over the pinned V25
baseline. Five had planning associations; ten did not. None had a configured
source-bound production recipe, boundary or component inventory. Therefore
the test generated zero native area cycles or new worlds. The separately
delivered Wicker and Mutiny review drafts are retained in V25, not promoted to
accepted full-area reconstructions. See `evidence/alton-full-area-cycle-test.json`.

Current integration is a local coordinator above the existing chunk runner.
The Actions workflow still consumes a prepared geometry bundle; native general
semantic reconstruction and area-controller dispatch are not automated by this
change. Wicker's remaining queue structures, track/support/tunnel components
need source-bound reconstruction recipes. It is deliberately not reported as a
fully rebuilt area merely because source sheets were scanned or old meshes exist.

Reproduce the real offline source pass by supplying checksum-matching retained
PDF directories in `source_directories`. Missing PDFs remain pending. A changed
area definition, catalogue or recipe requires a fresh reconstruction run.

## Verified component bindings

A park-pipeline recipe may supply a `planning_components` block:

```json
{
  "planning_components": {
    "bindings": "component-bindings.json",
    "mentions": "components/component-mentions.jsonl",
    "candidates": "drawing-geometry/geometry-candidates.jsonl",
    "corpus": "corpus"
  }
}
```

When called through the area coordinator, the last three paths are replaced by
that area's current extraction and corpus. `bindings` remains a recipe asset.
Each binding is a normal drawing feature review with `mention_id`,
`component_role` (`queue` or `fence`), `label_geometry_verified: true` and a
nonempty `label_geometry_verification_reference`. Candidate and mention must
belong to the same PDF page. Native label contents are re-extracted and checked;
nearby candidate rank never supplies verification.

The existing drawing adapter then checks retained candidate bytes, PDF hashes,
physical identity, source state, reuse and independently checked registration.
Queue bindings use path/plaza families; fences use wall/fence families.
Known printed metre fence heights must match the bound height parameter.
Unspecified units and materials still need independent dimension/proxy evidence;
the index does not supply generator parameters automatically. A planar stair
mention cannot become a measured 3D stair recipe.

The resulting `planning-components/features.jsonl` enters the normal compiler.
Mention identity, role, printed claims and label association remain in feature
metadata. Source dimensions, terrain and native placement checks still apply.
Inputs and output hashes pin resumption. Area family coverage uses the same
generator aliases as reconstruction, so a path counts as paving and a wooden
fence counts as a wall; required physical component IDs still remain mandatory. Withheld bindings leave no stale
features in the refreshed feed. This adapter does not provide missing real
Wicker association or registration evidence.

## Expanding area planning associations

`python -m voxel_mapper.area_sources --job examples/alton-resort-area-job.json --output-job /tmp/associated-job.json --report /tmp/association-report.json`

The reviewed registry `voxel_mapper/data/alton-area-associations.json` adds 19
application-to-area associations across seven formerly empty areas. The seed job
now selects sources for 12 of 15 areas. This links existing catalogue records;
it does not claim 19 newly discovered applications. Two application references
are shared between Gardens and Towers, and also already selected for Mutiny Bay.

Each association carries an official application page, an exact context hash,
a required location marker and supporting resort location evidence. The binder
rejects missing references, changed contexts, unmatched application pages and
unapproved hosts. Outputs preserve the input job and resolve relative asset
paths against its original location. Existing explicit selections are retained.
Run changed selections in a **fresh work directory**: old area state remains
pinned to its original inputs.

Application association means candidate document selection only. A shared
application may contain sheets for several locations. Neither a matching name
nor permission approval accepts its sheets as current geometry: existing versus
proposed state, sheet registration, area bounds, physical component inventories
and production recipes still need validation. A withdrawn/refused scheme cannot
be used as an existing reconstruction solely because of its area name.

Adventure Land, Gloomy Wood and Towers Street remain unassociated. The registry
records targeted search queries and pending companion references for further
review. An unsuccessful indexed search is not proof that a council application
does not exist. The acquisition/sweep evidence records actual available PDFs
separately from candidate document counts and repeats.
