# Full courtyard ground-floor layout study

V8 expands the isolated north-range study into four courtyard ranges, two rear
annexes and 28 named room areas. The existing CTD AL05 ground-floor plan is
checksum- and raster-pinned. All 679 V7 north-range native cells and their exact
component solids are retained. No glass is generated.

V9 makes slab roofs the default, including the north range. Bottom/top wooden
slabs form half-height courses; plank risers seal the underside of height changes.
All 3,801 V8 non-roof cells remain unchanged. Courses that meet retained masonry
are raised locally to prevent overlaps and open roof edges. This supersedes the
V8 claim that north roof cells remain unchanged. The walls and room layout remain
the same; no wooden roof stairs are exported. Use `--roof-style stairs` to reproduce
the V8 roof style.

V10 (`--facade-sources /path/to/pdfs`) opens the blocked lobby connection by
cutting only its temporary north joining-plane cap. The corresponding exact
solid and two standing native cells are updated together. The west courtyard
façade now uses fourteen manually reviewed AL08 opening silhouettes: five lower
windows, five doors, three upper windows and archway 2. Two dormer windows remain
withheld because they require new roof openings and dormer assemblies.

AL08's individual view caption is 1:50, although its title block says 1:100.
The generator pins the per-view scale and full source render. Its shared north
junction anchor is an explicit correspondence hypothesis; it does not certify
survey registration. Source elevation keys also correct the provisional range
names: the left plan strip containing archway 1 is south; the upper strip
containing archway 2 is west. The plan footprint is unchanged.

The remaining south façade requires a stepped wall/tower profile; the east
façade requires review of the sloping floor datum and tower/boarded-opening
correspondence. Their existing source views are pinned in the V10 review package.

The new layout is an explicit manual raster-sampled hypothesis. Wall centre-lines,
room rectangles and plan doorway cuts are approximations, not accepted original
PDF vector geometry. New heights, wall thicknesses, window sills/heads, symmetric
roof pitches, joining-plane caps and native overlap rules are display assumptions.
The plan's north arrow is not used to assert a geographic registration.

Three additional courtyard-to-exterior passages and the north-arch annex exit are
checked for standing air in native half-block occupancy. Narrow doors reserve a
one-metre native column, while the exact mesh retains sampled plan widths. One
south-lobby doorway remains obstructed by a retained north joining-plane cap;
this is reported rather than silently changing the reviewed previous model.

## Reproduce

Place the three checksum-named source PDFs required by the north-wing recipe in
one folder, then run:

```bash
python scripts/build_courtyard_layout_study.py --sources /path/to/pdfs --output /path/to/fresh-output
python scripts/render_courtyard_layout_study.py --model /path/to/fresh-output/courtyard-model.json --output /path/to/fresh-output/Mutiny_Full_Courtyard_V8.png
```

Add `--facade-sources` to the build command to include V10's west façade and
lobby connection. The source folder must contain the AL08 PDF named by its SHA.

The builder revalidates the source PDFs and reproduces the north wing before
expanding it. It writes an OBJ in the source Z-up frame, a coloured GLB in standard
Y-up metres, the room inventory, model/audit JSON and an isolated Bedrock world.
GLB mesh names preserve each wall, partition and native slab course for inspection
or editing in Blender/Cycles. Roof-hidden rendering does not remove the world roof.

## Remaining work

This completes a whole-complex ground-floor **layout preview**, not a surveyed
complete building. Upper floors, internal stairs, tower profiles/heights, detailed
service cubicles and furnishings remain absent. Other range elevation openings,
annex access correspondence and roof junctions need source review. Rooms labelled
as unlabelled/service spaces have descriptive display names, not established uses.
Components are individually watertight, but the overlapping assembly is not a
boolean-unioned manifold. Park-world placement remains disabled.
