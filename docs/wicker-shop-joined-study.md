# Joined shop review

The first in-game review showed a long horizontal gap between the walls and
main roof in the 1:1 surface study. The optional `--joined` build closes each
existing sampled wall column vertically to the sampled main-roof underside.
It never fills below the existing column top and rejects missing roofs,
inverted profiles or gaps exceeding one source metre. These are estimated
display joins, not newly recovered construction measurements. The source
meshes and original surface-study mode remain unchanged.

The joined mode also includes the retained canopy roof and front fascia.
It reproduces the canopy model from the original PDFs before export, verifies
its checksum, and retains the chosen northeast heights and conflicting
southeast trace. Side fascia, thickness and construction details remain
unresolved. The illustrative timber palette is unchanged.

Both scales audit every joining column and retain the doorway centre checks.
This establishes column continuity only, not full shell completeness or player
movement. Geographic placement, source handedness, floor datum and the
northwest opening width remain unresolved. No park geometry is added.

```sh
python scripts/build_wicker_shop_study.py --pdf-directory shop-pdfs \
  --output shop-joined-review --joined --preview
```

The package includes independent 1:1 and 4:1 worlds, an actual voxel preview,
per-world reports and the reproduced source opening review. Native export
cold-reopens both worlds and checks written blocks and unwritten air cells.
The 4:1 version is a detail review, not a full-size park reconstruction.

The reproduced 1:1 build contains 412 surface cells: 28 estimated joining
cells and 12 canopy/fascia samples in addition to the original surfaces.
At 4:1 it contains 7,189 cells, with 365 joining cells and 161 projection
samples. Both worlds passed native cold-reopen verification. Every existing
wall column connects to its overhead main-roof sample; all retained doorway
centre samples remain air. Unit checks exercise lower-hole preservation,
missing/remote/inverted roof refusal, both scales and unchanged source bytes.
