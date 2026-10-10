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
does not carve a generic building replacement or infer excavation.

An explicit placement field `"foundation_mode": "level_pad"` opts into estimated
grounding under `allow_estimates`. It adds a timber floor one block below the
walls and stone fill down to each sampled terrain column, including exterior
posts. Ground already at floor level is retained. It does not lower terrain,
change the source walls, fill door openings or bypass registration/identity
checks. Missing terrain, ground above the floor and fill deeper than 16 blocks
withhold the whole feature. Added cells pass the same registration-domain,
boundary and existing-world collision checks. The placement/feed hashes pin
this choice; the v2 adapter contract prevents silently resuming a v1 feed.

`assembly_identity_verified` must explicitly establish that the proposed local
assembly corresponds to the park building. Decorative dimensions remain estimates,
so normal `allow_estimates` handling still applies. The original model's unplaced
status remains recorded; the adapter does not promote it automatically.

`examples/wicker-shop-park-placement.json` records the real mapped centroid but
is deliberately incomplete. Current evidence has zero accepted controls and
checkpoints; floor elevation and source handedness are unresolved. The template
must not be enabled as a completed park placement. Pipeline integration is ready;
the actual insertion still awaits those placement measurements.

Before enabling that entry, run the [shop placement preflight](wicker-shop-placement-preflight.md).
It retains both orientations, distinguishes the fitted local origin from the
mapped centroid and checks emitted block columns against shop-area terrain.

Tests compile at 0°, the retained 25.244° candidate bearing and 90°, retain
slab/fence/trapdoor materials across chunk boundaries, reject missing registration,
datum mismatches, unverified assembly identity and collisions, and reject changed
assets/floors on resume. A synthetic terrain/base-world fixture exercises the
real park job and native composer; it does not establish real park accuracy.
