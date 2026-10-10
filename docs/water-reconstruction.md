# Water surfaces and beds (V10)

Unsurveyed water previously emitted only one surface block. Terrain underneath
accepted water footprints was masked, leaving a floating sheet and open void.
The mask was also registered before a lake level was accepted, so rejected
surfaces could leave bare holes. Open river lines did not receive the polygon
water-bed logic after buffering.

The builder now masks terrain only after accepting a water surface. Lakes use
consistent interior terrain samples or a declared absolute level. Streams use
local terrain-supported levels, with a short median window on line centrelines.
An inconsistent lake estimate preserves terrain rather than cutting a hole.
Canals with inconsistent level samples use the provisional flowing profile.

Measured absolute bed rasters continue to take precedence. Without valid bed
coverage, a labelled visual shelf slopes from one block deep at the shore to a
maximum of three metres. Bed cells are solid gravel; underlying artificial
foundation fill closes their undersides. Missing/invalid measured columns use
estimated shelves rather than being described as measured depths.

`water.estimated_bed` defaults to true and can disable the preview fallback.
`water.max_depth_m` defaults to 3 (supported range 1–10). Estimates retain
`bed_status: estimated_shore_shelf`, no measured bed source and separate counts
from measured columns. Native water blocks declare source-water states explicitly
so complete export readback compares identical states.

## Retained-world repair

The repair module repairs registered local water footprints on an existing
world, retaining its vertical offset and protecting structural/paving block
materials. The Alton V10 pass uses the accepted local features and retained DTM;
no surveyed bathymetry is available for these water bodies. Streams cap preview
depth at two metres. The bed fill uses nearby terrain minus the existing
16-block foundation depth, bounded to 32 blocks below the bed.

```bash
python -m voxel_mapper.water_repair \
  --source verified-v9-directory \
  --features original-generation/features-local.geojson \
  --output new-water-v10-directory \
  --datum-grid retained-grid.tif
```

All 13 mapped water bodies receive repairs, across 34,202 unique columns.
Export checking verifies every water column and its full solid bed/fill:
zero missing water cells and zero missing solid cells. Full touched-section
and chunk-coverage readback passes across 264 chunks. The overlay has 585,660
records and a net solid delta of 544,343 blocks.

All 245 reviewed V6 landscape details and all 47,287 non-Wicker V8 overlay cells
remain unchanged. Wicker's 7,950 deck/support cells remain unchanged, all 165
bents remain connected, and all 5,019 rider-envelope cells remain clear.
All 335 tests pass. Evidence: `evidence/water-v10-validation.json`.

The before/after section is sampled from reopened world blocks across the same
Boating Lake section. Depths, gravel substrate and foundation fill are visual
estimates; flowing levels are terrain-supported previews, not measured hydraulic
profiles. These estimates do not establish actual lake depths or engineered
channel/lock geometry.

## V11: rejected river polygons and bank-contaminated ponds

The V10 retained repair checked accepted features, so two polygons omitted from
`features-local.geojson` still contained holes. OSM `natural=water, water=river`
areas now receive the same flowing-water treatment as `waterway=river` lines.
The pond beside that river has a dominant low plateau: a bounded fallback
accepts at least 75% of 12 or more samples within a one-metre band, with no
significantly lower samples and higher bank outliers capped at eight metres.
Slopes, split terraces and lower channels remain rejected. This is an estimated
surface elevation, not a survey or hydraulic model.

The retained repair must receive the complete local source-water collection,
including rejected features, rather than only the builder's accepted output.
For this export, the original terrain mosaic was recovered byte-for-byte.
Current OSM water geometry was projected into the original world coordinate
frame and clipped to the mapped park boundary. Underground water/tunnel
features were preserved rather than promoted to surface water.

All 15 surface-water features are checked: 38,930 repair columns have water and
solid beds/fill. An independent scan of 1,165,980 existing-world columns inside
the mapped park boundary found 4,885 columns without any natural floor before
repair and zero afterward. This detects full-column voids; it does not prove
that every underground cavity, bank profile or estimated water level is correct.
All 21,703 physical cells from the retained V9 completion overlay are unchanged,
as are the 5,019 Wicker Man rider-clearance cells. Bed depths remain visual
estimates. See `evidence/water-v11-validation.json`.
