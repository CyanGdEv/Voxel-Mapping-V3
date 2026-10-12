V19 adds four bounded garden bridge crossings to the V18 full park: White
Bridge, Miniature Bridge, a western crossing and the cascade stream crossing.
The park-independent bridge geometry module emits decks, outside railings,
level/slab/stair approaches and explicit clearance cells. White Bridge has a
single flattened arch proxy; Miniature Bridge uses a three-span side-rib proxy.

Planning PDFs from SMD/2013/1105 are hash checked. Miniature Bridge retains
the Upper Gardens vector edges (paths 12046, 12047 and 16900), with a measured
inner width of 1.19075 m at the retained sheet scale. Its physical outline is
about 1.6 m wide. The other bridge axes come from retained OSM and widths are
estimates. The Historic England records 1037870 and 1037878 establish White
Bridge's ashlar and white balustrade, and Miniature Bridge's cast iron,
three arches and stone piers. They do not establish dimensions or elevations.

Absolute drawing alignment remains provisional. Miniature's surveyed deck
label is 149.5 m ODN; native bridge walking level uses 150 m ODN to join the
existing banks. White Bridge uses a 177 m ODN estimate from nearby drawing
levels, with inferred ramps to the lower native roads. Other crossing levels
are estimated from native banks. Archetypal shapes, slab quantization, railing
spacing and deck finishes remain visual proxies. Fine carved/iron detail and
current condition are not verified.

Three reviewed variable-width paving polygons add 353 surface columns:
90 at the White Bridge tarmac approach, 251 in the bridge/dam tarmac corridor,
and 12 at its stone-paving entry. The requested palettes provide gray concrete
for asphalt and a deterministic stone/stone-brick/cobblestone mix for stone.
Curved boundaries are sampled traces rather than exact CAD faces. Materials
are constrained to these local regions; brick wall labels are not floor evidence.
Existing slabs/stairs are preserved during material-only patching; 49 blocked
or partial surface columns are reported rather than flattened.

Water and bed cells are never replaced. Wet approach columns extend the deck
without filling the water. Ornamental rib collisions are withheld. Fifteen
known garden railing cells intersecting the new walking corridors are moved
to outside rail routes, retaining the green-pane colour proxy. Rail relocation
requires the supplied earlier garden overlay and a matching native railing
block; it cannot override other protected material.

Run `scripts/build_garden_bridges.py` with `--source`, `--output`, `--pdfs`,
`--osm`, `--grid` and `--rail-overlay`. The source is a native park directory
with its quality report/configuration; the railing overlay supplies reviewed
cell provenance. The OSTN15 datum grid and all four PDFs are checksum checked.

All 403 local tests pass. The native export verifies every cell of changed
sections across 25 chunks and total world chunk coverage. Separate readback
checks confirm all four walking profiles are cardinally connected, with no
rise exceeding a block and two blocks of headroom. No original water, gravel
beds, leaves, fence trunks or logs were overwritten. The remaining chunks are
copied from V18, including Prospect Tower. No in-game visual fidelity test is
claimed. See `evidence/garden-bridges-v19-validation.json` for checksums and
visit coordinates; the in-game spawn remains beside Prospect Tower.

The builder now repeats a native walking audit after reopening the composed
world and before writing the importable package. Each retained walking column
must have a supported full block, slab or stair at its declared height and
two air blocks overhead. The cardinal-neighbour graph must be one component;
adjacent rises above one block fail. Final composition is checked so later
features cannot silently obstruct an earlier bridge. A failure retains the
diagnostic world directory but produces no `park.mcworld`.
Results are embedded under `semantic_verification` in new build reports.

Existing V19 packages can be extracted and checked without changing blocks:

```sh
python -m voxel_mapper.reconstruction.walking_audit --world EXTRACTED_V19_WORLD
```

The replay of the saved V19 package passes all four profiles (299 columns).
See `evidence/garden-bridges-v19-walking-audit.json` for the package hash and
per-bridge results. This is a check of the existing package, not a new world
generation. The original 403-test validation above belongs to the original
V19 build.

Fractional input deck elevations now report the actual integer top of the
generated full block; previously the walking profile retained the unquantized
requested height. The existing four V19 deck inputs are integer elevations.
Slab tops are checked explicitly. Stairs use their taller tread envelope;
player movement, stair-facing transitions, absolute survey alignment and
in-game visual fidelity remain unverified.
