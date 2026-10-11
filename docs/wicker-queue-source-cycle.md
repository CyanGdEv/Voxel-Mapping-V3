# Wicker source queue preview

V24 adds one new ground-floor queue-walkway outline over the cumulative V23
park. This is a partial named-area review, not a completed Wicker reconstruction.

The pinned 2967-21 P1 PDF has four connected strokes at ordinals 601–604.
The native page frame and retained floor-sheet reduction correction produce
an approximately 2.70 × 16.50 m footprint. The pose follows the retained
station roof correspondence, then converts into the park's projected metre
frame. This remains provisional and has no independently accepted survey checks.

The builder samples the actual saved native terrain near the dated terrain
raster. It withholds protected Wicker building columns and locations without
a two-block clear surface. The source outline contains 45 raster columns;
26 are withheld and 19 receive stone paving under the user's no-material-label
default. Eight optional one-block oak-fence cells stand outside the walkway.
These rails are visual proxies, not a verified fence specification. Ends remain
open, and adjacent retained paving cells differ by at most one vertical block.

One ten-worker cycle schedules two native chunks. Every new cell has a bounded
replacement fingerprint. The exported package passes cold readback for all 27
written cells, solid bearing under every rail, all 4,757 native chunk identities
and section equality for the other 4,755 chunks. The ordinary native writer also
verifies all cells of touched sections. The full local suite has 826 passing tests, including a terrain-pinned native cycle fixture with protected-column and cold-download checks.

Reproduce with `python scripts/build_wicker_queue_cycle.py --job JOB.json`.
The job names `output`, `floor_pdf`, `wicker_quality`, `base_package`,
`base_quality`, `protected_geometry`, `grid_directory`, `terrain_config` and
`terrain_raster`. Optional `review_rails: true` requests the inferred rails.
All input assets are fingerprinted. A fresh output directory is required;
its generated cycle bundle can be resumed through the existing cycle runner.

The source-area coordinator deliberately keeps Wicker unresolved. This separate
review download does not satisfy its physical component inventory, registration
or existing/as-built gates. The remaining queue, stairs and ride structures
still need reconstruction and placement evidence before advancing to another area.
