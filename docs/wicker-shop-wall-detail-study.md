# 1:1 fence and trapdoor wall detail

The `--wall-details` review follows the requested block palette: native slabs
for the roof/canopy, dark-oak fences as vertical exterior timber accents and
opened spruce trapdoors as thin wall panels. It exports only the 1:1 world.

Decorations are additive and attach to existing solid spruce wall cells.
Facades are sampled along their dominant axis, with fence strips every three
blocks and panels between them. Columns without solid wall at both floor and
head level are skipped, preserving the doors. These decorative choices and
spacing are illustrative and user-requested, not recovered construction details.
The source meshes and geographic placement gates are unchanged.

The reproduced world contains 640 occupied block positions, including the
previous slab shell, 39 fence blocks and 23 vertical trapdoors across all four
facades. Native cold-reopen validation checks slab, fence and opened trapdoor
states. Tests check unchanged base blocks, solid wall anchors, clear doorway
centre samples and all four trapdoor directions.

```sh
python scripts/build_wicker_shop_study.py --pdf-directory shop-pdfs \
  --output shop-wall-detail-v5 --preview --wall-details
```

Import **Wicker Shop WALL DETAIL V5 REVIEW 1:1**. The included preview depicts
slab heights, thin trapdoor panels and fence posts; Minecraft computes fence
connections in-game. Placement, orientation and proposed/as-built correspondence
remain unresolved.
