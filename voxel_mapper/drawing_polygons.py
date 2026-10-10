"""Recover explicit even-odd PDF fill topology without semantic placement."""
from shapely.geometry import Polygon, mapping


def polygon_candidates(vectors, max_rings=2000):
    result={'status':'unplaced_candidates','layers':[],'world_geometry_additions':0}
    if vectors.get('status')!='unverified_candidates':
        return {**result,'status':'unavailable'}
    count=0
    for layer in vectors.get('layers',[]):
        groups={}
        for path in layer['paths']:
            groups.setdefault(path['paint_group'],[]).append(path)
        candidates=[]
        for group,paths in groups.items():
            if group in layer.get('incomplete_paint_groups',[]):
                continue
            # Nonzero winding and stroked outlines require different semantics.
            if any(p['paint_operator'] not in ('f*','B*','b*') for p in paths):
                continue
            geometry=None
            valid=True
            for path in paths:
                count+=1
                if count>max_rings:
                    return {'status':'budget_rejected','layers':[],'world_geometry_additions':0}
                try:
                    ring=Polygon(path['geometry']['coordinates'])
                except (ValueError,TypeError):
                    valid=False;break
                if not path['closed'] or not ring.is_valid or ring.is_empty or ring.area<=0:
                    valid=False;break
                geometry=ring if geometry is None else geometry.symmetric_difference(ring)
            if valid and geometry is not None and not geometry.is_empty:
                candidates.append({'paint_group':group,'geometry':mapping(geometry),
                    'semantic_status':'unclassified','construction_status':'not_verified'})
        result['layers'].append({'viewport':layer['viewport'],'metric_crs':layer['metric_crs'],'polygons':candidates})
    return result
