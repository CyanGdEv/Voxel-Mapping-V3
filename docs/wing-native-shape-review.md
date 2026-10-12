# Native shapes for isolated wing reviews

The full-block Mutiny preview loses low sills and thin masonry at block-centre samples and makes the roof visually heavy. The opt-in `--native-shapes` export fits complete facade cell profiles to native bottom/top slabs and straight upright/inverted stairs. Glazing is disabled following user feedback. It keeps one world block per source metre and leaves the exact reviewed wall/roof mesh unchanged. Default exports retain their existing sampler.

```bash
python scripts/build_local_wing_review.py \
  --recipe evidence/mutiny-north-wing-window-cycle-review-seed.json \
  --sources /path/to/checksum-named-pdfs \
  --output /path/to/fresh-review \
  --isolated-world --native-shapes
```

Only the bounded, unplaced, reviewed planar facade and exact two-slope roof recipe are supported. The sampler checks that the original triangles agree with the aperture profile; it rejects edited meshes, invalid sources, unsupported standing passages, work-budget exhaustion and roof profile gaps. It does not silently reconstruct an unrelated model.

Facade fitting minimizes missing plus excess profile area against each complete source cell. Door and arch centre columns retain two full air blocks; this can enlarge drawn clearance and is explicitly a display quantization. Disconnected sampled masonry below the upper facade is recorded and withheld rather than supported with invented piers. This removes the isolated block at local `(18, 0, 0)` in Mutiny while preserving its source masonry in the exact mesh.

The roof fits top surfaces at two stations per depth column. Rising/falling columns use correctly oriented stairs where their rise is at least half a metre. Adjacent column profiles must touch; edge contact does not establish a watertight roof shell. Roof top Hausdorff error is checked against the half-cell diagonal, `sqrt(0.5² + 0.5²)` metres, not a half-metre distance claim. The earlier V2 glazing proxy was rejected by the user and has been removed from the sampler. Window voids remain open.

The historical V2 Mutiny result is in `evidence/mutiny-wing-native-shape-audit.json`:

| Check | Previous full blocks | Native shapes V2 |
| --- | ---: | ---: |
| Review surface cells | 280 | 311 |
| Roof display volume, m³ | 192 | 144 |
| Missing facade profile area, m² | 12.781 | 8.390 |
| Excess facade profile area, m² | 5.568 | 6.427 |

The area tradeoff is explicit: missing masonry decreases while excess masonry increases. Total facade symmetric difference decreases from 18.349 to 14.817 m². There are 102 masonry cells, 192 roof stair cells and 17 glass proxy cells. Roof top profile error is 0.527 m within the 0.707 m allowance. Cold native readback verifies 5,711 composed blocks and all unwritten air in eight chunks, including stair direction and inverted states. The source model bytes remain unchanged.

For a comparison image, run `scripts/render_wing_native_shapes.py --before OLD/voxels.jsonl --after NEW/voxels.jsonl --output comparison.png`. It draws exposed faces of exact native half-cell occupancy, with illustrative colours and transparency. It is an export-shape render, not an in-game screenshot or acceptance of visual fidelity.

Outer/rear/end walls, interiors, junctions, roof cross-date correspondence, physical aperture extents and park registration remain unresolved. This creates a fresh isolated review world and adds no blocks to the retained park.

V3 removes all 17 glass proxy blocks (294 review cells, 5,694 composed blocks). The user manually repaired the arch in-game; a single screenshot does not specify every changed block. That correction is pending block-level reconciliation and is not claimed as reproduced by this export.


## V4 arch support correction

In-game review exposed a defect in V2/V3: the right pier at local x=18 lost its y=1 connector during independent area fitting. Cleanup then withheld its grounded y=0 block, joining the arch to the neighbouring opening. The grounded source masonry was not an unwanted floating block.

V4 subtracts every opening projection over standing height from each adjacent support column. It requires at least 0.125 m of continuous source masonry before fitting a connected native half-width strip. This threshold is an explicit display policy, not a measured pier width. Unsupported or out-of-facade piers reject instead of being invented. Required strip fitting retains the original area objective among compatible native shapes. Budget exhaustion withholds the complete result.

The real left/right continuous source cores within their native columns are 0.551/0.212 m. The right y=1 air cell becomes a west-facing upright stone-brick stair and its grounded y=0 block remains connected to the head. The 0.5 m native strip encroaches on the neighbouring window, so this is a disclosed quantization tradeoff. Both support strips and their head contacts are verified after cleanup and roof composition. Crown clearance is checked for rising-then-falling order around the source apex; the real half-column clearances are [2, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2] metres.

The fresh export has 296 review cells, including 104 masonry and 192 roof cells, and 5,696 composed native blocks in eight chunks. No glass is generated. Original mesh bytes remain unchanged. It has passed native readback; confirmation in Minecraft remains pending. This repairs the generator defect and does not claim recovery of every manual edit from a screenshot. Evidence: `evidence/mutiny-arch-support-audit.json`.
