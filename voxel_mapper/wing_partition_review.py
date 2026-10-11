"""Retain exact original path-segment wall bands in a reviewed wing plan scope."""
import copy,hashlib,json,math
from pathlib import Path
import re
import pymupdf
from shapely.affinity import affine_transform
from shapely.geometry import LineString,box,shape,mapping
from .drawing_components import split_page
from .architectural_interpretation import wall_bands_from_components
from .drawing_geometry import extract_page
from .drawing_page_tools import native_to_render_pixels

VERSION='wing-source-segment-partition-review-v1'
LITERAL_VERSION='wing-source-segment-partition-review-v2'


def derive(parents,matrix,factor,scope,*,max_segments=4096,literal_index=None):
    if type(max_segments) is not int or not 1<=max_segments<=4096 or len(matrix)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in matrix):
        raise ValueError('Bounded source segment review required')
    if type(factor) not in (int,float) or not math.isfinite(factor) or factor<=0:raise ValueError('Finite source scale required')
    components=split_page(parents);segments=[];used={};version=LITERAL_VERSION if literal_index is not None else VERSION
    for component in sorted(components,key=lambda c:c['id']):
        if (literal_index is None and component.get('curve_approximation',{}).get('cubic_segments')) or component.get('paint_reference_truncated'):continue
        paints=component.get('paint_references',[])
        if not paints or any(not re.fullmatch(r'\s*(?:\[\s*\]\s*0(?:\.0*)?)?\s*',str(p.get('stroke_style',{}).get('dashes_pdf','unknown'))) for p in paints):continue
        g=shape(component['geometry']);chains=[g.coords] if g.geom_type=='LineString' else [g.exterior.coords,*[r.coords for r in g.interiors]]
        for ring,chain in enumerate(chains):
            for index,(a,b) in enumerate(zip(chain,chain[1:])):
                line=LineString([a,b]);local=affine_transform(line,matrix)
                if line.length*factor<1.5 or not scope.covers(local):continue
                proofs=[]
                if literal_index is not None:
                    from .literal_path_edges import key
                    for paint in paints:proofs.extend(literal_index.get((paint['ordinal'],key(a,b)),[]))
                    if not proofs:continue
                if len(segments)>=max_segments:return {'version':version,'status':'segment_budget_withheld','bands':[],'segments':[],'source_components':[]}
                source={'component_id':component['id'],'component_contract':component['extraction_contract'],'ring_index':ring,'segment_index':index,'native_endpoints':[list(a),list(b)]}
                if literal_index is not None:source['literal_operator_proofs']=sorted(proofs,key=lambda p:(p['paint_ordinal'],p['item_index'],p['edge_index']))
                identifier=hashlib.sha256(json.dumps([version,source],sort_keys=True).encode()).hexdigest()
                record=copy.deepcopy(component);record.update(id=identifier,geometry=mapping(line),source_segment=source,
                    extraction_kind='wing_source_segments',extraction_version=version,
                    extraction_contract=hashlib.sha256(json.dumps([version,component['extraction_contract']]).encode()).hexdigest())
                if literal_index is not None:
                    record['parent_curve_approximation']=record['curve_approximation']
                    record['curve_approximation']={'cubic_segments':0,'chord_error_bound_pdf_points':0,'method':'original_literal_straight_operator'}
                segments.append(record);used[component['id']]=component
    bands,network=wall_bands_from_components(segments,factor,max_side_angle_sine=.01 if literal_index is not None else 1e-5)
    if network['status']!='paired_source_line_hints':bands=[]
    result={'version':version,'status':'source_partition_candidates_only','bands':[dict(b,local_geometry=mapping(affine_transform(shape(b['geometry']),matrix))) for b in bands],
            'segments':segments,'source_components':[used[k] for k in sorted(used)],'network':network,
            'height_application_verified':False,'physical_partition_identity_verified':False,'world_geometry_additions':0,
            'limitations':['Original paths, paint and coordinates remain unchanged; derived segments retain full original ring/segment references.',
                           'Whole source segments must lie inside the review scope; crossing segments are not clipped.',
                           'No closest band is selected and overlapping source-interval alternatives remain withheld.',
                           'Band pairing and review scope are drawing evidence, not physical wall identity or measured height.']}
    if literal_index is not None:result['source_side_angle_allowance_sine']=.01
    return result


def review(parent,plan_pdf,*,recover_mixed_paths=False,max_operator_items=200000):
    if type(recover_mixed_paths) is not bool:raise ValueError('Explicit mixed-path review flag required')
    spec=parent['source_frames']['plan']['specification'];path=Path(plan_pdf);raw=path.read_bytes()
    if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError('Plan source checksum changed')
    with pymupdf.open(stream=raw,filetype='pdf') as doc:
        page=doc[spec['page']-1];width=spec['render_width_pixels'];pix=page.get_pixmap(matrix=pymupdf.Matrix(width/page.rect.width,width/page.rect.width))
        if hashlib.sha256(pix.samples).hexdigest()!=spec['render_samples_sha256'] or [pix.width,pix.height]!=spec['render_size_pixels']:raise ValueError('Plan review raster changed')
        if spec['state']!='existing' or re.sub(r'\s+','',spec['caption']).lower() not in re.sub(r'\s+','',page.get_text()).lower():raise ValueError('Existing source caption required')
        t=native_to_render_pixels(page,width);pu=page.rect.width/width*spec['scale_denominator']*.0254/72
        a,b=parent['reviewed_traces']['plan']['facade_endpoints'];rear=parent['reviewed_traces']['plan']['rear_point']
        length=math.dist(a,b);u=[(b[i]-a[i])/length for i in (0,1)];dot=sum((rear[i]-a[i])*u[i] for i in (0,1))
        v=[rear[i]-a[i]-dot*u[i] for i in (0,1)];depth=math.hypot(*v);v=[n/depth for n in v]
        # Compose original native -> rendered pixels -> local metres, without fitting sheets.
        matrix=[pu*(u[0]*t[0]+u[1]*t[1]),pu*(u[0]*t[2]+u[1]*t[3]),
                pu*(v[0]*t[0]+v[1]*t[1]),pu*(v[0]*t[2]+v[1]*t[3]),
                pu*(u[0]*(t[4]-a[0])+u[1]*(t[5]-a[1])),pu*(v[0]*(t[4]-a[0])+v[1]*(t[5]-a[1]))]
        parents,extraction=extract_page(page,spec['sha256'],spec['page'],min_line_length_points=.25,max_candidates=10000,isolate_open_stroked_subpaths=True)
        scope=box(.1,.1,length*pu-.1,depth*pu-.1)
        literal_index=None;operator_report=None
        if recover_mixed_paths:
            from .literal_path_edges import extract
            literal_index,operator_report=extract(page,max_items=max_operator_items)
        if operator_report is not None and operator_report['status']!='original_straight_operators_only':
            result={'version':LITERAL_VERSION,'status':operator_report['status'],'bands':[],'segments':[],'source_components':[]}
        else:result=derive(parents,matrix,spec['scale_denominator']*.0254/72,scope,literal_index=literal_index) if extraction['status']=='unplaced_geometry_candidates' else {'version':VERSION,'status':'source_extraction_withheld','bands':[]}
        if operator_report is not None:result['literal_operator_review']=operator_report
        result.update(source_pdf_sha256=spec['sha256'],page=spec['page'],extraction=extraction,native_to_local_matrix=matrix,review_scope_local=mapping(scope))
    if path.read_bytes()!=raw:raise ValueError('Plan source changed during review')
    return result
