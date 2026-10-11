"""Bounded proofs of original straight PDF path operators, not curve chords."""
import math
import pymupdf
from .drawing_geometry import native_inverse

VERSION='literal-pdf-path-edges-v1'


def key(a,b):return tuple(sorted((tuple(a),tuple(b))))


def extract(page,*,max_items=200000):
    if type(max_items) is not int or not 1<=max_items<=200000:raise ValueError('Bounded literal operator budget required')
    matrix=native_inverse(page);index={};checks=0;curves=0
    def point(p):
        p=pymupdf.Point(p)*matrix
        if not all(math.isfinite(v) for v in (p.x,p.y)):raise ValueError('Nonfinite original operator point')
        return [p.x,p.y]
    for ordinal,path in enumerate(page.get_cdrawings(extended=True)):
        for item_index,item in enumerate(path.get('items',[])):
            checks+=1
            if checks>max_items:return {},{'version':VERSION,'status':'literal_operator_budget_withheld','checks':checks}
            operator=item[0];edges=[]
            if operator=='l':edges=[(point(item[1]),point(item[2]))]
            elif operator=='re':
                r=pymupdf.Rect(item[1]);points=[point(p) for p in (r.tl,r.tr,r.br,r.bl)]
                if item[2]<0:points.reverse()
                edges=list(zip(points,points[1:]+points[:1]))
            elif operator=='qu':
                q=pymupdf.Quad(item[1]);points=[point(p) for p in (q.ul,q.ur,q.lr,q.ll)];edges=list(zip(points,points[1:]+points[:1]))
            elif operator=='c':curves+=1
            for edge_index,(a,b) in enumerate(edges):
                checks+=1
                if checks>max_items:return {},{'version':VERSION,'status':'literal_operator_budget_withheld','checks':checks}
                if a==b:continue
                proof={'paint_ordinal':ordinal,'item_index':item_index,'edge_index':edge_index,'operator':operator,'native_endpoints':[a,b]}
                index.setdefault((ordinal,key(a,b)),[]).append(proof)
    return index,{'version':VERSION,'status':'original_straight_operators_only','checks':checks,'literal_edges':sum(len(v) for v in index.values()),'cubic_operators_excluded':curves}
