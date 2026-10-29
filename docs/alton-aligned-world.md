# Alton Towers aligned landscape world

The exporter produces a native Bedrock `.mcworld` in one British National Grid / ODN frame. It combines public OSM, georeferenced aerial appearance, retained planning geometry, matched terrain/surface rasters and classified raw LiDAR returns. The existing detailed Wicker Man buildings, track and dark-oak fence supports are registered into the landscape. Other rides are mapped locations; their track and mechanisms are not reconstructed.

The delivered draft covers a 2,080 × 1,120 m rectangle around the main park, including adjacent landscape and car parks. The main OSM park polygon covers approximately 1.17 km². There are 9,100 chunks and 19,156,041 occupied blocks. Minecraft X increases east, Z increases south; the BNG origin is E406896, N342880 and the vertical offset is −31 blocks. Spawn is at Towers Street, `[419, 154, -787]`.

## Layer composition

- OSM is projected using a pinned OSTN15 operation, without a lower-accuracy fallback. Polygon holes survive rasterisation. Narrow corridors retain mapped/default width provenance and continue under canopy.
- Esri World Imagery is sampled in its actual returned EPSG:3857 extent. RGB controls appearance inside paving; conservative infill extends at most four metres from mapped visible paving and requires a low, colour-compatible surface. Buildings and water are excluded. Visible low grass islands are retained. This is image interpretation, not independent boundary validation.
- Both EA rasters and the raw cloud are survey `P_10682`, 5 January 2022, native EPSG:27700 / ODN. Of 98,342,681 scanned returns, 11,033,630 eligible returns lie in the landscape rectangle. Withheld and synthetic flags are explicitly converted to Boolean masks. Class 6 supplies roof samples; classes 3–5 supply observed foliage bins. Missing LiDAR ground is not treated as low vegetation.
- Eighteen retained historical planning path/surface traces supplement OSM. Wicker Man keeps its planning-derived detail through inverse nearest-cell resampling of its pinned nominal-plan-to-BNG affine. Roof slabs remain slabs. Diagnostic plan wool is omitted. Retained riding clearances override foliage; actual track/support blocks are replayed last.
- The 249 other building footprints become hollow shells with half-block slab roofs. Classified roof returns cover 212; 37 use estimated OSM/default heights. Missing roof samples are filled only from observations inside the same footprint. Mapped water uses terrain-estimated levels and shallow visual beds. Bridge decks remain separate from water and terrain underneath.

## Material strength

`appearance_palettes.py` contains exactly two recipes each for brick and asphalt, plus one stone mix. Brick strength follows normalised redness; asphalt strength follows darkness. Shadowed or occluded samples use the nearest visible sample in the same family. This choice never converts a roof, tree or lake to paving. Geographic hashes make constituent choices and three-metre tonal patches repeatable across chunk and crop boundaries.

Strong brick uses terracotta, mud brick, oak and granite. Faded brick uses more mud brick/oak and less terracotta. Strong asphalt uses black concrete with grey wool texture; faded asphalt uses grey concrete with grey wool. Standard stone uses stone bricks, stone and cobblestone. Grey appearance wool is separate from diagnostic planning wool in the native material registry.

## Rebuild

Install the `alignedworld` optional dependencies. Retain the Nominatim main-park boundary, the exact existing Wicker detail, and the source receipts. Acquisition and raw-cloud gridding are explicit operations:

```sh
python scripts/acquire_alton_world_inputs.py --work WORK --location location.json
python scripts/grid_alton_world_cloud.py --work WORK --archive SK0540.zip --source-receipt cloud-source-receipt.json
python -m voxel_mapper.alton_aligned_world --work WORK --wicker RETAINED_WICKER --output OUTPUT --prepare-only
python -m voxel_mapper.alton_aligned_world --work WORK --wicker RETAINED_WICKER --output OUTPUT
```

The cloud source receipt must contain the official download URL and archive SHA256. The known tile entry and header are checked. The world exporter verifies the image, raster, point-grid and OSTN15 checksums and requires the pinned retained Wicker voxel file. A different detail build needs an updated registration. Existing native output is never overwritten. Large source inputs and generated worlds are retained as task artifacts, outside Git.

The native writer commits one chunk at a time without generating a park-sized SQLite/JSONL intermediate. It reopens all chunks and compares every material and declared state, all air in the rendered envelope, and unwritten section air. The delivered run compared 53,073,408 envelope cells. ZIP CRC, native file presence, spawn headroom and metadata types are also checked. Relevant material, terrain/water/roof, native exporter and transport tests accompany the change.

## Accuracy and scope

This is a multi-date landscape draft. Common coordinates and exact native replay do not prove physical registration. OSM and aerial offsets, historical proposals, winter foliage, estimated shell facades, inferred trunks/species and metre quantisation remain visible limitations. Lake beds are not bathymetry; foundations are artificial. Other rides are not detailed models. No Minecraft client import or visual-fidelity test is claimed.

The `.mcworld` embeds georeferencing, source hashes/URLs/dates, waypoints, the full retained Wicker detail report and attribution. The overview and material swatches are review renders, not Minecraft screenshots. Source attribution: OpenStreetMap contributors (ODbL-1.0), Environment Agency (OGL-UK-3.0), Esri World Imagery/providers and Staffordshire Moorlands public planning applications.
