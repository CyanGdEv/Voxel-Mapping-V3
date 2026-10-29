# Park-wide native LiDAR geometry

The finer pass covers the complete 2,080 × 1,120 m Alton world rectangle,
including the main park, gardens, ride areas, car parks and hotels. It is not a
Wicker-only crop. All 98,342,681 source points are scanned; every one of the
11,033,630 eligible local returns is indexed without random thinning. Survey
P_10682, 5 January 2022, remains in native EPSG:27700/ODN.

## Evidence retained

The sparse three-dimensional index uses 0.25 m cells in X, Y and Z, retains
classification and multiplicity, and contains 10,869,678 occupied sample cells.
The equivalent one-metre three-dimensional index has 6,247,300 cells. These are
bin counts, not additional observations or a measured increase in survey density.
There are 1,142,838 native horizontal columns with multiple observed height
layers. A single highest-return raster cannot preserve this information.

Original class-1/6 XYZ is retained alongside the index. The separate standard
LAZ delivery preserves all 11,033,630 eligible local source records, their
original coordinate scales, classifications, returns and other point fields.
Withheld and synthetic records are excluded with Boolean masks. Noise-class
records remain identifiable in the evidence and never become structure blocks.
Unclassified points are retained evidence; they are not automatically interpreted
as buildings, trees or ride track. Vegetation never establishes structural height.

## Geometry used by the world

- Ground refinements use weighted medians of all class-2 returns through their
  quarter-metre height bins. At least three source returns are required. Columns
  with more than 1.5 m of mixed height or disagreement with the matched DTM are
  left unchanged. Source water, bridges, building footprints and retained
  structure/passage grades are protected. Surface materials remain unchanged.
- Observed building roofs retain supported local height layers without the
  earlier three-by-three metre median smoothing. Isolated high returns do not
  set a roof. Distinct observed lower planes may supply awnings/overlapping
  surfaces; vertical facade points do not become invented interior floors.
- Supported class-6 returns outside mapped building outlines supply sparse
  observed surface voxels. Every supported half-height layer is retained, so
  vertical overlap is not collapsed to a highest roof. Two observed halves in
  the same native block combine into a full block. No volume extrusion,
  inferred footprint completion or interpolation across unseen gaps is applied.
- All vegetation classes are regridded from the fine park-wide index. Their
  original 4,102,575 observed one-metre occupancy cells are recovered exactly.
  Existing leaf geometry was already based on all eligible source returns;
  finer indexing does not invent additional tree branches at the same block scale.

The v3 reference geometry, running clearances and 13,000 retained Wicker blocks
keep priority. Whole grade/roof columns around retained blocks and passages are
frozen for this update, without clearing natural canopy above those columns.
The native world remains one block per metre horizontally, with half-block
structural sampling vertically. The fine index and full-precision LAZ preserve
detail for future meshing or a differently scaled world.

## Build and verify

```sh
python -m voxel_mapper.lidar_detail \
  --archive RETAINED_SK0540.zip --source-receipt point-cloud-receipt.json \
  --frame frame.json --output FINE_SAMPLES

python -m voxel_mapper.alton_aligned_world \
  --work RETAINED_ALTON --wicker RETAINED_WICKER \
  --surface-layers surface-layers.json --reference-edits world-edits.json \
  --lidar-detail FINE_SAMPLES/lidar-detail-receipt.json --output FRESH_WORLD

python -m voxel_mapper.lidar_detail \
  --archive RETAINED_SK0540.zip --source-receipt point-cloud-receipt.json \
  --frame frame.json --native-crop Alton-Towers-Park-Wide-LiDAR.laz

python scripts/verify_alton_lidar_update.py \
  --work RETAINED_ALTON --wicker RETAINED_WICKER \
  --surface-layers surface-layers.json --reference-edits world-edits.json \
  --lidar-detail FINE_SAMPLES/lidar-detail-receipt.json --output FRESH_WORLD \
  --baseline Alton-Towers-Reference-Rebuild-v3.mcworld \
  --native-cloud Alton-Towers-Park-Wide-LiDAR.laz
```

Sixty-three relevant tests cover all-class conservation, unthinned native LAZ,
source/CRS/hash restrictions, height separation, isolated spikes, holes, facade
rejection, protected grades, outside-footprint surfaces and native priorities,
alongside the earlier export/reference/material/terrain checks. The world writer
reopens all 9,100 native chunks and compares every material/state and the complete
air envelope. The separate verifier compares actual saved v3/v4 blocks across
the whole rectangle, checks retained ride roles and passage air, and matches the
full-precision LAZ to every fine-index key/count and all original structural XYZ.

The output title is **Alton Towers — LiDAR detail v4**. Exact geometry and native
comparison counts are in `evidence/alton-park-wide-lidar-validation.json`. The
before/after image is generated from native saved blocks and differences, not an
aerial overlay or a Minecraft client screenshot.

Roof residuals measure fit to accepted survey layers, not held-out accuracy.
Unseen surfaces, seasonal occlusion, source age/classification errors, generic
materials and Minecraft quantisation remain limitations. Earlier ride elevations,
supports and stations remain provisional. No new airborne survey, neural weight
retraining, independent physical registration or Minecraft client test is claimed.

Contains Environment Agency information © Environment Agency and/or database
right, OGL-UK-3.0. Existing OSM, Esri/provider, user-guide and planning-source
attribution remains embedded in the world.
