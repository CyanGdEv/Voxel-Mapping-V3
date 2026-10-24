# Conditional planning world downloads

A completed planning job can export its conditional row-group models as separate
Bedrock `.mcworld` files. Both the clear-gap and row-centre interpretations are
kept. These are explorable local surface-envelope prototypes on flat display
terrain, with no accepted placement in an Alton Towers park world.

In the Windows app:

1. Select a completed planning source, web planning or collection job.
2. Choose **Export preview worlds** and wait for the export job to finish.
3. Select that export and choose **Open world**. The page links each download and
   its audit. Save a `.mcworld` and open it with Minecraft Bedrock installed.

The target format is Bedrock 1.21.130. Each world starts in Creative mode with
mobs and daylight cycling disabled. Spawn is beside the row envelopes, supported
by grass, with two saved empty blocks above the ground. Minecraft import,
gameplay and player movement have not been tested by the export checks.

## Source and geometry

The request pins the exact saved `design-massing.json` bytes. A desktop request
also verifies that file against the completed planning job's output manifest.
The worker verifies the current review version and self-hash, complete source
page pins, claim hashes and exact current canonical specification. It recomputes
specifications from retained source claims rather than accepting a replacement
mesh in a re-signed review. This exports previously extracted claims; it does
not reanalyse or authenticate the original PDF independently.

The original specification remains unchanged. The existing building-native
compiler samples its surface at one block per source metre. Sub-metre boundaries
alias to full blocks; the report retains both source dimensions and actual
native cell bounds. For the current Woodcutters source, the 2.5 m row envelope
spans native Y cells -1 through 2. These display cells are not a new measured
height. Surface sampling leaves interior air; it does not fill solid volumes or
establish usable cabin interiors. The horizontal top is the row envelope's
display boundary, not a reconstructed canopy.

Local model `(X, depth Y, height Z)` becomes Minecraft `(X, height + offset,
-depth)`. The embedded georeferencing explicitly names local axes and has no
CRS or surveyed datum. A grass platform and four-layer artificial foundation
support the preview. They are not recovered park terrain. Existing and proposed
source states remain separate. Roof profile, openings, individual cabin
correspondence, paths/plazas and actual geographic alignment remain unresolved.

## Verification and limits

The native writer reopens LevelDB and compares every composed material and all
unwritten air occupancy in saved sections. A callback then checks saved spawn
metadata, supporting grass and two empty headroom blocks. The archive must have
root `level.dat` and `db/` entries, unique safe paths and no `LOCK` file. Every
packaged file must match the verified writer output; ZIP CRCs are checked. A
fresh extraction is opened again to check spawn and load every saved chunk.
Source specifications and claims are included in each world.

Outputs publish only after all selected worlds pass. Failure or cancellation
removes the temporary job output, and existing output directories are refused.
Managed workers retain the existing single-heavy-job scheduling and configurable
memory cap up to 16,384 MB. Each job supports at most eight worlds, each platform
at most 25,000 cells and each world at most 150,000 composed write attempts.
Requests must retain both spacing rivals for every selected source claim.
These checks do not create reviewed labels, train neural weights or certify
physical accuracy, structural safety or complete-park generation.

Advanced desktop JSON operation `planning_world_preview`:

```json
{
  "version": "planning-world-preview-v1",
  "review_path": "path/to/design-massing.json",
  "review_sha256": "<SHA-256 of the saved file bytes>",
  "alternative_ids": ["<clear-gap alternative ID>", "<row-centre alternative ID>"]
}
```

Paths resolve relative to the request file. `alternative_ids` is optional when
the review contains at most eight alternatives; larger reviews require explicit
complete source-claim pairs. Results include `index.html`, the downloads,
`quality-report.json`, the pinned source review, unchanged specifications and
voxel intents. `output_sha256` covers every output except the report containing
the manifest itself.
