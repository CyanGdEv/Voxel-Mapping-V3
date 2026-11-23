"""Sparse LiDAR foliage-shell repair helpers.

Coordinates are integer Minecraft blocks in (x, y, z) order. The repair is
deliberately conservative: it closes only one-block enclosed pinholes and
clips canopy voxels from protected structures plus an optional clearance.
"""

from __future__ import annotations

from collections.abc import Iterable

Voxel = tuple[int, int, int]
_NEIGHBOURS_26 = tuple(
    (dx, dy, dz)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    for dz in (-1, 0, 1)
    if (dx, dy, dz) != (0, 0, 0)
)
_FACES_6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def clip_canopy_to_obstacles(
    leaves: Iterable[Voxel],
    protected: Iterable[Voxel],
    *,
    clearance: int = 1,
) -> tuple[set[Voxel], int]:
    """Remove foliage in ruin/building voxels and a cubic clearance around them.

    ``protected`` should contain surveyed or otherwise high-confidence structure
    voxels (for example ruin roofs and masonry). A clearance of one block prevents
    leaves from visually intersecting those surfaces. Negative coordinates work.
    """
    if clearance < 0:
        raise ValueError("clearance must be non-negative")
    leaf_set = set(leaves)
    blocked: set[Voxel] = set()
    for x, y, z in set(protected):
        for dx in range(-clearance, clearance + 1):
            for dy in range(-clearance, clearance + 1):
                for dz in range(-clearance, clearance + 1):
                    blocked.add((x + dx, y + dy, z + dz))
    clipped = leaf_set - blocked
    return clipped, len(leaf_set) - len(clipped)


def fill_enclosed_leaf_pinholes(
    leaves: Iterable[Voxel],
    *,
    minimum_neighbours: int = 20,
) -> tuple[set[Voxel], int]:
    """Fill isolated one-voxel holes in dense 3-D leaf shells.

    A candidate must have all six face neighbours occupied and at least
    ``minimum_neighbours`` of its 26 surrounding voxels occupied. It also has to
    be adjacent to the input canopy, so this never expands an outer shell. Gaps
    larger than one voxel remain open for branches and canopy variation.
    """
    if not 1 <= minimum_neighbours <= 26:
        raise ValueError("minimum_neighbours must be between 1 and 26")
    leaf_set = set(leaves)
    candidates: set[Voxel] = set()
    for x, y, z in leaf_set:
        for dx, dy, dz in _NEIGHBOURS_26:
            p = (x + dx, y + dy, z + dz)
            if p not in leaf_set:
                candidates.add(p)
    additions: set[Voxel] = set()
    for x, y, z in candidates:
        if not all((x + dx, y + dy, z + dz) in leaf_set for dx, dy, dz in _FACES_6):
            continue
        support = sum((x + dx, y + dy, z + dz) in leaf_set for dx, dy, dz in _NEIGHBOURS_26)
        if support >= minimum_neighbours:
            additions.add((x, y, z))
    return leaf_set | additions, len(additions)


def repair_lidar_canopy(
    leaves: Iterable[Voxel],
    protected_structures: Iterable[Voxel],
    *,
    clearance: int = 1,
    minimum_neighbours: int = 20,
) -> tuple[set[Voxel], dict[str, int]]:
    """Clip structural collisions, then close only fully enclosed pinholes."""
    leaf_set = set(leaves)
    clipped, removed = clip_canopy_to_obstacles(
        leaf_set, protected_structures, clearance=clearance
    )
    repaired, filled = fill_enclosed_leaf_pinholes(
        clipped, minimum_neighbours=minimum_neighbours
    )
    return repaired, {
        "input_leaf_voxels": len(leaf_set),
        "removed_structure_overlaps": removed,
        "filled_enclosed_pinholes": filled,
        "output_leaf_voxels": len(repaired),
    }
