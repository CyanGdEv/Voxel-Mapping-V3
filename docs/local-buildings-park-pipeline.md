# Detailed local buildings in park jobs

The park registry now includes `local_building`. It reconstructs the 1:1 shop
from its pinned source mesh, using slabs, fence wall accents and vertical
trapdoor panels. It feeds the existing atomic compiler and chunk store, rather
than copying the local test world's grass platform or unrelated generated terrain.
The resulting rows use the normal section/cycle workers and native composer.

Add a job entry:

```json
{
  "allow_estimates": true,
  "local_buildings": [{
    "model": "../evidence/wicker-shop-projection-model.json",
    "model_sha256": "4beebc02761e1e694468cc94aa8e013d8036987b14a7138cc4e4e681c36b02b1",
    "placement": "wicker-shop-park-placement.json"
  }]
}
```

The placement file names existing manifest sources for the horizontal placement,
local profile and floor elevation. The profile source must pin both the raw PDF-
derived model SHA256 and its canonical JSON hash (`canonical_model_sha256`).
The job pins the model, placement, emitted feed, manifest and terrain configuration;
changed inputs cannot resume an old accepted job.

The horizontal source must retain an accepted `horizontal_registration_review`
with three non-collinear controls and two independent checkpoints. Its reviewed
local origin must match `anchor_xy`. Its transform must be a pure rotation and
translation at 1:1; scale changes and reflections are refused. Source meshes
are rotated before half-metre sampling, avoiding holes caused by rotating an
already completed voxel lattice. North/south trapdoor orientation accounts for
the native export's northing-to-Z sign change.

The floor uses the park's vertical datum and explicit source/status. Origin and
floor snap to the nearest metre, retaining offsets of at most 0.5 m per axis in
feature metadata. Every emitted block must lie within the checked registration
domain and park boundary, have terrain coverage and remain above the terrain.
Existing-world collisions withhold the entire feature atomically. This adapter
does not carve a generic building replacement or invent excavation/foundations.

`assembly_identity_verified` must explicitly establish that the proposed local
assembly corresponds to the park building. Decorative dimensions remain estimates,
so normal `allow_estimates` handling still applies. The original model's unplaced
status remains recorded; the adapter does not promote it automatically.

`examples/wicker-shop-park-placement.json` records the real mapped centroid but
is deliberately incomplete. Current evidence has zero accepted controls and
checkpoints; floor elevation and source handedness are unresolved. The template
must not be enabled as a completed park placement. Pipeline integration is ready;
the actual insertion still awaits those placement measurements.

Tests compile at 0°, the retained 25.244° candidate bearing and 90°, retain
slab/fence/trapdoor materials across chunk boundaries, reject missing registration,
datum mismatches, unverified assembly identity and collisions, and reject changed
assets/floors on resume. A synthetic terrain/base-world fixture exercises the
real park job and native composer; it does not establish real park accuracy.
