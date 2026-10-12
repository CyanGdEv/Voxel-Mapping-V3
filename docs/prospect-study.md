# Prospect Tower relative reconstruction study

This pass produces importable **isolated Bedrock review worlds**, rather than placing an uncertain tower in the park. The normal study uses one block per source metre. The enlarged study uses four blocks per source metre and is explicitly 4:1, not a park-scale reconstruction. Both use an artificial flat platform and local study zero; neither has a geographic CRS or ODN ground level.

The review package includes a side-by-side block geometry preview.

The image is a renderer preview, not an in-game screenshot. Bar/pane connections in Bedrock can differ from the schematic renderer.

## What is used

The hash-pinned extraction now retains **63 floor member profiles**: 23 ground floor, 24 first floor and 16 second floor. Each storey uses its own source footprints. Six reviewed elevation references establish relative balcony and roof levels. New official sheets provide sections, the proposed colour scheme, balcony railing details and location/block plans. The source review records URL, hash and PDF rotation for every acquired document.

Proposed AL3.41 colours are Pugin Red, Cornish Clay and Grass Green railings. Minecraft approximations use red terracotta, sandstone, sandstone walls/slabs and green panes. Cast-iron roof members use iron bars, whose native grey does not match Pugin Red. These palettes are proxies, not literal building materials or verified present-day finishes.

The study has three storeys, two balcony rings, thin external columns, pointed-arch proxies, 44 spiral tread proxies, green railing proxies, a faceted tapering roof and a finial proxy. Balcony envelopes, arch curves, intermediate roof radii, railing/tread dimensions and some vertical assignments are estimated. Carved tracery, full glazing, decorative castings and accurate accessibility are unfinished. The normal block grid merges small members and details.

## Placement remains withheld

AL3.42's Skyride station outline provides a useful correspondence with retained OSM way 70684295. A preliminary north-up, printed-scale centroid translation places the tower approximately 3.74 m from NHLE's listing reference. That is not an independent registration test, and a listing reference is not a surveyed tower centre. OSM way 70689521's rectangular footprint is not adopted as the actual tower shape. We still need independent placement checks and a defensible base elevation before composing into the park.

AL3.42, AL3.43 and the roof drawing have PDF page rotation of 90 degrees. Raw drawing coordinates are not displayed coordinates; use `page.rotation_matrix` when reviewing their vectors.

## Modular improvements

Architectural components can choose an explicitly evidenced `raster_rule: centroid` for small solid member footprints, avoiding unnecessary multi-cell widening of thin columns. Larger footprints and holes retain positive-overlap rasterization. An explicitly evidenced integer `voxel_priority` resolves material aliasing within a feature. Equal priorities with different materials at the highest surviving level remain withheld. This does not permit overwriting existing-world collisions. Priorities are resolved independently of component ordering and remain subject to the feature budget.

Sandstone, sandstone walls, stone-brick walls and brick walls join the supported palette. Sandstone wall blocks were verified in native export. The named study builder is deliberately separate from park composition.

## Reproduce

```bash
python scripts/extract_prospect_storeys.py --pdf-directory retained-prospect-pdfs --output new-upper-profiles.json
python -m voxel_mapper.reconstruction.prospect --model-scale 1 --output new-study-1
python -m voxel_mapper.reconstruction.prospect --model-scale 4 --output new-study-4
```

The source profile extraction requires the exact retained hashes for AL3.03 Rev B and AL3.04 Rev B. The builder uses packaged profiles and does not require live council downloads. Runtime dependencies cover extraction and world generation; the optional preview script additionally requires Matplotlib.

Both exported LevelDB worlds are reopened and every written block and unwritten air cell is compared against the planned output before packaging. This is native data validation, not in-game visual approval. The deliverable includes both worlds, component/quality reports and this preview. Existing park terrain, paths, ride geometry and water are untouched.
