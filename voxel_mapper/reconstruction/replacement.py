"""Explicit, bounded replacement of reviewed generic building placeholders.

This stage is separate from geometry generators, which cannot implicitly carve.
Coordinates and ground levels use the source world's local metre/ODN frame.
"""
from shapely.geometry import box


def compose_replacement(existing, ground, placeholder, model, approach=(), *,
                        placeholder_materials=('stone_bricks',), max_cells=10000):
    """Restore placeholder ground, clear only its reviewed blocks, then compose.

    existing maps cell -> native block base_name; ground maps column -> original
    surface cell elevation. Leaves may be pruned only at new occupied cells.
    Unknown solids, trunks, barriers and water cause an atomic refusal.
    """
    if placeholder.is_empty or not placeholder.is_valid or placeholder.area > 500:
        raise ValueError('Small valid reviewed placeholder footprint required')
    result = {}; removed = 0; pruned = 0
    def put(cell, material, role):
        if cell not in existing:
            raise ValueError('Missing native baseline cell')
        result[cell] = {'x':cell[0], 'y':cell[1], 'z':cell[2],
                        'kind':role, 'material':material, 'source':'estimated-placement'}
        if len(result)>max_cells:raise ValueError('Replacement budget exceeded')
    for cell, name in existing.items():
        x,y,z=cell
        if name not in placeholder_materials or (x,z) not in ground:continue
        if y < ground[x,z] or placeholder.intersection(box(x,z,x+1,z+1)).area<=1e-9:continue
        if y > ground[x,z]+30:raise ValueError('Placeholder exceeds reviewed height budget')
        put(cell, 'grass_block' if y==ground[x,z] else 'air', 'placeholder-removal')
        removed += 1
    if not removed:raise ValueError('Reviewed placeholder not found')
    # Approach first; architectural members take precedence at shared cells.
    for row in list(approach)+list(model):
        cell=tuple(row[k] for k in ('x','y','z'));x,y,z=cell
        if not all(isinstance(v,int) for v in cell):raise ValueError('Integer cells required')
        if cell not in existing or (x,z) not in ground:raise ValueError('Outside inspected baseline')
        if y<ground[x,z]:raise ValueError('New geometry buried below terrain')
        old=result[cell]['material'] if cell in result else existing[cell]
        if old not in ('air','grass_block','dirt','stone','cobblestone','sandstone','leaves','slab','stairs'):
            raise ValueError('Unreviewed existing solid collision: '+old)
        # Surface paving only; do not treat higher stone structures as floors.
        if old in ('stone','cobblestone','slab','stairs') and y>ground[x,z]:
            raise ValueError('Existing elevated structure collision')
        if old=='leaves':pruned+=1
        put(cell,row['material'],row.get('kind','structure'))
    return list(result.values()), {'removed_placeholder_cells':removed,
        'pruned_leaf_cells_at_new_solids':pruned,'overlay_records':len(result),
        'scope':'Reviewed placeholder blocks and explicit new solid cells only'}
