"""Exact dashed-end connections to original solid passage-side candidates."""
import math
import re
from shapely.geometry import LineString,Point,shape,mapping
from shapely.strtree import STRtree
from .drawing_components import split_page

VERSION='archway-exact-source-ends-v1'
SOLID=re.compile(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*')
DASHED=re.compile(r'\s*\[\s*([\d.\s]+)\]\s*[\d.]+\s*')


def review(parents,references,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:raise ValueError('Bounded source-end checks required')
    if len(references)>1 or sum(len(r['reference_occurrences']) for r in references)>500:raise ValueError('Single bounded reference page required')
    components=split_page(parents);sources={(r['document_sha256'],r['page']) for r in components}
    if any((r['document_sha256'],r['page']) not in sources for r in references):raise ValueError('Same source page required')
    segments=[];ends=[]
    for row in components:
        if (row['geometry']['type']!='LineString' or row.get('curve_approximation',{}).get('cubic_segments')
                or row.get('paint_reference_truncated') or not row.get('paint_references')):continue
        styles=[p['stroke_style'].get('dashes_pdf') for p in row['paint_references']]
        solid=all(isinstance(s,str) and SOLID.fullmatch(s) for s in styles)
        dashed=all(isinstance(s,str) and (m:=DASHED.fullmatch(s)) and any(float(x)>0 for x in m[1].split()) for s in styles)
        if not solid and not dashed:continue
        coords=row['geometry']['coordinates']
        for i,(a,b) in enumerate(zip(coords,coords[1:])):
            g=LineString([a,b])
            if g.length==0:continue
            record={'component_id':row['id'],'component_contract':row['extraction_contract'],
                'parent_references':row['parent_references'],'source_component_geometry':row['geometry'],
                'segment_index':i,'segment_geometry':mapping(g),'stroke_dashes_pdf':styles}
            (segments if solid else ends).append((g,record))
            if len(segments)+len(ends)>100000:raise ValueError('Source segment budget exceeded')
    index=STRtree([g for g,_ in segments]);checks=0;links=[]
    def withheld():return {'version':VERSION,'status':'end_budget_withheld','connections':[], 'checks':checks,'world_geometry_additions':0}
    for end,end_record in ends:
        partners=[]
        for point in end.coords:
            matches=[]
            for k in index.query(Point(point)):
                checks+=1
                if checks>max_checks:return withheld()
                k=int(k)
                if segments[k][0].covers(Point(point)):matches.append(k)
            partners.append(matches)
        for first in partners[0]:
            for second in partners[1]:
                checks+=1
                if checks>max_checks:return withheld()
                if first==second:continue
                a,ar=segments[first];b,br=segments[second]
                if a.intersects(b):continue
                av=(a.coords[-1][0]-a.coords[0][0],a.coords[-1][1]-a.coords[0][1])
                bv=(b.coords[-1][0]-b.coords[0][0],b.coords[-1][1]-b.coords[0][1])
                # Diagnostic one-degree policy; original skewed geometry is never straightened.
                sine=abs(av[0]*bv[1]-av[1]*bv[0])/(a.length*b.length)
                if sine>math.sin(math.radians(1)):continue
                hull=a.union(b).convex_hull
                for reference in references:
                    for occurrence,row in enumerate(reference['reference_occurrences']):
                        checks+=1
                        if checks>max_checks:return withheld()
                        if (not row['reference_id'].startswith('archway:')
                                or row['glyph_screen']['status']!='raster_consistent_candidate'
                                or not hull.contains(shape(row['label_geometry']))):continue
                        links.append({'reference_id':row['reference_id'],'occurrence_index':occurrence,
                            'dashed_end':end_record,'solid_sides':[ar,br],
                            'physical_passage_verified':False,'closed_opening_verified':False,'coordinate_control_verified':False})
    links.sort(key=lambda r:(r['reference_id'],r['occurrence_index'],r['dashed_end']['component_id'],
        r['dashed_end']['segment_index'],[(s['component_id'],s['segment_index']) for s in r['solid_sides']]))
    return {'version':VERSION,'status':'exact_source_end_connections_only','connections':links,'checks':checks,
        'solid_segments':len(segments),'dashed_segments':len(ends),'parallel_angle_policy_degrees':1,
        'physical_passage_verified':False,'world_geometry_additions':0,
        'limitations':['Exact endpoint incidence and full-label containment in the sides convex hull are diagnostic evidence only.',
            'Dashed paint may denote overhead geometry or other annotations; passage semantics and opposite ends remain unresolved.',
            'All competing source connections are retained. No closure polygon, scale, height or coordinate control is exported.']}
