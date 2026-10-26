# Conditional Wicker floor, plinth and grading prototype

A separate Bedrock prototype now models the shop, station and maintenance floor proposals rather than draping their complete footprints over terrain. It uses the retained Wicker/courtyard XY frame and keeps the earlier aligned world unchanged. The new world is named **Wicker conditional floor and path-grading prototype**.

## Datum and floor representation

The original plan supplies Shop FFL 182.5 and Station/Maintenance FFL 183.25. A native-text scan of retained drawings found OS benchmark references (178.90 m) but no explicit tie from these proposed floor levels to ODN. This scan is not an exhaustive OCR or survey-datum investigation. The builder therefore requires `--assume-plan-ffl-odn` and embeds that unresolved assumption in the package; it does not mark the datum verified.

| Source floor proposal | Printed FFL | Preview walking-surface level under ODN assumption | Quantization |
| --- | ---: | ---: | ---: |
| Shop | 182.50 | 182 | -0.50 m |
| Station | 183.25 | 183 | -0.25 m |
| Maintenance | 183.25 | 183 | -0.25 m |

These are full one-metre floor blocks. Their block base is one metre below the walking surface, avoiding an extra-block height error. Source decimals are retained even though this coarse preview cannot represent quarter-metre floors. This is not a final architectural floor specification.

The source footprints contain 217 shop, 168 station and 298 maintenance cell samples. Two station/maintenance cells overlap at the same printed level; they are merged while retaining both source identities. Different source levels are rejected even if whole-block quantization would hide their disagreement. There are **681 unique floor cells**.

Floor interiors use neutral stone bricks; existing source marking colours remain at their XY locations on the new surfaces. Raised areas receive **254 provisional solid stone-brick plinth blocks**, and terrain is cut inside footprints where the floor proposal is lower. Solid plinths are display supports, not measured footings, verified structural design or a confirmed undercroft layout. There are no reconstructed exterior walls, roofs or complete buildings.

## Path-grading proposal

A cut-only proposal within one block could not remove every source-path discontinuity. A bounded linear programme instead minimizes total absolute cut/fill changes, with every affected cell limited to plus/minus one block and every orthogonal candidate path-neighbour difference limited to one block. A tiny secondary cost prefers cuts in exact ties. The solver must finish successfully and return integral block heights; timeout, infeasibility or excess budgets refuse the export.

The actual proposal changes **17 path cells: 11 cuts and 6 fills**, all one block. The candidate path network's two-block neighbour pairs fall from **17 to zero**. This is an estimated grading alternative, not a reconstruction of documented finished grades. It does not invent named stairs or doorways. Existing building footprints, ride guides and edging columns are excluded from the grading variables.

Floor-perimeter access is audited separately. **Three two-block floor/path perimeter differences remain**. These are perimeter samples, not three identified entrances. Door positions, entry stairs and accessible routes remain unresolved; this prototype is not a verified navigable world. No Minecraft client import or gameplay test has been performed.

## Preservation and native checks

All 12,602 original ground-feature materials and 4,178 plan-marking XY positions are retained; height changes are explicit. Existing 1,213 edging blocks retain their source columns. The original geographic world package remains byte-for-byte unchanged. Courtyard dimensions and map registration are not refitted, stretched or expanded by this stage.

Actual native saving verifies all 39,250 surface/profile columns and block properties, supported spawn, headroom, explicit plinth writes, archive bytes/CRCs and all 187 extracted chunks. A portable CLI replay reproduces the floor-cell and grading-change files exactly and passes native/archive checks again. Fifteen focused floor/grading, source-audit and geographic tests pass. They cover floor-top quantization, shared provenance, differing-level rejection, minimum grading edits, no input mutation, cancellation, infeasible bounds and the explicit assumption requirement.

## Reproduce

The portable review pack retains the original aligned world, six planning inputs, OSM/grid/DTM assets, source landscape PDF and request. With this repository installed:

```sh
python -m voxel_mapper.planning_floor_preview \
  --config alignment-request.json --world-directory base-world \
  --pdf originals/wicker-landscape.pdf --output a-new-floor-preview \
  --assume-plan-ffl-odn
```

The flag opts into a clearly conditional study; it does not approve production placement. Grading variables cap at 65,536 cells with a 20-second solver limit, floor cells at 2,048, plinth blocks at 16,384 and native writes at one million. Source/terrain pins, original FFL extraction and geographic placement are recomputed. The base world is hash-checked before and after generation. This is a source/CLI workflow, without a new desktop button or automatic model training.

Next work is to establish the floor datum and actual entrance/undercroft details, resolve the three perimeter transitions using that evidence, and then add source-driven walls and roofs. The conditional design assumptions remain separate from accepted source geometry and survey truth.
