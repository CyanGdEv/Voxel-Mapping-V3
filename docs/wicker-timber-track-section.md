# Wicker Man timber track: reference style and first constructed section

The first constructed section covers **98.903 m**, from the source **HP1 → LP1 → HP2** crosshairs (source chainages 232.749–331.652 m). The retained full plan centreline is 773.568 m; the other sections remain coloured plan guides. This is a visual coaster reconstruction, not an operable Minecraft ride.

## Reference analysis

The ten user-supplied Towers Magic screenshots guide appearance. Their lighting, textures and likely custom ride assets prevent reliable identification of every original block. The following are vanilla approximations, not claims about the reference world's exact inventory:

| Reference feature | Construction used |
| --- | --- |
| Pale timber uprights and repeating joints | Oak fences between full oak-log nodes |
| Horizontal timber frame tiers | Oak logs with X/Z axes, at estimated 3 m vertical intervals |
| Diagonal lattice bracing | Stepped oak fence diagonals in both directions |
| Dark running strips / sleepers | Dark-oak planks and bottom slabs; spruce ties underneath |
| Light side maintenance walkway | Oak top/bottom slabs |
| Thin side railings | Oak fences outside running clearance |
| Square joint/end details | Outward-facing oak trapdoors |
| Low foundation pads | Stone-brick display pads on retained ground |

The pictured dark rail and train models may require a resource pack or ride mod; they are not identified or reproduced as functional rail equipment. The effigy, fire effects, buildings and banners are reference context and are not newly constructed in this track phase.

## Geometry and height evidence

The exact retained source-markings file is checksum pinned. Its original faceted centreline and **73,495 brown support-outline segments** stay in the current nominal source frame; no OSM route ordering or old OSM branch windows are substituted. Crosshairs are replayed from the original landscape PDF (SHA beginning `1c5dc5`), including their printed labels and vector sequences.

| Source control | Printed level, m | Distance from crosshair to plan centreline, m |
| --- | ---: | ---: |
| HP1 | 201.0 | 0.0145 |
| LP1 | 191.7 | 0.0188 |
| HP2 | 193.4 | 0.0129 |

These are related-drawing checks, not survey accuracy. Printed levels are conditionally used as running-surface heights in the existing ODN display. Smoothstep interpolation holds zero slope at each selected extremum without overshooting the printed levels; intermediate vertical geometry is estimated. Heights are quantized to half blocks. Banking is unmeasured and held at zero. Exact running-rail sections, transition radii and structural timber sizes remain unresolved.

Polygonizing the original brown linework recovers closed post symbols. The selected section contains **94 eligible symbols** in the configured 0.2–0.4 m² symbol-area band; **41 opposite-side pairs** are placed using their source centroids and a maximum 0.8 m chainage difference. Symbol dimensions are not accepted footing or timber dimensions. The generated frames use those paired positions, rather than a regular guessed horizontal spacing.

The running strip has **272 cardinally connected columns**, at most **0.5 m** neighbouring height difference, and **816 native air samples** check three whole blocks above it. All 41 paired support frames are constructed; 465 upright cells are checked for continuous log/fence/pad occupancy. The source symbols sit mostly on blue/brown 2D guide cells; these underlying guide materials remain unchanged. Actual paving and other land-use cells are excluded from new post bases. Existing buildings, queue, maintenance shell, terrain and all previous structures remain intact.

## Validation and replay

Forty-three focused tests cover interpolation/extrema/extrapolation rejection, collapse of sub-metre samples into single native surfaces, material legality, support continuity, paving refusal, running-strip connectivity, cancellation and the existing building pipeline. Native export checks all written blocks/unwritten air; additional readback verifies the 272 running surfaces and 816 clearance samples. Archive CRC/file checks and cold reopen cover all 187 chunks. Minecraft import/gameplay, functional trains, structural engineering and physical survey registration remain unverified.

```sh
python -m voxel_mapper.timber_track_world \
  --base-directory maintenance-built \
  --markings-path source-markings.json \
  --pdf-path original-landscape.pdf \
  --output fresh-track-world \
  --allow-provisional
```

The distinct level name is `Wicker TIMBER TRACK - HP1 LP1 HP2 first section`. The existing maintenance-built archive is not overwritten. The report retains selected source controls, each paired symbol's geometry hash, constructed/withheld frame receipts, all track samples, the style palette and assumptions. No model training labels or new survey acceptance are produced.
