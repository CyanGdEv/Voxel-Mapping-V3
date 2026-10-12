# Boundary V3 shop review

In-game feedback still showed openings near eaves and gable corners. The
previous column-only join test was insufficient: the retained 4:1 geometry
allows outside air to reach the interior through the staircase roof. The
previous 1:1 geometry passes that air test; the screenshots alone do not
establish which exported revision was loaded.

The new optional `--closed` mode derives the complete wall boundary from the
retained floor outline, fills its columns up to the main roof and keeps the
declared doorway apertures clear. It adds vertical risers at roof steps so
adjacent samples meet along faces. These are estimated voxel display closures;
source meshes, physical construction thickness, orientation and registration
remain unchanged and unresolved. The canopy/front fascia still use the
retained northeast-height hypothesis.

Validation floods six-neighbour air from outside a bounded box. The floor and
door openings are temporarily sealed for this test only. Every interior air
cell inside the footprint and below the roof is checked for outside reachability.
The actual world preserves all declared door-column air cells. This is a voxel
closure test, not physical water tightness or a player-movement simulation.

At 1:1, 52 boundary columns are checked, with 28 added wall cells and 64 roof
riser cells. The interior test checks 532 air cells, with zero reachable from
outside. At 4:1, 220 boundary columns receive 225 added wall cells and 1,904
roof riser cells. All 57,412 checked interior air cells are unreachable from
outside when doors are temporarily sealed. The final displayed assemblies
contain 468 and 8,953 cells respectively, including the provisional canopy.

```sh
python scripts/build_wicker_shop_study.py --pdf-directory shop-pdfs \
  --output shop-boundary-v3 --closed --preview
```

Import the worlds named **Wicker Shop BOUNDARY V3 REVIEW**, in either 1:1 or
4:1. Separate revision names help distinguish them from the earlier surface
and joined studies. Both exports undergo native cold-reopen block/air checks.
Tests reproduce the previous 4:1 leak, detect deliberately removed wall and
roof cells, and check closure and preserved door apertures at both scales.
No geographic park placement is added.
