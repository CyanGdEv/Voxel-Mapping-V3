"""Half-metre roof samples mapped to native slabs in a one-block-per-metre world."""
from collections import Counter
from itertools import product
from .shop_shell import close_shell,boundary_columns,opening_columns,leak_audit


def half_mesh(mesh):
    return {**mesh,'vertices':[[2*v for v in p] for p in mesh['vertices']]}


def occupied_halves(materials):
    cells=set()
    for (x,y,z),material in materials.items():
        levels=(1,) if material.endswith('_slab_top') else (0,) if material.endswith('_slab') else (0,1)
        cells.update((2*x+dx,2*y+dy,2*z+dz) for dx,dy,dz in product((0,1),levels,(0,1)))
    return cells


def assemble(model):
    from .shop_study import raster_mesh
    wall,_=raster_mesh(half_mesh(model['wall_mesh']),1)
    roof,_=raster_mesh(half_mesh(model['roof_mesh']),1)
    wall,roof,closure=close_shell(model,wall,roof,2)
    materials={tuple(v//2 for v in p):'spruce_planks' for p in wall}
    grouped={}
    for x,y,z in roof:grouped.setdefault((x//2,y//2,z//2),set()).add(y%2)
    for p,halves in grouped.items():
        # Full wall occupancy wins at wall/roof aliases, preserving the join.
        materials[p]='dark_oak_planks' if p in materials or len(halves)==2 else 'dark_oak_slab_top' if halves=={1} else 'dark_oak_slab'
    doors=opening_columns(model['opening_base_segments'],1)
    for (x,z),head in doors.items():
        for y in range(head):materials.pop((x,y,z),None)
    door_halves={(2*x+dx,2*z+dz):2*head for (x,z),head in doors.items() for dx,dz in product((0,1),repeat=2)}
    occupied=occupied_halves(materials)
    audit=leak_audit(occupied,boundary_columns(model['outer_wall_base_outline'],2),
                     door_halves,model['outer_wall_base_outline'],2)
    if audit['interior_reached_from_exterior']:raise ValueError('Native slab occupancy opens the shell')
    projection=set()
    if 'projection_mesh' in model:
        projection,_=raster_mesh(half_mesh(model['projection_mesh']),1)
        groups={}
        for x,y,z in projection:groups.setdefault((x//2,y//2,z//2),set()).add(y%2)
        for p,halves in groups.items():
            if p not in materials:
                materials[p]='dark_oak_planks' if len(halves)==2 else 'dark_oak_slab_top' if halves=={1} else 'dark_oak_slab'
    # Preserve the already quantized two-block doorway clearance at 1:1.
    for (x,z),head in doors.items():
        for y in range(head):materials.pop((x,y,z),None)
    if any((x,y,z) in materials for (x,z),head in doors.items() for y in range(head)):
        raise ValueError('Slab palette obstructs a declared doorway')
    return materials,{'sampling_metres':.5,'world_blocks_per_source_metre':1,
        'rule':'roof half-cell occupancy selects top/bottom slabs; mixed halves and wall aliases use full blocks',
        'material_counts':dict(sorted(Counter(materials.values()).items())),
        'source_half_cell_closure':closure,'native_shape_leak_audit':audit,
        'door_air_verified':True,'projection_half_cells':len(projection),
        'fence_policy':'reserve fences for source-supported posts or rails; no post dimensions recovered for this canopy',
        'brown_palette':'dark oak and spruce remain illustrative; unspecified brown cushion block not substituted'}
