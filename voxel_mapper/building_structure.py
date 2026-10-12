"""Bounded native connectivity/contact diagnostics; not engineering certification."""
from collections import defaultdict
from .wing_block_shapes import occupied_halves

VERSION='building-native-structure-v1'


def inspect(cells,anchor_cells=(),protected_air=(),roof_contacts=(),*,max_halves=500000,max_checks=4000000):
    if type(max_halves) is not int or not 1<=max_halves<=500000 or type(max_checks) is not int or not 1<=max_checks<=4000000:
        raise ValueError('Bounded structural review required')
    if not isinstance(cells,dict) or not cells or len(cells)*8>max_halves:
        raise ValueError('Structural occupancy budget exceeded')
    for p,m in cells.items():
        if not isinstance(p,tuple) or len(p)!=3 or any(type(v) is not int for v in p) or not isinstance(m,str):
            raise ValueError('Integer native cells and materials required')
    occupied=occupied_halves(cells)
    if len(occupied)>max_halves or len(protected_air)>100000 or len(roof_contacts)>200000:
        raise ValueError('Structural occupancy/contact budget exceeded')
    for p in [*anchor_cells,*protected_air]:
        if len(p)!=3 or any(type(v) is not int for v in p):raise ValueError('Integer structural anchor/air required')
    anchors={tuple(p) for p in anchor_cells if tuple(p) in cells}
    anchor_halves={p for p in occupied if tuple(v//2 for v in p) in anchors}
    protected={tuple(p) for p in protected_air};checks=0
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise ValueError('Structural review work budget exceeded; no partial assessment')
    def neighbours(p):
        for axis in range(3):
            for step in (-1,1):
                q=list(p);q[axis]+=step;yield tuple(q)
    def groups(points):
        remaining=set(points);result=[]
        for start in sorted(points):
            if start not in remaining:continue
            remaining.remove(start);queue=[start];group={start}
            while queue:
                p=queue.pop()
                for q in neighbours(p):
                    charge()
                    if q in remaining:remaining.remove(q);group.add(q);queue.append(q)
            result.append(group)
        return result
    all_groups=groups(occupied);anchored=set();components=[]
    for number,group in enumerate(all_groups):
        floor_contact=bool(group&anchor_halves)
        if floor_contact:anchored.update(group)
        components.append({'id':number,'half_cells':len(group),'touches_declared_floor':floor_contact,
            'bounds_half_grid':[list(min(p[i] for p in group) for i in range(3)),list(max(p[i] for p in group) for i in range(3))]})
    wood={p for p,m in occupied.items() if m.startswith(('dark_oak','spruce','oak'))}
    roof_regions=[];unsupported=0
    for number,group in enumerate(groups(wood)):
        contacts=set()
        for p in group:
            for q in neighbours(p):
                charge()
                if q in occupied and q not in wood:contacts.add(q)
        reaches_floor=bool(group&anchored) if anchors else None
        unsupported+=reaches_floor is False
        roof_regions.append({'id':number,'half_cells':len(group),'masonry_contact_half_cells':len(contacts),
                             'reaches_declared_floor':reaches_floor,'sample_half_grid':list(min(group))})
    missing_contacts=[];guarded=0
    for contact in roof_contacts:
        a,b=contact['columns'];threshold=contact['minimum_half_y'];upper=contact['maximum_half_y']
        if (len(a)!=2 or len(b)!=2 or any(type(v) is not int for v in [*a,*b,threshold,upper])
                or abs(a[0]-b[0])+abs(a[1]-b[1])!=1 or not 0<=upper-threshold<=16):
            raise ValueError('Bounded neighbouring roof contact required')
        joins=False;guard=False
        for h in range(threshold,upper+1):
            for side in (0,1):
                charge()
                if a[0]!=b[0]:
                    left,right=sorted([a,b]);p=(2*left[0]+1,h,2*left[1]+side);q=(2*right[0],h,2*right[1]+side)
                else:
                    left,right=sorted([a,b],key=lambda c:c[1]);p=(2*left[0]+side,h,2*left[1]+1);q=(2*right[0]+side,h,2*right[1])
                joins |= p in occupied and q in occupied
                guard |= p in protected or q in protected
        if not joins:
            if guard:guarded+=1
            else:missing_contacts.append({'columns':[list(a),list(b)],'minimum_half_y':threshold,'maximum_half_y':upper})
    blocked=sorted(set(occupied)&protected)
    reasons=[]
    if not anchors:reasons.append('missing_declared_floor_anchor')
    elif unsupported:reasons.append('roof_regions_without_floor_connection')
    if anchors and len(anchored)!=len(occupied):reasons.append('geometry_without_floor_connection')
    if missing_contacts:reasons.append('missing_expected_roof_contacts')
    if blocked:reasons.append('blocked_declared_air')
    roof_fraction=1-unsupported/len(roof_regions) if anchors and roof_regions else 1. if anchors else None
    assessed_contacts=len(roof_contacts)-guarded
    contact_fraction=1-len(missing_contacts)/assessed_contacts if assessed_contacts else 1.
    score=min(len(anchored)/len(occupied),roof_fraction,contact_fraction,0. if blocked else 1.) if anchors else None
    return {'version':VERSION,'status':'passed_native_checks' if not reasons else 'needs_structural_review',
            'reasons':reasons,'checks':checks,'occupied_half_cells':len(occupied),'component_count':len(components),
            'components':components,'declared_floor_anchor_cells':len(anchors),
            'floor_connected_half_cells':len(anchored),'floor_connected_fraction':len(anchored)/len(occupied) if anchors else None,
            'roof_region_count':len(roof_regions),'roof_regions':roof_regions,
            'native_diagnostic_score':score,'roof_floor_connected_fraction':roof_fraction,
            'unsupported_roof_regions':unsupported if anchors else None,
            'missing_roof_contact_count':len(missing_contacts),'missing_roof_contacts':missing_contacts,
            'guarded_roof_contacts_unassessed':guarded,'blocked_air_half_cells':len(blocked),
            'blocked_air_samples':[list(p) for p in blocked[:32]],
            'physical_structural_safety_verified':False,'player_movement_verified':False,
            'limitations':['Face connectivity is a native geometry diagnostic, not load-bearing engineering evidence.',
                'Source-declared floor anchors do not establish terrain, foundations or surveyed elevation.',
                'Guarded roof interfaces remain unassessed; absent guards cannot establish a complete passage inventory.']}
