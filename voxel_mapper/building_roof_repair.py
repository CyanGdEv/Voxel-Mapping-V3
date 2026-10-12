"""Bounded display risers joining detached roofs without altering masonry or air."""
from itertools import product
from .wing_block_shapes import occupied_halves
from .building_structure import inspect


def repair(cells,anchors,protected,roof_columns,*,max_repairs=16):
    if type(max_repairs) is not int or not 0<=max_repairs<=16:raise ValueError('Bounded roof repair count required')
    output=dict(cells);records=[];protected=set(protected)
    for _ in range(max_repairs):
        review=inspect(output,anchors,protected)
        if review['unsupported_roof_regions'] in (None,0):break
        occupied=occupied_halves(output)
        # Determine the floor-connected occupancy once; geometry groups are
        # traversed from actual source-declared floor cells, never a preview pad.
        starts={p for p in occupied if tuple(v//2 for v in p) in anchors}
        grounded=set(starts);queue=list(starts)
        while queue:
            p=queue.pop()
            for axis in range(3):
                for step in (-1,1):
                    q=list(p);q[axis]+=step;q=tuple(q)
                    if q in occupied and q not in grounded:grounded.add(q);queue.append(q)
        wood={p for p,m in occupied.items() if m.startswith('dark_oak')}
        supported_levels={}
        for x,h,z in wood&grounded:supported_levels.setdefault((x//2,z//2),set()).add(h)
        unsupported=wood-grounded;bottoms={}
        for x,h,z in unsupported:bottoms[x//2,z//2]=min(bottoms.get((x//2,z//2),h),h)
        options=[]
        for (x,z),bottom in sorted(bottoms.items()):
            if (x,z) not in roof_columns:continue
            for nx,nz in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)):
                levels=[h for h in supported_levels.get((nx,nz),()) if 0<bottom-h<=2]
                if not levels:continue
                start=max(levels);additions={};valid=True
                for h in range(start,bottom):
                    position=(x,h//2,z);old=output.get(position)
                    new_halves={(2*x+dx,h,2*z+dz) for dx,dz in product((0,1),repeat=2)}
                    if new_halves&protected or old and not old.startswith('dark_oak'):
                        valid=False;break
                    additions.setdefault(position,set()).add(h%2)
                if valid:options.append((bottom-start,(x,z),(nx,nz),start,bottom,additions))
        if not options:break
        _,column,neighbour,start,bottom,additions=min(options,key=lambda r:r[:5])
        candidate=dict(output)
        for position,halves in additions.items():
            old=output.get(position)
            if old:
                halves=halves|({1} if old.endswith('_slab_top') else {0} if old.endswith('_slab') else {0,1})
            candidate[position]='dark_oak_planks' if len(halves)==2 else 'dark_oak_slab_top' if 1 in halves else 'dark_oak_slab'
        after=inspect(candidate,anchors,protected)
        if after['unsupported_roof_regions']>=review['unsupported_roof_regions']:
            break
        output=candidate
        records.append({'column':list(column),'grounded_neighbour':list(neighbour),'added_half_height_interval':[start,bottom],
                        'cells_changed':[list(p) for p in sorted(additions)],'evidence_class':'bounded_display_join_hypothesis'})
    return output,records
