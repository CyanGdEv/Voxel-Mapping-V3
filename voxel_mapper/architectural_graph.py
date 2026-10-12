"""Bounded source drawing topology, without object or physical connectivity claims."""
from collections import Counter,defaultdict
import hashlib
import json
import re
from shapely.geometry import LineString,Point,mapping,shape
from shapely.strtree import STRtree
from .drawing_components import split_page

VERSION='architectural-source-graph-v1'
DEFAULTS={'max_edges':20000,'max_nodes':40000,'max_pair_checks':100000,'max_overlaps':10000}


def build(parents,*,graph_options=None):
    opts={**DEFAULTS,**(graph_options or {})}
    if set(opts)!=set(DEFAULTS) or any(type(v) is not int or not 1<=v<=DEFAULTS[k] for k,v in opts.items()):
        raise ValueError('Bounded architectural graph options required')
    components=sorted(split_page(sorted(parents,key=lambda r:r['id'])),key=lambda r:r['id'])
    source=(components[0]['document_sha256'],components[0]['page'],components[0]['extraction_contract']) if components else None
    pin=hashlib.sha256(json.dumps(sorted(parents,key=lambda r:r['id']),sort_keys=True).encode()).hexdigest()
    def identity(value):return hashlib.sha256(json.dumps([VERSION,source,value],sort_keys=True).encode()).hexdigest()
    edges=[];geometries=[];nodes={};overlaps=[];checks=0;counts=Counter()
    def withheld(reason):return {'version':VERSION,'status':'graph_budget_withheld','reason':reason,'options':opts,
        'source_parent_records_sha256':pin,'source_components':[],'edges':[],'nodes':[],'overlaps':[],
        'connected_subgraphs':[],'world_geometry_additions':0}
    def node(point,edge,kind):
        key=tuple(point)
        if key not in nodes:
            if len(nodes)>=opts['max_nodes']:return False
            nodes[key]={'id':identity(['node',key]),'point_pdf_native':list(key),'incidences':{}}
        # An endpoint remains an endpoint if the same node is also found by overlay.
        incident=nodes[key]['incidences'];previous=incident.get(edge['id'])
        if previous is None or kind=='retained_endpoint':incident[edge['id']]={'edge_id':edge['id'],'basis':kind,
            'curve_approximation_present':edge['curve_approximation_present']}
        return True
    for component in components:
        g=shape(component['geometry']);curved=bool(component['curve_approximation']['cubic_segments'])
        styles=[r['stroke_style'].get('dashes_pdf') for r in component.get('paint_references',[])]
        if component.get('paint_reference_truncated') or not styles:paint='unknown_or_truncated'
        elif all(isinstance(s,str) and re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',s) for s in styles):paint='solid'
        elif all(isinstance(s,str) and re.fullmatch(r'\s*\[\s*(?:\d+(?:\.\d+)?\s*)+\]\s*\d+(?:\.\d+)?\s*',s) for s in styles):paint='dashed_pattern'
        else:paint='mixed_or_unknown'
        paths=[('open_line',None,list(g.coords))] if g.geom_type=='LineString' else [
            ('exterior_ring',0,list(g.exterior.coords))]+[('hole_ring',i,list(r.coords)) for i,r in enumerate(g.interiors)]
        for role,ring,coords in paths:
            for i,(a,b) in enumerate(zip(coords,coords[1:])):
                if a==b:continue
                if len(edges)>=opts['max_edges']:return withheld('edge_budget')
                line=LineString([a,b]);identifier=identity(['edge',component['id'],role,ring,i])
                edge={'id':identifier,'component_id':component['id'],'path_role':role,'ring_index':ring,'segment_index':i,
                    'geometry':mapping(line),'paint_class':paint,'curve_approximation_present':curved,
                    'source_geometry_basis':'bounded_curve_chord' if curved else 'retained_straight_segment'}
                edges.append(edge);geometries.append(line);counts[paint+'_edges']+=1
                if curved:counts['bounded_curve_chord_edges']+=1
                for point in (a,b):
                    if not node(point,edge,'retained_endpoint'):return withheld('node_budget')
    # Curved chords remain visible in the graph, but never create asserted exact interior intersections.
    exact=[i for i,e in enumerate(edges) if not e['curve_approximation_present']]
    index=STRtree([geometries[i] for i in exact])
    for local,i in enumerate(exact):
        for other in index.query(geometries[i]):
            other=int(other)
            if other<=local:continue
            checks+=1
            if checks>opts['max_pair_checks']:return withheld('intersection_budget')
            j=exact[other];intersection=geometries[i].intersection(geometries[j])
            if intersection.is_empty:continue
            if intersection.geom_type=='Point':points=[intersection.coords[0]]
            elif intersection.geom_type=='MultiPoint':points=[p.coords[0] for p in intersection.geoms]
            elif intersection.geom_type=='LineString':
                if len(overlaps)>=opts['max_overlaps']:return withheld('overlap_budget')
                overlaps.append({'edge_ids':sorted([edges[i]['id'],edges[j]['id']]),'geometry':mapping(intersection),
                    'physical_identity_verified':False})
                points=[intersection.coords[0],intersection.coords[-1]]
            else:raise ValueError('Unexpected straight-segment intersection geometry')
            for point in points:
                for k in (i,j):
                    if not node(point,edges[k],'straight_overlay_intersection'):return withheld('node_budget')
    edge_nodes=defaultdict(set);node_records=[]
    for row in nodes.values():
        incidences=sorted(row['incidences'].values(),key=lambda r:r['edge_id']);row={**row,'incidences':incidences}
        degree=len(incidences);valence=sum(1 if r['basis']=='retained_endpoint' else 2 for r in incidences)
        row.update(drawing_degree=degree,drawing_valence=valence,topology_candidate='open_end' if valence==1 else 'branch_or_crossing' if valence>2 else 'continuation',
            physical_connectivity_verified=False,view_scope_verified=False)
        counts[row['topology_candidate']+'_nodes']+=1
        for incident in incidences:edge_nodes[incident['edge_id']].add(row['id'])
        node_records.append(row)
    lookup={r['id']:[i['edge_id'] for i in r['incidences']] for r in node_records};seen=set();subgraphs=[]
    for identifier in sorted(edge_nodes):
        if identifier in seen:continue
        pending=[identifier];members=set();member_nodes=set()
        while pending:
            current=pending.pop()
            if current in seen:continue
            seen.add(current);members.add(current)
            for n in edge_nodes[current]:
                member_nodes.add(n);pending.extend(e for e in lookup[n] if e not in seen)
        subgraphs.append({'id':identity(['subgraph',sorted(members)]),'edge_ids':sorted(members),'node_ids':sorted(member_nodes),
            'physical_object_identity_verified':False,'view_scope_verified':False})
    for edge in edges:edge['node_ids']=sorted(edge_nodes[edge['id']])
    return {'version':VERSION,'status':'source_drawing_topology_only','options':opts,'source_parent_records_sha256':pin,
        'coordinate_frame':'pdf_native_points_y_up','document_sha256':source[0] if source else None,'page':source[1] if source else None,
        'source_components':components,'edges':sorted(edges,key=lambda r:r['id']),'nodes':sorted(node_records,key=lambda r:r['id']),
        'overlaps':sorted(overlaps,key=lambda r:r['edge_ids']),'connected_subgraphs':sorted(subgraphs,key=lambda r:r['id']),
        'counts':{**dict(counts),'edges':len(edges),'nodes':len(nodes),'overlaps':len(overlaps),
            'connected_subgraphs':len(subgraphs),'intersection_pair_checks':checks},
        'physical_connectivity_verified':False,'view_scope_verified':False,'world_geometry_additions':0,
        'limitations':['Graph connectivity is drawing topology, not a physical object, view assignment or 3D junction.',
            'Original components, paint, holes and curve bounds are retained; no gaps are snapped or bridged.',
            'Curved component chords have no asserted exact interior crossings; their retained endpoints remain approximation-qualified.',
            'Coincident edges retain distinct source identities and overlap evidence. No wall, fill, height or registration is inferred.']}
