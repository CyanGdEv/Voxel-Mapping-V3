# Mutiny Bay canopy review cycle

V25 adds a bounded canopy review over the V24 cumulative full park. It does
not establish accepted registration or complete the courtyard or Mutiny Bay.

The source is the pinned existing roof sheet 3023-10. Twelve visually reviewed
central canopy corners snap to native straight-line endpoints in its displayed
PDF frame. The cruciform outline covers 222.38 m² at the printed 1:200 scale.
The pose uses the correct mapped courtyard relation 5496185, its inner member
106842140 and the site north direction. Scale is fixed at the printed value;
the drawing is not stretched to fit the map. The transformed courtyard inner
boundary differs by 12.76% in area and 1.37 m Hausdorff distance. Roof and wall
extents may differ. No independent survey controls are accepted, and the
previous BBQ-polygon diagnostic remains rejected.

V25 rasterises 227 canopy roof columns at one block per metre. Spruce slabs,
34 full-block roof seams, six fence supports (18 cells) and eight trapdoor
brackets are visual proxies. Eaves/ridge levels of 182/184 m, roof pitch,
post layout and materials are estimates inside the saved placeholder height
envelope; they are not measured drawing specifications. Saved ground bearing
controls the support base. Roof seams join slab steps instead of leaving
separate floating panels.

Clearance removes 549 generic stone/stone-brick placeholder cells within the
mapped central canopy footprint, above its saved floor and below 185 m. Any
column containing conflicting materials or extra blocks in that envelope is
withheld as a whole. The actual run withheld zero columns. Courtyard wings,
paving, overhead fixtures and Wicker work remain in the cumulative baseline.
This does not apply the unbuilt proposed smokehouse scheme.

One ten-worker review cycle changes 836 cells in four chunks. The package
passes cold readback for every cell, solid bearing beneath every support,
unchanged saved floor, all 4,757 chunk identities and section equality for the
4,753 untouched chunks. The normal writer also verifies touched sections.
All 833 tests pass. See `evidence/mutiny-canopy-v25-validation.json`.

Run `python scripts/build_mutiny_canopy_cycle.py --job JOB.json`. The job names
`output`, `roof_pdf`, `osm`, `previous_review`, `base_world`, `grid_directory`,
`terrain_config` and `terrain_raster`. Inputs and native replacement blocks
are fingerprinted; a fresh output directory is required. `previous_review`
is the retained V22 validation containing the source courtyard outline.
The OSM input retains way/member identities; this run converted a fresh
OpenStreetMap map extract, bbox -1.893,52.987,-1.887,52.991, into the existing
geometry JSON representation. These dated map references are checks, not
independent survey control. OpenStreetMap contributors, ODbL.

Visit the preview with `/tp -463 141 -117`. The package retains the baseline
spawn. The next reconstruction preview must inherit V25's native bundle and
package hash. The production area coordinator keeps Mutiny Bay incomplete;
this separate `review_draft` does not bypass its acceptance gates.
