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
