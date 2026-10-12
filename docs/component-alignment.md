# Component-level alignment review

A PDF fill can contain several disconnected water bodies or building outlines.
Comparing that compound paint record to one mapped object produces misleading
shape scores. `drawing-components-v1` separates Polygon members of each retained
MultiPolygon, keeps interior holes and merges geometrically identical parts.
Original geometry records remain available. Every component lists its parent
candidate IDs and member indexes, source page and parent extraction contract.
Matching recomputes these components from the retained parent page rather than
trusting supplied member references.

```sh
python -m voxel_mapper.drawing_components \
  --corpus work/corpus \
  --candidates work/drawing-geometry/geometry-candidates.jsonl \
  --output work/drawing-components
```

The parent feed must include complete retained pages, grouped by PDF/page and
extraction contract. PDFs and exact parent records are checked before output.
Limits remain 2.5 million output records, 10,000 pages, 10,000 parent records and
20,000 components per page. Parent and paint-reference budgets prevent unbounded
provenance. Curved-parent approximation bounds are retained conservatively;
decomposition neither improves their precision nor assigns physical semantics.

Enable `drawing_components` alongside `drawing_geometry` in a park job to use
component polygons for matching, boundary hypotheses and sheet alignment:

```json
"drawing_geometry": {"enabled": true},
"drawing_components": {"enabled": true}
```

Use a fresh matching/alignment output directory when switching feeds. Component
exports remain withheld until explicit parent/component semantic review is
implemented; a component match or successful geometric fit cannot generate
world geometry. Independent registration controls/checkpoints and current state,
reuse, dimensions and material evidence remain required.

`survey-context-v1` also distinguishes a national-grid declaration from an
arbitrary, local or unscaled survey grid. Anchor audit v3 withholds coordinate
fits when such restrictions occur, even if OSGB36 or OSTN15 appears nearby.
Printed coordinate values and application locations are not measured attachment
points. A national-grid declaration alone never verifies registration.

## Park-domain mapped comparison references

`python -m voxel_mapper.physical_references` builds a checksum-pinned reference
feed from retained OSM building and water polygons, including unnamed objects.
Supply `--osm`, `--boundary`, `--boundary-crs`, `--osm-sha256`,
`--boundary-sha256` and `--output`. The boundary must use a projected metre CRS.
Only complete footprints covered by the actual park polygon are retained;
crossing footprints are excluded, never clipped into artificial comparison
shapes. Paths, ride centre lines and other nonpolygon records are excluded.
The selector accepts up to 100,000 source features and 5,000 reference polygons.

Use the resulting `physical-references.geojson` with reference CRS `EPSG:4326`
and the retained park CRS as the matching target. These references expand the
comparison pool; they establish neither surveyed control points nor current
as-built identity. Matching v3 publishes completed feeds atomically and checks
association row counts before issuing its receipt.
