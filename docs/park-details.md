# Planning details beside paths

The V5 detail pass starts with the verified V4 paving world. It adds reviewed
rocks, planter boxes, wall sections and missing buildings without changing ride
layouts or replacing existing solid blocks. This is an initial detail pass,
not complete park landscaping.

## Candidate extraction

`python -m voxel_mapper.park_detail_plans` reads pages with an existing provisional
alignment in the paving audit and checks each PDF against its SHA-256. The same
visible solid grey/black linework used for paving is noded into closed faces,
with a separate detail area budget of 0.15–1,500 m². Curves and supported clipping
are retained. Paving's default area budgets remain unchanged.

Exact object labels bind to the smallest bounded containing face. Rock and wall
size constraints withhold broad landscape/paving faces; scale-bar boundaries
are excluded. A planter can bind to a uniquely adjacent drawn footprint within
1.5 m when the next candidate is at least 0.5 m farther away. No shape is created
from a label alone. The inventory contains candidates only: legends, title
blocks, ride platforms and physical semantics still need native-page review.

```bash
python -m voxel_mapper.park_detail_plans \
  --planning-cache /absolute/path/planning-sources \
  --paving-audit /absolute/path/park-planning-paving-audit.json \
  --output /absolute/path/detail-candidates
```

`data/alton-path-details.json` retains 21 explicitly reviewed native footprints,
labels, source URLs/hashes, page/face IDs and alignment poses. The review rejected
Marauder's Mayhem's circular ride platform despite its contained "building"
elevation annotation, a long ambiguous rock-labelled edge, and broad paving or
title-block faces containing wall labels. The export withholds five reviewed
rocks that collide with mapped through-paths or existing solid cells.

## Materials and height

Printed stone/brick/timber/concrete wall and building labels select the relevant
vanilla block material. Separate material words inside a reviewed building
footprint are retained as evidence. Adjacent CAD text spans "steel" and "clad"
can form one material phrase; isolated or conflicting material words do not.

The two emitted buildings have planning footprints and independently sampled
terrain/roof profiles. At least 90% of columns must have plausible height data;
spikes, excessive roughness and incompatible foundations are rejected using the
existing building-profile checks. Existing mapped buildings are excluded from
this missing-building pass. Roof shapes are 2.5D raster profiles, not exact
architectural meshes. Terrain and surface hashes and transformation provenance
remain in the output report.

Printed wall heights take precedence and are rounded up at one-metre voxel
resolution. Without a printed height, retaining-wall relief uses nearby terrain
with a six-block upper bound. Other walls use a one-block preview height. Rocks
use a one/two-block relief estimate constrained to the measured footprint. The
planter uses a one-block rim and generic vegetation. These unknown heights and
unspecified materials are recorded as estimates, not planning specifications.

## World composition and validation

The generator excludes excessive water, road/through-path and existing-building
overlap. It protects retained Wicker/Oblivion physical and clearance cells.
Candidates must remain inside existing world chunks. Only air cells can receive
new blocks; building and planter objects are withheld as a whole if any cell
collides. Rocks/walls may retain safe cells with blocked cells recorded.

```bash
python -m voxel_mapper.park_details \
  --source-output /absolute/path/verified-v4-world \
  --park-output /absolute/path/alton-full-park \
  --planning-cache /absolute/path/planning-sources \
  --datum-grid /absolute/path/uk_os_OSTN15_NTv2_OSGBtoETRS.tif \
  --output /absolute/path/park-details-v5
```

The initial V5 export adds 235 blocks across 16 objects: nine rock groups, one
retaining wall, three other wall sections, one planter and two buildings. Every
cell of touched chunk sections and total chunk coverage passes Bedrock readback
across 15 touched chunks. The solid block delta equals the 235 overlay records:
no existing solid blocks or paving cells were replaced. Ride layouts remain
unchanged. All 306 tests pass.

The preview renders added blocks and retained ground from the exported world,
with simplified colours and other raised structures hidden for clarity. It is
not an in-game screenshot. Geometry and source dates remain provisional.

## V6 wall continuation

A further native-page review of 23 wall candidates added a stone gabion wall
and a stone retaining-wall section. The retaining-wall phrase is split across
three contiguous rotated CAD spans; their original text and coordinates are
retained alongside the reviewed combined phrase. Separate wall material words
only apply inside the reviewed footprint; conflicting or nearby paving labels
do not select the wall material. Wall heights remain estimates.

The wider building assessment checked 65 distinct in-boundary footprints: 28
already mapped, 34 without a reliable surface profile and three previously
reviewed profiles (including the excluded ride platform). It found no additional
reliable buildings for this pass.

V6 preserves all 235 V5 detail blocks and adds ten blocks across the two wall
sections. The cumulative 245 blocks across 18 objects pass full touched-section
and chunk-coverage readback across 18 chunks. All 307 tests pass.
Validation: `evidence/park-details-v6-validation.json`.
