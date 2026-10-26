"""Source-authored solid and patterned fill regions and explicit paving-legend associations.

Direct page content only. Rendering masks, legend claims and physical surfaces
remain separate: this stage never supplies area-layout or world geometry.
"""
from collections import Counter
from concurrent.futures import CancelledError
import hashlib
import io
import json
import math
import re

import pymupdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream, IndirectObject, StreamObject
from shapely.geometry import box, mapping
from shapely.ops import unary_union

from .building_spec import digest
from .drawing_geometry import flatten_cubic
from .drawing_footprints import fill_geometry
from .drawing_page_tools import native_inverse

VERSION = 'planning-source-hatch-regions-v2'
LIMITS = {'max_content_bytes':16000000, 'max_operations':500000,
          'max_records':512, 'max_path_operators':20000, 'max_points':200000,
          'max_scan_operations':1000000, 'max_fill_rule_work':2000000, 'max_text_mask_checks':64000, 'max_resource_bytes':4000000, 'max_overlay_work':2000000, 'max_output_bytes':8000000}


def pattern_signature(reference, max_bytes=4000000):
    """Resolved appearance identity, including image bytes, palettes and masks.

    Translation changes tile phase, retained separately, not the repeated
    texture class. Linear pattern transforms remain part of the identity.
    """
    pattern=reference.get_object(); matrix=list(map(float,pattern.get('/Matrix',[1,0,0,1,0,0])))
    if (pattern.get('/PatternType')!=1 or pattern.get('/PaintType')!=1
            or len(matrix)!=6 or not all(math.isfinite(v) for v in matrix)
            or matrix[0]*matrix[3]-matrix[1]*matrix[2]==0):return None
    used=0;nodes=0
    def canonical(value, depth=0, ancestry=()):
        nonlocal used,nodes
        nodes+=1
        if depth>24 or nodes>10000:raise ValueError('Hatch resource structure budget exceeded')
        if isinstance(value,IndirectObject):
            key=(value.idnum,value.generation)
            if key in ancestry:raise ValueError('Cyclic hatch resource')
            return canonical(value.get_object(),depth+1,ancestry+(key,))
        if isinstance(value,dict):
            # Compression representation is irrelevant once bytes are decoded.
            data={str(k):canonical(v,depth+1,ancestry) for k,v in sorted(value.items())
                  if not isinstance(value,StreamObject) or k not in ('/Length','/Filter','/DecodeParms')}
            if isinstance(value,StreamObject):
                if value.get('/Subtype')=='/Image':
                    width=int(value.get('/Width',0));height=int(value.get('/Height',0))
                    bits=int(value.get('/BitsPerComponent',1))
                    if min(width,height,bits)<1 or width*height*bits>8*max_bytes:
                        raise ValueError('Hatch image decode budget exceeded')
                raw=value.get_data();used+=len(raw)
                if used>max_bytes:raise ValueError('Hatch resource byte budget exceeded')
                data['decoded_stream_sha256']=hashlib.sha256(raw).hexdigest()
            return data
        if isinstance(value,(list,tuple)):return [canonical(v,depth+1,ancestry) for v in value]
        if isinstance(value,bytes):
            used+=len(value)
            if used>max_bytes:raise ValueError('Hatch resource byte budget exceeded')
            return {'bytes_sha256':hashlib.sha256(value).hexdigest()}
        if isinstance(value,(int,float)):
            if not math.isfinite(float(value)):raise ValueError('Finite hatch resource number required')
            return float(value)
        if value is None or str(value)=='NullObject':return None
        text=str(value);used+=len(text.encode())
        if used>max_bytes:raise ValueError('Hatch resource byte budget exceeded')
        return text
    data=canonical(pattern)
    data['/Matrix']=matrix[:4]
    return {'appearance_sha256':digest(data),'pattern_matrix':matrix,'resource_bytes':used}


def recover(operations, resources, frame, *, limits=None, cancelled=lambda:False, include_solid_fills=False, fill_rule_styles=None):
    """Bounded native-coordinate interpreter for direct fill paint."""
    limits={**LIMITS,**(limits or {})}
    if len(operations)>limits['max_operations']:raise ValueError('Hatch operation budget exceeded')
    patterns=resources.get('/Pattern',{}); patterns=patterns.get_object() if hasattr(patterns,'get_object') else patterns; signatures={};resource_bytes=0
    if len(patterns)>256:raise ValueError('Hatch pattern resource budget exceeded')
    for name,value in patterns.items():
        if cancelled():raise CancelledError('Hatch review cancelled')
        signature=pattern_signature(value,limits['max_resource_bytes']-resource_bytes)
        if signature:resource_bytes+=signature['resource_bytes'];signatures[str(name)]=signature
    ctm=pymupdf.Matrix(1,0,0,1,0,0);pattern=None;cs='/DeviceGray';solid=[0.];safe=True;fill_alpha=1.;clips=[];stack=[]
    path=[];current=start=None;pending=None;records=[];counts=Counter();points=0;overlay_work=0;unsupported=[];fill_work={'checks':0};last_resolution='simple_source_rings'
    def nums(args,n):
        if len(args)!=n or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) for v in args):
            raise ValueError('Finite exact hatch operands required')
        return list(map(float,args))
    def point(args):return list(pymupdf.Point(*nums(args,2))*ctm)
    def geometry(even_odd,resolve_complex=False):
        nonlocal points,last_resolution
        last_resolution='simple_source_rings'
        rings=[];ring=[]
        def charge(n):
            nonlocal points
            points+=n
            if points>limits['max_points']:raise ValueError('Hatch point budget exceeded')
        def flush():
            nonlocal ring
            if ring:
                if ring[0]!=ring[-1]:charge(1);ring.append(ring[0])
                if len(ring)>=2:rings.append(ring)
                ring=[]
        for row in path:
            op=row['operator'];p=row['points']
            if op=='m':flush();charge(1);ring=[p[0]]
            elif op=='l':
                if not ring:charge(1);ring=[p[0]]
                charge(1);ring.append(p[-1])
            elif op=='c':
                if not ring:charge(1);ring=[p[0]]
                curve,_=flatten_cubic(p,.05,max_points=min(10000,limits['max_points']-points+1))
                charge(len(curve)-1);ring.extend(curve[1:])
            elif op=='h':flush()
            else:raise ValueError('Unsupported hatch path operator')
        flush()
        if not rings:raise ValueError('Empty hatch path')
        if len(rings)>256:raise ValueError('Hatch ring budget exceeded')
        from shapely.geometry import Polygon
        if any(len(r)<4 or not Polygon(r).is_valid or Polygon(r).area<=0 for r in rings):
            if not resolve_complex:raise ValueError('Invalid hatch ring')
            g=_source_fill_arrangement(rings,even_odd,fill_work,limits['max_fill_rule_work'])
            last_resolution='source_fill_rule_arrangement'
        else:g=fill_geometry(rings,even_odd,True)
        if g.is_empty or not g.is_valid or g.geom_type not in ('Polygon','MultiPolygon'):raise ValueError('Invalid hatch topology')
        return g
    for index,(args,op) in enumerate(operations):
        if index%256==0 and cancelled():raise CancelledError('Hatch review cancelled')
        if op==b'q':
            if len(stack)>=64:raise ValueError('Hatch graphics depth budget exceeded')
            stack.append((pymupdf.Matrix(ctm),pattern,cs,list(solid) if solid is not None else None,safe,fill_alpha,list(clips)))
        elif op==b'Q':
            if not stack:raise ValueError('Unbalanced hatch graphics scopes')
            ctm,pattern,cs,solid,safe,fill_alpha,clips=stack.pop()
        elif op==b'cm':
            ctm=pymupdf.Matrix(*nums(args,6))*ctm
            if not all(math.isfinite(v) for v in ctm) or ctm.a*ctm.d-ctm.b*ctm.c==0:raise ValueError('Finite nonsingular hatch transform required')
        elif op==b'gs':
            states=resources.get('/ExtGState',{}); states=states.get_object() if hasattr(states,'get_object') else states
            state=states.get(str(args[0])) if len(args)==1 else None
            if state is None:safe=False
            else:
                state=state.get_object()
                allowed={'/Type','/CA','/ca','/BM','/SMask','/AIS','/SA','/OP','/op','/OPM'}
                fill_alpha=float(state.get('/ca',fill_alpha))
                safe=safe and not(set(state)-allowed) and math.isfinite(fill_alpha) and 0<fill_alpha<=1 and state.get('/BM','/Normal')=='/Normal' and state.get('/SMask','/None')=='/None' and not getattr(state.get('/OP',False),'value',state.get('/OP',False)) and not getattr(state.get('/op',False),'value',state.get('/op',False))
        elif op in (b'BDC',b'BMC'):safe=False
        elif op==b'cs':
            cs=str(args[0]) if len(args)==1 else None;pattern=None
            solid={'/DeviceGray':[0.],'/DeviceRGB':[0.,0.,0.],'/DeviceCMYK':[0.,0.,0.,1.]}.get(cs)
        elif op in (b'rg',b'g',b'k'):
            cs={b'rg':'/DeviceRGB',b'g':'/DeviceGray',b'k':'/DeviceCMYK'}[op]
            solid=nums(args,{'/DeviceRGB':3,'/DeviceGray':1,'/DeviceCMYK':4}[cs]);pattern=None
            if any(not 0<=v<=1 for v in solid):solid=None
        elif op in (b'scn',b'sc'):
            pattern=str(args[0]) if cs=='/Pattern' and len(args)==1 else None
            components={'/DeviceRGB':3,'/DeviceGray':1,'/DeviceCMYK':4}.get(cs)
            solid=nums(args,components) if components is not None and len(args)==components and all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in args) else None
            if solid is not None and any(not 0<=v<=1 for v in solid):solid=None
        elif op==b'm':current=start=point(args);path.append({'operator':'m','points':[current],'index':index})
        elif op==b'l':
            end=point(args)
            if current is None:raise ValueError('Hatch line without current point')
            path.append({'operator':'l','points':[current,end],'index':index});current=end
        elif op in (b'c',b'v',b'y'):
            if current is None:raise ValueError('Hatch curve without current point')
            n=nums(args,6 if op==b'c' else 4)
            a=point(n[:2]);b=point(n[2:4]);end=point(n[4:]) if op==b'c' else b
            controls=[current,a,b,end] if op==b'c' else [current,current,a,end] if op==b'v' else [current,a,end,end]
            path.append({'operator':'c','original_operator':op.decode(),'points':controls,'index':index});current=end
        elif op==b're':
            x,y,w,h=nums(args,4);p=[point(v) for v in ([x,y],[x+w,y],[x+w,y+h],[x,y+h])]
            path.append({'operator':'m','points':[p[0]],'index':index})
            path.extend({'operator':'l','points':[a,b],'index':index} for a,b in zip(p,p[1:]+p[:1]))
            path.append({'operator':'h','points':[],'index':index});current=start=p[0]
        elif op==b'h':
            if current is None:raise ValueError('Hatch close without current point')
            path.append({'operator':'h','points':[],'index':index});current=start
        elif op in (b'W',b'W*'):pending=(op==b'W*',index)
        elif op in (b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'S',b's',b'n'):
            is_fill=op in (b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*')
            signature=signatures.get(pattern)
            paint_kind='pattern'
            if signature is None and include_solid_fills and solid is not None and cs in ('/DeviceRGB','/DeviceGray','/DeviceCMYK'):
                paint_kind='solid'
                signature={'appearance_sha256':digest(['solid_device_colour',cs,solid]),
                    'solid_colour_space':cs,'solid_colour_components':list(solid)}
            if is_fill and signature is not None:
                if not safe or any(c['geometry'] is None for c in clips):counts['unsupported_graphics_or_clip_scope']+=1;counts['unsafe_graphics' if not safe else 'invalid_clip']+=1
                else:
                    try:g=geometry(op in (b'f*',b'B*',b'b*'),
                        (signature['appearance_sha256'],fill_alpha) in (fill_rule_styles or set()))
                    except ValueError as e:
                        if 'budget' in str(e):raise
                        counts[str(e)]+=1;g=None
                        unsupported.append({'paint_operation_index':index,'paint_kind':paint_kind,
                            'reason':str(e),'source_path_operator_count':len(path),'fill_opacity':fill_alpha,**signature})
                        if len(unsupported)>limits['max_records']:raise ValueError('Withheld source fill budget exceeded')
                    if g is not None:
                        def vertices(geometry):
                            return sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors)
                                for p in (list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry])
                                if p.geom_type=='Polygon')
                        visible=g
                        for boundary in [box(*frame)]+[clip['geometry'] for clip in clips]:
                            overlay_work+=vertices(visible)*vertices(boundary)
                            if overlay_work>limits['max_overlay_work']:raise ValueError('Hatch overlay work budget exceeded')
                            visible=visible.intersection(boundary)
                        if not visible.is_empty and visible.is_valid and visible.geom_type in ('Polygon','MultiPolygon'):
                            records.append({'paint_operation_index':index,'paint_kind':paint_kind,'pattern_resource':pattern if paint_kind=='pattern' else None,
                                'fill_opacity':fill_alpha,'fill_rule_resolution':last_resolution,**signature,
                                'source_operators':list(path),'fill_even_odd':op in (b'f*',b'B*',b'b*'),
                                'clip_operation_indices':[c['index'] for c in clips],
                                'clip_references':[{'operation_index':c['index'],'source_operators':c['source_operators'],
                                    'even_odd':c['even_odd']} for c in clips],
                                'geometry':json.loads(json.dumps(mapping(visible))),
                                'source_fill_geometry':json.loads(json.dumps(mapping(g))),
                                'source_geometry_intersected':not g.equals(visible),
                                'curved_operators':sum(p['operator']=='c' for p in path)})
                            if len(records)>limits['max_records']:raise ValueError('Hatch record budget exceeded')
            if pending is not None:
                try:clip=geometry(pending[0])
                except ValueError as e:
                    if 'budget' in str(e):raise
                    counts['clip_'+str(e)]+=1;clip=None
                clips.append({'geometry':clip,'index':pending[1],'source_operators':list(path),'even_odd':pending[0]})
                if len(clips)>16:raise ValueError('Hatch clipping depth budget exceeded')
            path=[];current=start=None;pending=None
        elif op==b'Do':counts['uninterpreted_xobject_invocations']+=1
        if len(path)>limits['max_path_operators']:raise ValueError('Hatch path operator budget exceeded')
    if stack or pending is not None:raise ValueError('Unbalanced hatch source state')
    return records,{'counts':dict(counts),'flattened_point_work':points,'resource_byte_work':resource_bytes,'operations':len(operations),'overlay_work':overlay_work,'withheld_source_fills':unsupported,'fill_rule_work':fill_work['checks']}




def _source_fill_arrangement(rings,even_odd,work,limit):
    """Resolve the source fill rule over its original flattened edge walks.

    Retraced edges keep their winding multiplicity. No buffer repair, endpoint
    snapping, polygon hull or invented bridge supplies a missing boundary.
    """
    from shapely.geometry import LineString
    from shapely.ops import polygonize
    edges=[(a,b) for ring in rings for a,b in zip(ring,ring[1:]) if a!=b]
    work['checks']+=len(edges)**2
    if work['checks']>limit:raise ValueError('Source fill-rule arrangement budget exceeded')
    faces=list(polygonize(unary_union([LineString([a,b]) for a,b in edges])))
    retained=[]
    for face in faces:
        work['checks']+=len(edges)
        if work['checks']>limit:raise ValueError('Source fill-rule winding budget exceeded')
        point=face.representative_point();x,y=point.x,point.y;winding=0
        for a,b in edges:
            cross=(b[0]-a[0])*(y-a[1])-(x-a[0])*(b[1]-a[1])
            if a[1]<=y<b[1] and cross>0:winding+=1
            elif b[1]<=y<a[1] and cross<0:winding-=1
        inside=(winding%2!=0) if even_odd else (winding!=0)
        if inside:retained.append(face)
    return unary_union(retained)

def _text_background(record,runs,contexts,inverse,tree,native_boxes,check,work,limit):
    """Withhold source-sized annotation backplates, including rotated/L masks.

    This correspondence only withholds a physical role. It cannot accept a
    paving region, infer a label role, or supply geometry from text extents.
    """
    if record['paint_kind']!='solid' or record['curved_operators']:return None
    from shapely.geometry import shape
    g=shape(record['geometry'])
    lines=[p['points'] for p in record['source_operators'] if p['operator']=='l']
    orthogonal=bool(lines) and all(a[0]==b[0] or a[1]==b[1] for a,b in lines)
    near_rectangle=(g.geom_type=='Polygon' and not g.interiors and len(g.exterior.coords)==5
        and g.area>=.98*g.minimum_rotated_rectangle.area)
    if not orthogonal and not near_rectangle:return None
    selected=[];expanded=box(*g.bounds).buffer(2);support=g.buffer(2)
    for position in tree.query(expanded):
        check();work['checks']+=1
        if work['checks']>limit:raise ValueError('Solid text-background comparison budget exceeded')
        i=int(position)
        if expanded.covers(native_boxes[i]) and support.covers(native_boxes[i].centroid):selected.append(i)
    if not selected:return None
    bounds=unary_union([native_boxes[i] for i in selected]).bounds
    if max(abs(a-b) for a,b in zip(g.bounds,bounds))>2:return None
    return {'status':'source_text_background_fill_withheld','scope':'source text/backplate correspondence for withholding only',
        'maximum_native_bounds_difference_pdf_points':2,
        'source_text_runs':[{'trace_indices':runs[i]['trace_indices'],
            'character_indices':runs[i]['character_indices']} for i in selected],
        'native_text_bounds':list(bounds),'native_backplate_bounds':list(g.bounds),
        'physical_role_inferred':False}


def page_review(page, sha, number, *, options=None, cancelled=lambda:False):
    """Recover original hatch regions; legend transfer remains a review claim."""
    options={} if options is None else options
    if not isinstance(options,dict) or set(options)-set(LIMITS):raise ValueError('Known hatch limits required')
    limits={**LIMITS,**options}
    if any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in limits.items()):raise ValueError('Lower-only hatch limits required')
    if not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or type(number) is not int or number!=page.number+1:
        raise ValueError('Original hash and matching hatch page required')
    result={'version':VERSION,'document_sha256':sha,'page':number,'coordinate_frame':'pdf_native_points_y_up',
        'scope':'supported direct-page pattern and solid fills; form descendants and later visibility unverified',
        'limits':limits,'analysis_complete':True,'status':'source_hatch_region_review',
        'records':[],'legends':[],'curve_tolerance_pdf_points':.05,
        'physical_identity_verified':False,'topology_against_exact_curves_verified':False,
        'later_overpaint_visibility_verified':False,
        'scale_verified':False,'registration_verified':False,'world_placement_eligible':False,
        'world_geometry_additions':0,'training_labels_generated':0}
    def fail(reason):
        result.update(analysis_complete=False,status='source_hatch_region_review_withheld',reason=str(reason)[:512],records=[],legends=[])
        result.pop('summary',None)
        return result
    if cancelled():raise CancelledError('Hatch review cancelled')
    content=page.read_contents();pin=hashlib.sha256(content).hexdigest();result['source_content_sha256']=pin
    if len(content)>limits['max_content_bytes']:return fail('Hatch content byte budget exceeded')
    try:
        raw=page.parent.tobytes()
        if len(raw)>24000000:return fail('Hatch document byte budget exceeded')
        reader=PdfReader(io.BytesIO(raw));source=reader.pages[number-1]
        resources=source.get('/Resources',{});resources=resources.get_object() if hasattr(resources,'get_object') else resources
        if (page.cropbox!=page.mediabox or page.mediabox.x0!=0 or page.mediabox.y0!=0
                or float(source.get('/UserUnit',1))!=1):return fail('Uncropped standard native hatch page required')
        operations=ContentStream(source.get_contents(),reader).operations
        if len(operations)>limits['max_scan_operations']:return fail('Source fill scan budget exceeded')
        if cancelled():raise CancelledError('Hatch review cancelled')
        records,work=recover(operations,resources,list(map(float,source.mediabox)),limits=limits,cancelled=cancelled,include_solid_fills=True)
        result['work']=work
        from . import ordinary_surfaces, glyph_visibility, planning_outline_semantics
        traces=page.get_texttrace()
        if len(traces)>10000 or sum(len(t['chars']) for t in traces)>200000:return fail('Hatch text budget exceeded')
        inverse=native_inverse(page);legends=[]
        runs=ordinary_surfaces.label_runs(traces)
        def check():
            if cancelled():raise CancelledError('Hatch review cancelled')
        contexts=planning_outline_semantics.AnnotationContexts(page,runs,planning_outline_semantics.LIMITS,check)
        for run in runs:
            if cancelled():raise CancelledError('Hatch review cancelled')
            text=''.join(chr(c[0]) for c in run['chars']).strip()
            if not re.match(r'^(New|Existing)(?:\s|$)',text,re.I):continue
            seed=contexts.positions[contexts.key(run)];found=set();pending=[seed]
            while pending:
                i=pending.pop()
                if i in found:continue
                found.add(i)
                if len(found)>32:raise ValueError('Hatch legend part budget exceeded')
                pending.extend(j for j in contexts.neighbours(i) if j not in found)
            ordered=sorted(found,key=lambda i:runs[i]['bbox'][0])
            text=' '.join(''.join(chr(c[0]) for c in runs[i]['chars']).strip() for i in ordered)
            match=re.fullmatch(r'(New|Existing) Paving with levels',text,re.I)
            if not match:continue
            context=contexts.review(run)
            if context and context['ambiguous_adjacency']:continue
            if len(legends)>=32:return fail('Hatch legend budget exceeded')
            screen=glyph_visibility.screen_architectural_span(page,run,zoom=24 if run['size']<4 else 6)
            bounds=list(pymupdf.Rect(run['bbox'])*inverse)
            if context:
                from shapely.geometry import shape
                bounds=list(unary_union([shape(p['geometry_pdf_native']) for p in context['parts']]).bounds)
                screen={'status':'raster_consistent_candidate' if context['all_parts_visible'] else 'whole_legend_visibility_withheld'}
            legend={'text':text,'printed_state':match[1].lower(),'native_bounds':bounds,
                'trace_indices':run['trace_indices'],'character_indices':run['character_indices'],'glyph_screen':screen,
                'status':'withheld_no_unique_visible_fill_swatch'}
            if context:legend['original_parts']=context['parts']
            if screen['status']=='raster_consistent_candidate':
                x0,y0,x1,y1=bounds;swatches=[]
                from shapely.geometry import shape
                for index,r in enumerate(records):
                    a,b,c,d=shape(r['geometry']).bounds
                    if 0<=x0-c<=100 and max(b,y0)<min(d,y1) and 20<=c-a<=120 and 10<=d-b<=60:
                        swatches.append(index)
                if len(swatches)==1:
                    i=swatches[0];legend.update(status='visible_legend_fill_association',
                        swatch_record_index=i,appearance_sha256=records[i]['appearance_sha256'],fill_opacity=records[i]['fill_opacity'],
                        swatch_paint_operation_index=records[i]['paint_operation_index'])
            legends.append(legend)
        # Duplicate or contradictory keys do not independently authorize transfer.
        grouped={}
        for legend in legends:
            if legend['status']=='visible_legend_fill_association':grouped.setdefault((legend['appearance_sha256'],legend['fill_opacity']),[]).append(legend)
        supported_styles={key for key,claims in grouped.items() if len(claims)==1}
        unresolved_styles={(r['appearance_sha256'],r.get('fill_opacity',1.))
            for r in work['withheld_source_fills']}
        if supported_styles & unresolved_styles:
            if 2*len(operations)>limits['max_scan_operations']:return fail('Source fill scan budget exceeded')
            first_work=work
            remaining={**limits,
                'max_points':limits['max_points']-first_work['flattened_point_work'],
                'max_overlay_work':limits['max_overlay_work']-first_work['overlay_work'],
                'max_resource_bytes':limits['max_resource_bytes']-first_work['resource_byte_work']}
            records,work=recover(operations,resources,list(map(float,source.mediabox)),
                limits=remaining,cancelled=cancelled,include_solid_fills=True,fill_rule_styles=supported_styles)
            for key in ('flattened_point_work','overlay_work','resource_byte_work'):
                work[key]+=first_work[key]
            work.update(source_passes=2,scan_operations=2*len(operations))
            result['work']=work
            by_paint={r['paint_operation_index']:i for i,r in enumerate(records)}
            for legend in legends:
                if 'swatch_paint_operation_index' in legend:
                    legend['swatch_record_index']=by_paint[legend['swatch_paint_operation_index']]
        else:
            if len(operations)>limits['max_scan_operations']:return fail('Source fill scan budget exceeded')
            work.update(source_passes=1,scan_operations=len(operations))
        from shapely.geometry import shape
        visible_keys=[l for l in legends if l['status']=='visible_legend_fill_association']
        key_geometry=unary_union([unary_union([box(*l['native_bounds']),
            shape(records[l['swatch_record_index']]['geometry'])]) for l in visible_keys])
        first_swatch=min((l['swatch_paint_operation_index'] for l in visible_keys),default=-1)
        backplates=[r for r in records if r['paint_kind']=='solid'
            and r['solid_colour_space'] in ('/DeviceRGB','/DeviceGray')
            and all(v==1 for v in r['solid_colour_components']) and r['fill_opacity']==1
            and r['paint_operation_index']<first_swatch and not key_geometry.is_empty
            and shape(r['geometry']).covers(key_geometry)]
        result['legend_backplates']=[{'paint_operation_index':r['paint_operation_index'],
            'geometry_sha256':digest(r['geometry']),'scope':'opaque source legend backplate only'} for r in backplates]
        from shapely.strtree import STRtree
        native_boxes=[box(*(pymupdf.Rect(run['bbox'])*inverse)) for run in runs]
        text_tree=STRtree(native_boxes);mask_work={'checks':0}
        for r in records:
            claims=grouped.get((r['appearance_sha256'],r['fill_opacity']),[])
            claim=claims[0] if len(claims)==1 else None
            background=(_text_background(r,runs,contexts,inverse,text_tree,native_boxes,check,mask_work,limits['max_text_mask_checks'])
                if claim and r['paint_operation_index']!=claim['swatch_paint_operation_index'] else None)
            r.update(id=digest([VERSION,sha,number,r]),physical_identity_verified=False,
                later_overpaint_visibility_verified=False,world_placement_eligible=False,
                status='unclassified_source_fill_region',legend_claim=None)
            if background:
                r.update(status='source_text_background_fill_withheld',text_background_evidence=background)
            if not background and claim and r['paint_operation_index']!=claim['swatch_paint_operation_index']:
                # Require separation from the full legend and its swatch, rather
                # than turning nearby keys/title graphics into park geometry.
                from shapely.geometry import shape
                g=shape(r['geometry']);swatch_left=shape(records[claim['swatch_record_index']]['geometry']).bounds[0]
                masks=[p for p in backplates if p['paint_operation_index']>r['paint_operation_index']]
                plan_side=g.bounds[2]<swatch_left
                crossing_plan=g.bounds[0]<swatch_left and bool(masks)
                if plan_side or crossing_plan:
                    if masks:
                        mask=unary_union([shape(p['geometry']) for p in masks])
                        vertices=sum(len(p['source_operators']) for p in masks)
                        result['work']['overlay_work']+=len(r['source_operators'])*vertices
                        if result['work']['overlay_work']>limits['max_overlay_work']:return fail('Legend backplate overlay budget exceeded')
                        reviewed=g.difference(mask)
                        if reviewed.is_empty:continue
                        if not reviewed.equals(g):r.update(review_geometry=json.loads(json.dumps(mapping(reviewed))),
                            legend_backplate_occlusion={'scope':'review display only; not physical terrain',
                                'source_mask_paint_indices':[p['paint_operation_index'] for p in masks]})
                    r.update(status='legend_associated_paving_region_for_review',legend_claim={
                        'text':claim['text'],'printed_state':claim['printed_state'],'source_legend_sha256':digest(claim),
                        'legend_trace_indices':claim['trace_indices'],
                        'legend_character_indices':claim['character_indices'],
                        'swatch_paint_operation_index':claim['swatch_paint_operation_index'],
                        'appearance_sha256':claim['appearance_sha256'],
                        'material':None,'physical_surface_accepted':False})
        result['work']['text_mask_checks']=mask_work['checks']
        if hashlib.sha256(page.read_contents()).hexdigest()!=pin:return fail('Original hatch content changed')
        result.update(records=records,legends=legends,summary={
            'source_hatch_regions':sum(r['paint_kind']=='pattern' for r in records),
            'legend_associated_paving_regions':sum(r['legend_claim'] is not None for r in records),
            'curved_paving_regions':sum(r['legend_claim'] is not None and r['curved_operators']>0 for r in records)})
        recovered=sum(r['fill_rule_resolution']=='source_fill_rule_arrangement' for r in records)
        if recovered:result['summary']['source_fill_rule_regions_recovered']=recovered
        solid_count=sum(r['paint_kind']=='solid' for r in records)
        if solid_count:
            result['summary'].update(source_solid_fill_regions=solid_count,
                text_background_fills_withheld=sum('text_background_evidence' in r for r in records),
                existing_paving_regions=sum(r['legend_claim'] is not None and r['legend_claim']['printed_state']=='existing' for r in records),
                proposed_paving_regions=sum(r['legend_claim'] is not None and r['legend_claim']['printed_state']=='new' for r in records))
        if len(json.dumps(result,allow_nan=False).encode())>limits['max_output_bytes']:return fail('Hatch output byte budget exceeded')
        return result
    except (ValueError,RuntimeError,KeyError,TypeError,IndexError,OverflowError,PdfReadError) as error:return fail(error)


def write_overlay(review, preview, destination):
    """Original-page preview with hatch outlines, no acceptance or metric scale."""
    if not review or not review['analysis_complete'] or not review['records']:return None
    from pathlib import Path
    import base64
    from shapely.geometry import shape
    from shapely.affinity import affine_transform
    a,b,c,d,e,f=preview['pdf_native_to_pixels']
    width,height=preview['size_pixels']
    background=Path(destination).parent/preview['file']
    paths=[]
    for r in review['records']:
        if r.get('paint_kind')=='solid' and not r['legend_claim']:continue
        g=affine_transform(shape(r.get('review_geometry',r['geometry'])),[a,c,b,d,e,f])
        colour='#00aaee' if r['legend_claim'] else '#b88020'
        paths.append(g.svg(scale_factor=.4,fill_color=colour,opacity=.3))
    data=('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width} {height}"><image width="100%" height="100%" '
        'xlink:href="data:image/png;base64,'+base64.b64encode(background.read_bytes()).decode()+'"/>'+''.join(paths)+'</svg>').encode()
    if len(data)>16000000:raise ValueError('Hatch overlay byte budget exceeded')
    Path(destination).write_bytes(data)
    return {'file':Path(destination).name,'sha256':hashlib.sha256(data).hexdigest(),**review['summary']}
