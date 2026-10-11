"""Gap-qualified source-network faces for review; original geometry stays unchanged."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from shapely.affinity import affine_transform
from shapely.geometry import LineString,Point,Polygon,box,mapping,shape
from shapely.ops import polygonize_full,unary_union
from shapely.strtree import STRtree

VERSION='aperture-gap-proposals-v1'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def propose(opening,records,matrix,scope,gap_limit=2,*,max_checks=200000,max_segments=10000,max_gaps=2000,max_faces=2000):
    limits=[(max_checks,200000),(max_segments,10000),(max_gaps,2000),(max_faces,2000)]
    if any(type(v) is not int or not 1<=v<=upper for v,upper in limits):raise ValueError('Bounded gap proposal budgets required')
    if (len(records)>20000 or len(matrix)!=6 or len(scope)!=4 or type(gap_limit) not in (int,float) or not 0<gap_limit<=2 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [*matrix,*scope])):
        raise ValueError('Finite source frame and bounded gap limit required')
    if scope[2]<=scope[0] or scope[3]<=scope[1]:raise ValueError('Ordered source scope required')
    keys={(r['document_sha256'],r['page'],r['coordinate_frame']) for r in records}
    if len(keys)>1 or any(k[2]!='pdf_native_points_y_up' for k in keys):raise ValueError('One original source page required')
    points=opening['points_pixels']
    if len(points)>2048 or any(len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points):raise ValueError('Bounded finite reviewed aperture required')
    seed=Polygon(points)
    if not seed.is_valid or seed.area<=0 or not box(*scope).covers(seed):raise ValueError('Valid in-scope reviewed aperture required')
    transform=[matrix[0],matrix[2],matrix[1],matrix[3],matrix[4],matrix[5]]
    search=box(seed.bounds[0]-12,seed.bounds[1]-12,seed.bounds[2]+12,seed.bounds[3]+12)
    counts=Counter();checks=0;segments=[];proofs=[];endpoints=[];protected=[]
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise OverflowError
    def withheld(reason):return {'status':'gap_proposal_budget_withheld','reason':reason,'proposals':[],'gaps':[],'checks':checks,'counts':dict(counts),'world_geometry_additions':0}
    try:
        for record in sorted(records,key=lambda r:r['id']):
            charge()
            if record.get('paint_reference_truncated') or record.get('curve_approximation',{}).get('cubic_segments'):
                counts['curved_or_truncated_components_deferred']+=1;continue
            paints=record.get('paint_references',[])
            if not paints or any(not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints):continue
            native=shape(record['geometry']);g=affine_transform(native,transform)
            if g.geom_type not in ('LineString','Polygon') or not g.is_valid:continue
            if not search.intersects(g):continue
            native_chains=[list(native.coords)] if native.geom_type=='LineString' else [list(native.exterior.coords),*[list(r.coords) for r in native.interiors]]
            chains=[list(g.coords)] if g.geom_type=='LineString' else [list(g.exterior.coords),*[list(r.coords) for r in g.interiors]]
            if g.geom_type=='Polygon':protected.extend(Polygon(r) for r in g.interiors)
            for ring,(chain,native_chain) in enumerate(zip(chains,native_chains)):
                for index,(a,b) in enumerate(zip(chain,chain[1:])):
                    charge()
                    line=LineString([a,b])
                    if line.length==0 or not search.intersects(line):continue
                    if len(segments)>=max_segments:raise OverflowError
                    # Entire original source segment retained, including crossing baselines.
                    proof={'source_candidate_id':record['id'],'ring_index':ring,'segment_index':index,
                           'native_endpoints':[list(native_chain[index]),list(native_chain[index+1])],
                           'pixel_endpoints':[list(a),list(b)]}
                    segments.append(line);proofs.append(proof)
                if g.geom_type=='LineString' and chain[0]!=chain[-1]:
                    for index in (0,len(chain)-1):
                        if search.covers(Point(chain[index])):
                            endpoints.append({'source_candidate_id':record['id'],'vertex_index':index,
                                              'native_point':list(native_chain[index]),'pixel_point':list(chain[index])})
        if not segments:return {'status':'no_eligible_source_network','proposals':[],'gaps':[],'checks':checks,'counts':dict(counts),'world_geometry_additions':0}
        ep=[Point(e['pixel_point']) for e in endpoints];index=STRtree(ep);gaps=[];gap_lines=[]
        for i,point in enumerate(ep):
            for j in index.query(point.buffer(gap_limit)):
                j=int(j)
                if j<=i or endpoints[i]['source_candidate_id']==endpoints[j]['source_candidate_id']:continue
                charge();distance=point.distance(ep[j])
                if distance==0:counts['exact_endpoint_pairs']+=1;continue
                if distance>gap_limit:continue
                if len(gaps)>=max_gaps:raise OverflowError
                gap={'endpoints':[endpoints[i],endpoints[j]],'distance_pixels':distance,
                     'kind':'added_hypothesis_edge','original_endpoints_moved':False,'physical_connection_verified':False}
                gap['id']=digest(gap);gaps.append(gap);gap_lines.append(LineString([point,ep[j]]))
        spatial_sources=STRtree(segments)
        for i,line in enumerate(segments):
            for j in spatial_sources.query(line,predicate='intersects'):
                if int(j)>i:charge()
        base_network=unary_union(segments);proposals=[];seen=set();trial_faces=0
        totals=Counter()
        # Never combine competing repairs in one network. Original network first,
        # then one explicit connector per trial; multi-gap cycles are outside this stage.
        for active_gap,connector in [(None,None),*zip(gaps,gap_lines)]:
            charge()
            all_lines=segments+([connector] if connector is not None else [])
            spatial=STRtree(all_lines)
            if connector is not None:
                for _ in spatial_sources.query(connector,predicate='intersects'):charge()
            network=unary_union([base_network,connector]) if connector is not None else base_network
            parts=list(network.geoms) if hasattr(network,'geoms') else [network]
            if sum(len(g.coords) for g in parts)>40000:raise OverflowError
            faces,cuts,dangles,invalid=polygonize_full(network)
            if len(faces.geoms)>max_faces:raise OverflowError
            trial_faces+=len(faces.geoms)
            totals.update(cut_edges=len(cuts.geoms),dangles=len(dangles.geoms),invalid_rings=len(invalid.geoms))
            for face in sorted(faces.geoms,key=lambda g:g.normalize().wkb_hex):
                charge()
                if not face.is_valid or face.area<=0 or not search.covers(face) or not box(*scope).covers(face):continue
                if face.interiors:
                    counts['multi_ring_face_deferred']+=1;continue
                iou=face.intersection(seed).area/face.union(seed).area
                distance=seed.boundary.hausdorff_distance(face.boundary)
                if iou<.85 or distance>12:continue
                if any(face.intersection(hole).area>1e-7 for hole in protected):
                    counts['protected_hole_fill_withheld']+=1;continue
                source_links=[];gap_links=[];coverage=[]
                for j in spatial.query(face.boundary.buffer(1e-7)):
                    charge();j=int(j);line=all_lines[j];overlap=face.boundary.intersection(line.buffer(1e-7,cap_style=2))
                    if overlap.length<=1e-6:continue
                    pieces=list(overlap.geoms) if hasattr(overlap,'geoms') else [overlap]
                    for piece in pieces:
                        if piece.geom_type!='LineString' or piece.length<=1e-6:continue
                        fractions=sorted([line.project(Point(piece.coords[0]),normalized=True),line.project(Point(piece.coords[-1]),normalized=True)])
                        link={'interval_fractions':fractions,'boundary_length_pixels':piece.length}
                        if j<len(segments):source_links.append({**proofs[j],**link})
                        else:gap_links.append({'gap_id':active_gap['id'],**link})
                        coverage.append(piece)
                # Comparison tolerance only: it never enters network construction.
                if not coverage or not unary_union(coverage).buffer(1e-7).covers(face.boundary):
                    counts['incomplete_interval_proof_withheld']+=1;continue
                if len(source_links)+len(gap_links)>2048 or len(face.exterior.coords)+sum(len(r.coords) for r in face.interiors)>2048:raise OverflowError
                source_links.sort(key=digest);gap_links.sort(key=digest)
                proposal={'geometry_pixels':mapping(face),'geometry_identity':digest(mapping(face.normalize())),'source_interval_proofs':source_links,'hypothesis_interval_proofs':gap_links,
                    'iou_with_reviewed_trace':iou,'boundary_hausdorff_pixels':distance,
                    'status':'gap_qualified_outline_proposal' if gap_links else 'original_closed_outline_candidate',
                    'provenance_comparison_epsilon_pixels':1e-7,'source_coordinates_changed':False,'physical_aperture_verified':False,'connector_trial_id':active_gap['id'] if gap_links else None,'mesh_update_authorized':False,'world_geometry_additions':0}
                proposal['id']=digest(proposal)
                if proposal['id'] in seen:continue
                seen.add(proposal['id']);proposals.append(proposal)
                if len(proposals)>max_faces:raise OverflowError
        counts.update(source_segments=len(segments),gap_edges=len(gaps),connector_trials=1+len(gaps),network_faces_across_trials=trial_faces,
                      proposals=len(proposals))
        return {'status':'single_connector_network_faces_only','proposals':proposals,'gaps':gaps,'checks':checks,'counts':dict(counts),
                'gap_limit_pixels':gap_limit,'search_margin_pixels':12,
                'limitations':['One added connector per independent trial. Multiple-connector cycles and exhaustive non-face cycles remain outside this stage.',
                              'Added connectors are explicit hypotheses, not original drawing edges or accepted physical connections.',
                              'No source endpoint moved, gap silently repaired, largest outline selected, or mesh automatically changed.'],
                'world_geometry_additions':0}
    except OverflowError:return withheld('bounded network/proposal work exhausted')


def run(recipe_path,source_pdf,output):
    import pymupdf
    from .drawing_geometry import extract_page
    from .drawing_components import split_page
    from .drawing_page_tools import native_to_render_pixels
    from .native_opening_inventory import run as inventory
    recipe_path=Path(recipe_path);source_pdf=Path(source_pdf);output=Path(output)
    if recipe_path.stat().st_size>2*1024*1024 or source_pdf.stat().st_size>32*1024*1024:raise ValueError('Source byte budget exceeded')
    raw=source_pdf.read_bytes();recipe_raw=recipe_path.read_bytes();recipe=json.loads(recipe_raw)
    inv=inventory(recipe_path,source_pdf,output/'inventory');view=json.loads(Path(inv['inventory_path']).read_text())
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
        matrix=native_to_render_pixels(doc[view['page']-1],recipe['documents']['elevation']['render_width_pixels'])
        parents,extraction=extract_page(doc[view['page']-1],view['document_sha256'],view['page'],min_line_length_points=.25,max_candidates=10000,isolate_open_stroked_subpaths=True)
    records=split_page(parents) if extraction['status']=='unplaced_geometry_candidates' else []
    rows=[]
    for opening in recipe['openings']:
        rows.append({'seed_id':opening['id'],'review':propose(opening,records,matrix,view['reviewed_scope_pixels']) if records else
                     {'status':'source_extraction_withheld','proposals':[],'gaps':[],'world_geometry_additions':0}})
    used={p['source_candidate_id'] for row in rows for proposal in row['review']['proposals'] for p in proposal['source_interval_proofs']}
    used.update(e['source_candidate_id'] for row in rows for gap in row['review']['gaps'] for e in gap['endpoints'])
    report={'version':VERSION,'document_sha256':view['document_sha256'],'recipe_sha256':hashlib.sha256(recipe_raw).hexdigest(),
            'inventory_sha256':inv['inventory_sha256'],'native_to_pixel_matrix':matrix,'render_transform':'uniform_width_scale; rounded pixmap height is not resampling',
            'metres_per_pixel_nominal':view['metres_per_pixel_nominal'],'extraction':extraction,'rows':rows,
            'source_components':[r for r in records if r['id'] in used],'world_geometry_additions':0,'mesh_update_authorized':False}
    if raw!=source_pdf.read_bytes() or recipe_raw!=recipe_path.read_bytes():raise ValueError('Gap proposal inputs changed during run')
    encoded=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();target=output/'aperture-gap-proposals.json';reused=target.exists()
    if len(encoded)>32*1024*1024:raise ValueError('Gap proposal receipt budget exceeded')
    if reused and target.read_bytes()!=encoded:raise ValueError('Gap proposal receipt changed; use fresh output')
    if not reused:target.write_bytes(encoded)
    return {'version':VERSION,'proposal_path':str(target),'proposal_sha256':hashlib.sha256(encoded).hexdigest(),'reused':reused,
            'opening_statuses':dict(Counter(r['review']['status'] for r in rows)),
            'openings_with_proposals':sum(bool(r['review']['proposals']) for r in rows),'world_geometry_additions':0,'mesh_update_authorized':False}
