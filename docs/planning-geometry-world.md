# Current paving, rock and oak-fence world

The Windows app's **Export area world** action now uses complete same-page paving
and gap evidence when available. It exports a Bedrock `.mcworld`, a top-down
preview, an oblique block schematic and saved-world checks. Existing requests
without this evidence retain the previous area exporter.

The bundled `rock-boundary-reference.json` saves the user's generation style:
low irregular stone, stone bricks and cobblestone, with slabs, stairs and wall
posts, between half a block and two blocks high. These are prototype style
choices from the supplied Minecraft image, not dimensions extracted from plans.
The separate source gap policy and original contours remain unchanged.

Paths **strictly narrower than four blocks** use **oak fences** instead of rock.
Exactly four blocks retains rock. Width is the first continuous source paving
cross-section along the local outward boundary normal, at one block per nominal
metre. Remote paving across another island does not increase that width. At
corners the narrower supported normal takes precedence. Grass-side connector
cells join diagonal fences where possible, without occupying paving or protected
buildings. Unresolved widths keep the saved rock default and are reported.

## Wicker prototype

The current source replay uses 43 paving regions from page 1 of SMD/2017/0111,
with nominal scale from the printed plan. The complete 219 by 157 block platform
has 34,383 cells, including 7,558 paving cells, 839 oak-fence columns and 462 rock
columns (534 rock blocks). All paving cells remain clear above ground. Four
building proposals are yellow ground-level footprint markers; no buildings,
roof heights, ride structures or surveyed terrain have been reconstructed here.

170 grass-side connectors were added. 25 diagonal fence pairs could not be joined
without violating the geometry protections; four boundary samples have unresolved
width. 27 of 43 source boundaries have no eligible one-metre edging sample after
paving and building protection, and one tiny paving region has no centre sample.
Those omissions are listed in the report, not silently promoted as complete
reconstruction. The nominal frame is not surveyed park registration.

The exporter verifies every written native block and property, unwritten air,
all platform cells, boundary profiles, paving headroom and supported spawn.
It checks ZIP CRCs, compares packaged files with the verified world and reopens
all 165 chunks after extraction. Minecraft import and actual player movement
have not been tested; the previews are schematics using the generated cells,
not screenshots from Minecraft. The prototype does not update model weights or
create training truth.

## Reproduce and limits

The review bundle includes byte-identical pinned source JSON and a portable
`generation-request.json`. From an installed source checkout, run:

```sh
python -m voxel_mapper.planning_geometry_world --config /path/to/generation-request.json --output /path/to/fresh-output
```

This is a separately bounded prototype exporter: at most 65,536 platform cells,
512 metres per side, 300,000 native write attempts, 200,000 input points,
2,000,000 sampling checks and 20,000 width probes / boundary cells. The Wicker
replay uses 146,787 write attempts. Limits may only be lowered; oversized complete
geometry fails rather than being cropped or rescaled. Native writes use the
existing SQLite composer and saved checks decode one chunk at a time. Legacy
area-export limits and promotion gates are unchanged.

Tests cover the strict four-block threshold, disconnected paving intervals,
corners, deterministic partial-block shapes, diagonal fence connections,
protected paving, source mutation and substitution, cancellation/quotas, native
block-state/archive checks, managed desktop selection and restart. The frozen
Windows smoke runs an original PDF through planning analysis and the managed
exporter, verifying both oak fences and rock in the packaged executable.
