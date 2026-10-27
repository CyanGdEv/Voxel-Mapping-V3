# Wicker Man track elevation correction

The original full-layout export lowered only terrain directly under the deck.
It did not check the neighbouring banks, leaving visible trenches around the low
track sections. Its guessed 188 m queue overpass also ran through the preshow roof.
The revised generator starts again from the pre-track maintenance park, restoring
that export's outdoor terrain cuts and all roof/wall blocks above level 183.

Outdoor profile fitting probes original terrain across a 6 m shoulder corridor,
including forward/backward samples and retained stone/fence obstacles. The target
deck top clears that envelope by 1 m, then neighbouring samples rise to smooth
local bumps. The check uses actual raster slab undersides against terrain and
adjacent banks; a low source height cannot pass by excavating outdoor terrain.
Actual slab placement still uses half-block quantization.

Three explicit covered slots use different rules: maintenance and station at
183.5 m, and a preshow underpass at 180 m below the retained 184 m upper floor.
These are prototype track levels, not measured running heights. The preshow
approach descends from chainage 120 m, reaches 180 m at 125 m and stays low through
153 m before rising towards the lift. Only the declared covered track beds and
entrances allow bounded cuts. Roof and upper-wall removal at height 186 or above
is forbidden, and the preshow undercroft ceiling at 183 is separately protected.
In this export every retained building block above height 183 is unchanged.

Centre clearance is explicitly two whole air blocks above the rounded slab top,
suitable for checking this static model. Side fences remain outside that strip.
This is not a certified train envelope or a functional ride. No supports, bents,
footings or under-deck ties are added.

All 14 planning labels and their original source bindings remain in the report.
Terrain fitting can raise their display heights when the retained DTM/obstacles
conflict with the drawing. `elevation_review.source_level_comparison` reports each
difference, rather than silently changing source evidence. The largest marker
adjustment before rounding is LP6, approximately +2.47 m. Small nonzero differences
elsewhere can also arise from half-metre profile sampling. These discrepancies
need further source/terrain reconciliation before a surveyed-accuracy claim.

The complete 773.57 m retained centreline plus its explicitly estimated 1.60 m
drafting-gap connector is preserved. Independent vertical visits to one XY cell
remain separate; slab and ordered sample connectivity are checked. Banking,
vertical curvature between source levels and approach heights remain provisional.

```sh
python -m voxel_mapper.full_track_world \
  --base-directory PATH/maintenance-built \
  --markings-path PATH/source-markings.json \
  --pdf-path PATH/original-landscape.pdf \
  --output FRESH-DIRECTORY --allow-provisional
```

The profile pins original source files, base world, marker assignments, estimated
approach controls, covered slots and clearance settings. Native delivery checks
compare retained block states, verify restored upper buildings and ceiling,
check outdoor terrain/shoulder clearance, preserve shop landings and queue access,
and reopen saved chunks/archive files. Actual Minecraft client import and ride
operation are not tested.
