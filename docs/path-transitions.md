# Path-attached slabs and stairs

V17 fixes detached stair strips by operating on the actual native paving footprint.
Four provisional garden stair traces are restored to their original V15 cells;
V16's seven other garden paths, walls and green barriers remain. Future garden
extraction withholds those unattached stair traces; native path smoothing supplies
transitions instead.

`reconstruction.garden_surfaces.path_transitions` is park-independent. Its input
is a paved-cell field with walking heights, material families and route tangents.
At an isolated one-block rise, a bottom slab is placed on the lower paving block,
creating a half-height transition to the higher block. Sustained climbs replace
paving blocks with stairs, including a terminal landing stair. Stair backs face
an actual higher path neighbour in the route direction. Descending runs retain
the uphill orientation. Cross-slope neighbours cannot turn stairs across the route.
Existing half-step surfaces remain, and missing path cells are not bridged by guess.

The retained-world adapter obtains path corridors from OSM and the remaining
reviewed garden paths. It samples the actual topmost paved blocks rather than
creating a separate DTM stair ribbon. Changes remain within those paved columns.
No grass-side stair strips, new support towers or terrain regrade are generated.
Slabs keep the lower full block as their foundation; stairs replace the existing
paving block. Stone, stone-brick, brick and sandstone families preserve finish
proxies. Native material families without a supported partial-block equivalent
are left untouched.

Protected foliage, water/bed columns, ride structure, rider air and V16 wall/barrier
cells cannot be changed. Native changed-section readback includes unchanged cells.
Physical validation checks slab foundations, actual route membership and stair
alignment to neighbouring path elevations. Rises greater than one metre and
existing missing paving remain unresolved; this is a half-step correction to
retained elevations, not an engineered grading survey.

```sh
python -m voxel_mapper.path_smoothing \
  --source park-gardens-v16-final --baseline park-foliage-v15 \
  --output park-paths-v17 --osm recovery/park-osm.json \
  --boundary recovery/boundary-local.json \
  --grid recovery/uk_os_OSTN15_NTv2_OSGBtoETRS.tif
```

The Alton adapter requires retained foliage, ride-clearance and water-column
protection files from the reproducible evidence workspace. The core transition
function has no Alton names or source dependencies. Tests cover isolated rises,
continuous ascending/descending runs, terminal landings, half-step preservation,
missing paving and cross-slope orientation.

Existing top-slab landings are filled to full blocks at the same walking height,
removing the empty half-block underneath. Existing bottom slabs and stairs are
not stacked with extra transition blocks. A stair flight starts with an added
half-step on its lower approach, avoiding a dip below the flat approaching path.
