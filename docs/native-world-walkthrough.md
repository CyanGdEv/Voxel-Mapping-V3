# Native world walkthrough

The pilot exporter now provides a complete walking route from the saved spawn,
outside the building, through each resolved entrance and into the declared
interior. Routes are traced from reopened native blocks using the existing
conservative support/headroom/half-step rules. No Minecraft client runs as part
of export. Every gameplay result starts as `not_run`.

Restore the three originals described in
[the provisional component guide](provisional-component-review.md), then run:

```sh
python -m voxel_mapper.world_pilot \
  --job examples/wicker-doorway-review-a-job.json \
  --output output/wicker-walkthrough-a

python -m voxel_mapper.world_pilot \
  --job examples/wicker-doorway-review-b-job.json \
  --output output/wicker-walkthrough-b
```

Use fresh output directories. Each exported pilot world now includes:

* `playtest-guide.md`: import instructions, walking mode, reset command and
  per-entrance native waypoints with spawn, crossing and interior points marked.
* `playtest-routes.json`: exact route coordinates in the local audit frame and
  Minecraft's native frame, tied to the exported world's SHA256.
* `playtest-results.json`: a blank human result form for import, supported spawn,
  mapped surfaces, each entrance, building exterior and terrain edges. The form
  retains the world hash, observer/platform/version/time fields, notes and
  optional evidence references. It does not authenticate the observer.

Open `park.mcworld` in Minecraft Bedrock. This build targets **1.21.130**;
record the actual tested version. Follow the generated guide, switch from
Creative to Adventure for the walking checks, and walk both directions through
each entrance without flight or jumps. Use Creative afterwards to inspect the
exterior and roof. Keep the original export unchanged and edit a copy of the
result form. Record `pass`, `fail`, `blocked` or `not_run` for each check. A
failure should include its native position and a screenshot/reference if possible.

`pilot-report.json` hashes all three initial walkthrough files. A filled copy
will naturally differ from the blank form. Importing/saving in Minecraft may
also change world/database bytes; the form identifies the original export.
No completion or acceptance field in the pilot report is updated from an edited
form. There is no automatic feedback or training-label conversion.

## Exterior route proof

Access audit version `provisional-world-access-v3` retains the actual path,
rather than only reachability booleans. The spawn-to-crossing portion stays
outside the footprint except for the selected entrance's native columns. Its
remaining portion stays on the declared floor and enters the footprint interior.
The search has the existing 60,000-state bound. Missing or blocked witnesses
remain unresolved and are shown as unresolved in the access diagram and guide.

This closes a second interior-detour false pass. With two separate elevated
mapped approaches, each entrance could have an exterior route from *some*
mapped path, while spawn could reach the second entrance only by entering the
first and crossing the interior. The earlier booleans both passed. The new
spawn-to-entrance witness rejects that second exterior approach. A synthetic
saved-world regression reproduces the previous pass and checks the withheld
result without changing geometry.

Waypoints use block centres: local column `(x, z)` becomes native
`(x + 0.5, -z + 0.5)`. The feet height is the local half-unit standing height
divided by two, plus the native export offset. Negating `z + 0.5` would put the
point one native block away. Half-slab standing heights remain fractional.

## Scope of the retained scenes

Both Wicker orientation hypotheses retain the same source model, voxel data,
estimated approaches and block composition as the connected-doorway iteration.
The new routes and guide do not move the building, widen openings or add blocks.
The exported archive hash changes because its embedded access report now contains
the route witnesses. Fresh exports need not have identical archive bytes.

Hypothesis A has native walkthrough routes through all three declared openings.
Hypothesis B has routes through its two broad openings; its northwest door stays
unresolved because its mapped approach connects to spawn through the building
interior. The previous audit marked it green. The new guide retains that failure
instead of providing a route through another entrance. These are automated
collision diagnostics, not completed in-game tests.

Full spawn-to-interior route lengths (including existing exterior terrain/path,
not just the separately bounded construction approaches):

| Scene | opening-NE | opening-SW | door-NW |
| --- | ---: | ---: | ---: |
| A | 9 m | 57 m | 23 m |
| B | 81 m | 9 m | Unresolved |

The 184 m floor, orientation, materials and source-to-building identity remain
provisional. Three elevated OSM paths still lack absolute elevations and remain
withheld. The narrow source doorway remains a wider native-grid approximation;
successful movement does not verify its source width.

The first real accepted placement still needs independent controls/checkpoints,
floor/datum and source state/identity. Accepted real planning components and real
reviewed training labels remain zero; the candidate ranker remains an untrained
baseline. The validation receipt under `docs/evidence/walkthrough/` records the
retained native routes, hashes, old/new false-pass reproduction and test results.
