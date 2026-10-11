# Full courtyard ground-floor layout study

V8 expands the isolated north-range study into four courtyard ranges, two rear
annexes and 28 named room areas. The existing CTD AL05 ground-floor plan is
checksum- and raster-pinned. All 679 V7 north-range native cells and their exact
component solids are retained. No glass is generated.

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

The builder revalidates the source PDFs and reproduces the north wing before
expanding it. It writes an OBJ in the source Z-up frame, a coloured GLB in standard
Y-up metres, the room inventory, model/audit JSON and an isolated Bedrock world.
GLB mesh names preserve each wall, partition and roof component for inspection
or editing in Blender/Cycles. Roof-hidden rendering does not remove the world roof.

## Remaining work

This completes a whole-complex ground-floor **layout preview**, not a surveyed
complete building. Upper floors, internal stairs, tower profiles/heights, detailed
service cubicles and furnishings remain absent. Other range elevation openings,
annex access correspondence and roof junctions need source review. Rooms labelled
as unlabelled/service spaces have descriptive display names, not established uses.
Components are individually watertight, but the overlapping assembly is not a
boolean-unioned manifold. Park-world placement remains disabled.
