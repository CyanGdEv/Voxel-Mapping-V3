"""Exact dashed-end connections to original solid passage-side candidates."""
import math
import re
from shapely.geometry import LineString,Point,Polygon,shape,mapping
from shapely.strtree import STRtree
from .drawing_components import split_page

VERSION='archway-exact-source-ends-v2'
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
    # Search both solid and dashed original segments for a second complete end.
    # A four-edge cycle is a source topology candidate, never an opening identity.
    for link in links:
        a,b=[shape(r['segment_geometry']) for r in link['solid_sides']]
        end=shape(link['dashed_end']['segment_geometry']);start=list(end.coords)
        label=shape(references[0]['reference_occurrences'][link['occurrence_index']]['label_geometry'])
        opposite=[]
        for candidate,record in segments+ends:
            checks+=1
            if checks>max_checks:return withheld()
            if candidate.equals(end):continue
            points=list(candidate.coords)
            if not (a.covers(Point(points[0])) and b.covers(Point(points[1]))):
                if a.covers(Point(points[1])) and b.covers(Point(points[0])):points.reverse()
                else:continue
            ring=Polygon([start[0],points[0],points[1],start[1]])
            if not ring.is_valid or ring.is_empty or not ring.contains(label):continue
            opposite.append({'source_end':record,'source_side_portions':[
                mapping(LineString([start[0],points[0]])),mapping(LineString([start[1],points[1]]))],
                'source_cycle_closed':True,'physical_opening_verified':False,'coordinate_control_verified':False})
        opposite.sort(key=lambda r:(r['source_end']['component_id'],r['source_end']['segment_index']))
        link['opposite_end_candidates']=opposite
        link['cycle_status']='complete_source_cycle_candidates' if opposite else 'opposite_source_end_missing'
    links.sort(key=lambda r:(r['reference_id'],r['occurrence_index'],r['dashed_end']['component_id'],
        r['dashed_end']['segment_index'],[(s['component_id'],s['segment_index']) for s in r['solid_sides']]))
    return {'version':VERSION,'status':'exact_source_end_connections_only','connections':links,'checks':checks,
        'complete_source_cycle_candidates':sum(len(r['opposite_end_candidates']) for r in links),'solid_segments':len(segments),'dashed_segments':len(ends),'parallel_angle_policy_degrees':1,
        'physical_passage_verified':False,'world_geometry_additions':0,
        'limitations':['Exact endpoint incidence and full-label containment in the sides convex hull are diagnostic evidence only.',
            'Dashed paint may denote overhead geometry or other annotations; a complete source cycle does not establish passage semantics.',
            'All competing source connections are retained. No closure polygon, scale, height or coordinate control is exported.']}


def occurrence_index(report,occurrence):
    """Proof locations in the full page report; never a geometry selection."""
    if report['version']!=VERSION:raise ValueError('Current source-end review required')
    indices=[i for i,r in enumerate(report['connections']) if r['occurrence_index']==occurrence]
    return {'source_end_connection_indices':indices,
        'complete_source_cycle_candidates':sum(len(report['connections'][i]['opposite_end_candidates']) for i in indices)}
