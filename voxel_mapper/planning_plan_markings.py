"""Source-reviewed plan markings; no general track or building recognition claim."""
from concurrent.futures import CancelledError
import hashlib
import json
import math
from pathlib import Path

import pymupdf
from shapely.geometry import LineString,MultiLineString,Polygon,Point,mapping,shape

from .building_spec import digest
from .drawing_page_tools import native_inverse
from . import drawing_geometry,planning_curved_boundaries

VERSION='planning-reviewed-plan-markings-v1'
PROFILE_PATH=Path(__file__).with_name('data')/'wicker-plan-markings.json'
LIMITS={'max_drawings':100000,'max_source_operators':100000,'max_points':200000,'max_output_bytes':16000000,'max_raster_steps':1000000}
MATERIALS={'track_centre':'orange_wool','track_sides':'blue_wool','support_boundaries':'brown_wool','building_boundary':'light_blue_concrete','theming_envelope':'purple_wool','queue_below_annotation':'yellow_wool','queue_area':'stone_bricks'}


def profile():
    p=json.loads(PROFILE_PATH.read_text())
    if (p.get('version')!='reviewed-wicker-marking-source-v1' or p.get('origin')!='source_review_for_user_marking_instruction'
            or p.get('side_marking_offset_blocks')!=1 or p.get('side_offset_is_source_measurement') is not False
            or not {'building_boundary','track_centre','support_boundaries'}<={f['role'] for f in p['features']}<=set(MATERIALS)):
        raise ValueError('Supported reviewed plan-marking profile required')
    return p


def _capture(page,preset,*,cancelled=lambda:False):
    """Capture complete selected paint groups; never repair their endpoints."""
    def check():
        if cancelled():raise CancelledError('Plan marking extraction cancelled')
    check();paths=page.get_drawings();inverse=native_inverse(page)
    if len(paths)>LIMITS['max_drawings']:raise ValueError('Plan marking drawing budget exceeded')
    operators=points=0;features=[];note_cache={}
    for specification in preset['features']:
        check();selector=specification['selector'];note=None
        if 'annotation' in specification:
            from .planning_theming_notes import capture
            note=capture(page,specification['annotation']['trace_indices'],cancelled=cancelled,cache=note_cache)
        if 'annotation_anchor' in selector:
            indices=[]
        elif 'ordinals' in selector:
            indices=selector['ordinals']
            if any(type(i) is not int or not 0<=i<len(paths) for i in indices):raise ValueError('Source marking paint is absent')
        else:
            indices=[i for i,p in enumerate(paths) if p['type']=='s' and list(p.get('color') or [])==selector['stroke']
                and p.get('width')==selector['width'] and p.get('dashes')==selector['dashes']]
        geometries=[];witnesses=[]
        for i in indices:
            check();path=paths[i]
            if (path.get('layer') or ('s' in path['type'] and path.get('stroke_opacity',1)!=1)
                    or ('f' in path['type'] and path.get('fill_opacity',1)!=specification.get('source_fill_opacity',1))):
                raise ValueError('Reviewed marking opacity or layer changed')
            operators+=len(path['items'])
            if operators>LIMITS['max_source_operators']:raise ValueError('Plan marking operator budget exceeded')
            ops=planning_curved_boundaries._operators(path,inverse)
            witnesses.append([i,path.get('seqno'),path['type'],ops])
            parts,approx=drawing_geometry.subpaths(path,inverse,{'curve_tolerance_points':.05,'max_points':20000})
            if approx['cubic_segments'] and not specification.get('allow_source_curves'):raise ValueError('Reviewed straight-facet marking profile required')
            for part in parts:
                points+=len(part)
                if points>LIMITS['max_points']:raise ValueError('Plan marking point budget exceeded')
                if specification.get('filled_boundary') or specification.get('filled_area'):
                    if 'f' not in path['type']:raise ValueError('Original filled boundary required')
                    g=Polygon(part)
                    if not g.is_valid or g.is_empty:raise ValueError('Valid original filled boundary required')
                    geometries.append(g if specification.get('filled_area') else LineString(g.exterior.coords))
                elif len(part)>1:geometries.append(LineString(part))
        if 'annotation_anchor' in selector:
            if note is None:raise ValueError('Visible queue-below note required')
            parts=[r for r in note['parts'] if r['trace_indices']==[selector['annotation_anchor']]]
            if len(parts)!=1 or not note['claim']['queueing_below_stated']:raise ValueError('Exact queue-below annotation anchor required')
            geometries=[shape(parts[0]['geometry_pdf_native']).centroid];points+=1
            witnesses=[['annotation_anchor',selector['annotation_anchor'],note['source_annotation_sha256']]]
        if not geometries:raise ValueError('Complete selected marking geometry required')
        g=geometries[0] if len(geometries)==1 else MultiLineString(geometries)
        geometry=json.loads(json.dumps(mapping(g)))
        features.append({'id':digest([VERSION,preset['document_sha256'],preset['page'],specification['key'],geometry]),
            'key':specification['key'],'label':specification['label'],'role':specification['role'],
            'material':MATERIALS[specification['role']],'geometry_pdf_native':geometry,
            'source_paint_groups':len(indices),'source_paint_witnesses_sha256':digest(witnesses),
            'source_selection_sha256':digest(selector),'geometry_sha256':digest(geometry),
            'physical_identity_verified':False,'height_reconstruction_eligible':False})
        if specification['role']=='queue_area':
            if note is None or not note['claim']['queueing_below_stated']:raise ValueError('Queue-below source claim required for queue area')
            features[-1]['queue_area_context']=specification['queue_area_context']
        if note is not None:
            features[-1]['semantic_evidence']=note
            features[-1]['source_annotation_sha256']=note['source_annotation_sha256']
        if specification.get('allow_source_curves'):
            features[-1]['curve_tolerance_pdf_points']=.05
    return features,{'source_operators':operators,'points':points,'raw_drawings':len(paths)}


def page_review(page,sha,number,*,cancelled=lambda:False):
    preset=profile();result={'version':VERSION,'document_sha256':sha,'page':number,
        'coordinate_frame':'pdf_native_points_y_up','analysis_complete':True,'records':[],
        'status':'no_reviewed_source_profile','profile_sha256':digest(preset),
        'source_content_sha256':hashlib.sha256(page.read_contents()).hexdigest(),
        'physical_identity_verified':False,'world_placement_eligible':False,'model_weights_updated':False,
        'training_labels_generated':0,'limits':dict(LIMITS)}
    if cancelled():raise CancelledError('Plan marking review cancelled')
    if (sha,number)!=(preset['document_sha256'],preset['page']):return result
    try:
        if page.number+1!=number or result['source_content_sha256']!=preset['source_content_sha256']:
            raise ValueError('Reviewed original marking page changed')
        records,work=_capture(page,preset,cancelled=cancelled)
        result.update(records=records,work=work,status='reviewed_source_markings',
            side_marking_offset_blocks=preset['side_marking_offset_blocks'],side_offset_is_source_measurement=False,
            limitations=['Games and toilet/arcade outlines are source-reviewed 2D markings, not verified building exteriors.',
                'Original toilet wall gaps/openings are retained; no closed footprint is invented.',
                'Orange follows the original faceted ride alignment; brown follows original support-frame and post outlines.',
                'Blue sides are one-block display offsets from the centre line, not measured rail edges.',
                'This pinned Wicker drawing profile is not a general autonomous ride-layout extractor.',
                'No ride height, track crossing level, supports in 3D, terrain registration or model training is inferred.'])
        validate_review(result,sha,number)
        if hashlib.sha256(page.read_contents()).hexdigest()!=preset['source_content_sha256']:raise ValueError('Original marking page changed')
        if len(json.dumps(result,separators=(',',':'),allow_nan=False).encode())>LIMITS['max_output_bytes']:raise ValueError('Marking review byte budget exceeded')
    except (ValueError,RuntimeError,KeyError,TypeError,OverflowError) as error:
        result.update(analysis_complete=False,status='plan_markings_withheld',records=[],reason=str(error)[:512])
    return result


def validate_review(value,sha,number):
    preset=profile()
    if isinstance(value,dict) and value.get('profile_sha256')!=digest(preset):
        for name in ('wicker-plan-markings-v1.json','wicker-plan-markings-v2.json'):
            path=PROFILE_PATH.with_name(name)
            if not path.is_file():continue
            legacy=json.loads(path.read_text())
            if value.get('profile_sha256')==digest(legacy):preset=legacy;break
    if (not isinstance(value,dict) or value.get('version')!=VERSION or not value.get('analysis_complete')
            or (value.get('document_sha256'),value.get('page'))!=(sha,number)
            or (sha,number)!=(preset['document_sha256'],preset['page'])
            or value.get('source_content_sha256')!=preset['source_content_sha256']
            or value.get('profile_sha256')!=digest(preset) or value.get('side_marking_offset_blocks')!=1
            or value.get('side_offset_is_source_measurement') is not False
            or len(value.get('records',[]))!=len(preset['features'])):
        raise ValueError('Pinned reviewed-source markings required')
    for row,specification in zip(value['records'],preset['features']):
        expected=specification['expected'];g=shape(row['geometry_pdf_native'])
        if (g.geom_type not in (('Point',) if specification['role']=='queue_below_annotation' else ('Polygon',) if specification['role']=='queue_area' else ('LineString','MultiLineString')) or g.is_empty or not g.is_valid or g.has_z
                or not all(math.isfinite(v) for v in g.bounds)
                or any(row.get(k)!=v for k,v in {'key':specification['key'],'label':specification['label'],
                    'role':specification['role'],'material':MATERIALS[specification['role']],
                    'source_selection_sha256':digest(specification['selector']),**expected}.items())
                or digest(row['geometry_pdf_native'])!=expected['geometry_sha256']
                or row.get('id')!=digest([VERSION,sha,number,specification['key'],row['geometry_pdf_native']])):
            raise ValueError('Reviewed marking geometry or source witness changed')
        if 'annotation' in specification:
            from .planning_theming_notes import validate
            note=validate(row.get('semantic_evidence'))
            if note['source_annotation_sha256']!=expected['source_annotation_sha256']:raise ValueError('Theming level/queue relationship changed')
        elif row.get('semantic_evidence') is not None:raise ValueError('Unsupported added marking semantics')
        if specification['role']=='queue_area':
            if not row['semantic_evidence']['claim']['queueing_below_stated'] or row.get('queue_area_context')!=specification['queue_area_context']:
                raise ValueError('Queue extent/user interpretation changed')
        elif row.get('queue_area_context') is not None:raise ValueError('Unsupported added queue area')
    return value


def side_lines(centre,offset=1):
    """Per-segment display offsets retain all branches at projected crossings."""
    parts=list(centre.geoms) if centre.geom_type=='MultiLineString' else [centre];lines=[]
    for part in parts:
        coords=list(part.coords)
        for sign in (-1,1):
            prior=None
            for a,b in zip(coords,coords[1:]):
                dx=b[0]-a[0];dy=b[1]-a[1];length=math.hypot(dx,dy)
                if length==0:continue
                nx=-dy/length*offset*sign;ny=dx/length*offset*sign
                start=(a[0]+nx,a[1]+ny);end=(b[0]+nx,b[1]+ny)
                if prior is not None and prior!=start:lines.append(LineString([prior,start]))
                lines.append(LineString([start,end]));prior=end
    return MultiLineString(lines) if lines else MultiLineString()


def line_cells(geometry,*,cancelled=lambda:False,charge=lambda:None):
    """Half-open grid traversal, including every crossed cell without buffering."""
    if geometry.geom_type=='Point':
        charge();yield math.floor(geometry.x),math.floor(geometry.y);return
    parts=list(geometry.geoms) if geometry.geom_type=='MultiLineString' else [geometry]
    for part in parts:
        coordinates=list(part.coords)
        for a,b in zip(coordinates,coordinates[1:]):
            if cancelled():raise CancelledError('Plan marking rasterisation cancelled')
            x,y=math.floor(a[0]),math.floor(a[1]);ex,ey=math.floor(b[0]),math.floor(b[1]);dx=b[0]-a[0];dy=b[1]-a[1]
            sx=1 if dx>0 else -1;sy=1 if dy>0 else -1
            tx=((x+1-a[0]) if dx>0 else (a[0]-x))/abs(dx) if dx else math.inf
            ty=((y+1-a[1]) if dy>0 else (a[1]-y))/abs(dy) if dy else math.inf
            ix=1/abs(dx) if dx else math.inf;iy=1/abs(dy) if dy else math.inf
            charge();yield x,y
            while (x,y)!=(ex,ey):
                # Stop an axis once its end cell is reached (boundary endpoints).
                ax=tx if x!=ex else math.inf;ay=ty if y!=ey else math.inf
                if abs(ax-ay)<1e-12:x+=sx;y+=sy;tx+=ix;ty+=iy
                elif ax<ay:x+=sx;tx+=ix
                else:y+=sy;ty+=iy
                charge();yield x,y


def rasterize(value,transform,bounds,*,cancelled=lambda:False,max_steps=None,max_cells=20000):
    limit=LIMITS['max_raster_steps'] if max_steps is None else max_steps
    if type(limit) is not int or not 1<=limit<=LIMITS['max_raster_steps']:raise ValueError('Lower-only marking raster budget required')
    a,b,c,d=bounds;steps=0;cells={};priorities={};counts={};covered={}
    def charge():
        nonlocal steps
        steps+=1
        if steps>limit:raise ValueError('Plan marking raster budget exceeded')
    rows=[]
    for row in value['records']:
        g=transform(row['geometry_pdf_native']);rows.append((row['key'],row['role'],row['material'],g))
        if row['role']=='track_centre':rows.append((row['key']+'-sides','track_sides','blue_wool',side_lines(g,value['side_marking_offset_blocks'])))
    priority={'queue_area':-1,'support_boundaries':0,'track_sides':1,'track_centre':2,'building_boundary':3,'theming_envelope':4,'queue_below_annotation':5}
    for key,role,material,g in rows:
        counts[key]=0;covered[key]=set()
        if role=='queue_area':
            def area_cells():
                x0,z0,x1,z1=g.bounds
                for x in range(math.floor(x0),math.ceil(x1)):
                    if cancelled():raise CancelledError('Queue area rasterisation cancelled')
                    for z in range(math.floor(z0),math.ceil(z1)):
                        charge()
                        if g.covers(Point(x+.5,z+.5)):yield x,z
            samples=area_cells()
        else:samples=line_cells(g,cancelled=cancelled,charge=charge)
        for cell in samples:
            x,z=cell
            if not a<=x<c or not b<=z<d:raise ValueError('Complete plan markings exceed world platform')
            covered[key].add(cell)
            if cell not in priorities or priority[role]>priorities[cell]:
                cells[cell]={'material':material,'role':role,'feature_key':key};priorities[cell]=priority[role]
            if len(cells)>max_cells:raise ValueError('Plan marking cell budget exceeded')
    for row in cells.values():counts[row['feature_key']]+=1
    return cells,{'profile_sha256':value['profile_sha256'],'display_cells_by_feature':counts,
        'source_sample_cells_by_feature':{k:len(v) for k,v in covered.items()},'raster_steps':steps,
        'side_marking_offset_blocks':value['side_marking_offset_blocks'],'side_offset_is_source_measurement':False,
        'source_review_profile_scope':'pinned Wicker drawing only','height_reconstructed':False,
        'theming_relationships':{r['key']:r['semantic_evidence']['claim'] for r in value['records'] if r['role']=='theming_envelope'},
        'queue_route_generated':False,'queue_area_generated':any(r['role']=='queue_area' for r in value['records']),
        'queue_areas':{r['key']:{'geometry_pdf_native':r['geometry_pdf_native'],**r['queue_area_context']} for r in value['records'] if r['role']=='queue_area'}}


def write_overlay(result,paving,buildings,layout,preview,destination):
    if not result or not result['analysis_complete'] or not result['records']:return None
    from html import escape
    from shapely.affinity import affine_transform
    from .planning_building_boundaries import write_overlay as building_overlay
    base=building_overlay(buildings,paving,preview,destination)
    if not base:return None
    matrix=pymupdf.Matrix(preview['pdf_native_to_pixels']);layers=[]
    affine=(layout or {}).get('shared_frame',{}).get('native_to_nominal_local_affine')
    inverse=None
    if affine:
        a,b,d,e,x,y=affine;det=a*e-b*d
        inverse=[e/det,-b/det,-d/det,a/det,(b*y-e*x)/det,(d*x-a*y)/det]
    colours={'support_boundaries':'#80502d','track_sides':'#2459df','track_centre':'#ff8500','building_boundary':'#0875db','theming_envelope':'#a335cb','queue_below_annotation':'#eebc00','queue_area':'#eebc00'}
    order={'queue_area':-1,'support_boundaries':0,'track_sides':1,'track_centre':2,'building_boundary':3,'theming_envelope':4,'queue_below_annotation':5}
    for row in result['records']:
        g=shape(row['geometry_pdf_native']);layers.append((row['role'],g,row['label']))
        if row['role']=='track_centre' and inverse is not None:
            guides=side_lines(affine_transform(g,affine),result['side_marking_offset_blocks'])
            layers.append(('track_sides',affine_transform(guides,inverse),'One-block display side guides; not measured rails'))
    elements=[]
    for role,g,label in sorted(layers,key=lambda r:order[r[0]]):
        commands=[]
        if g.geom_type=='Point':
            q=pymupdf.Point(g.x,g.y)*matrix
            elements.append(f'<circle cx="{q.x:.4f}" cy="{q.y:.4f}" r="3" fill="#eebc00"><title>'+escape(label)+'; note anchor only, no queue route or extent</title></circle>')
            continue
        if g.geom_type=='Polygon':
            rings=[g.exterior,*g.interiors]
            for ring in rings:
                points=[pymupdf.Point(*p)*matrix for p in ring.coords]
                commands.append('M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points)+' Z')
            elements.append('<path d="'+' '.join(commands)+'" fill="#eebc00" fill-opacity="0.35" fill-rule="evenodd" stroke="none"><title>'+escape(label)+'; user-identified queue zone, internal lanes unknown</title></path>')
            continue
        for line in list(g.geoms) if g.geom_type=='MultiLineString' else [g]:
            points=[pymupdf.Point(*p)*matrix for p in line.coords]
            commands.append('M'+' L'.join(f'{p.x:.4f},{p.y:.4f}' for p in points))
        width='.8' if role=='support_boundaries' else '2.2'
        elements.append('<path d="'+' '.join(commands)+'" fill="none" stroke="'+colours[role]+'" stroke-width="'+width+'" vector-effect="non-scaling-stroke"><title>'+escape(label)+'</title></path>')
    path=Path(destination);raw=path.read_text().replace('</svg>',''.join(elements)+'</svg>').encode()
    if len(raw)>16000000:raise ValueError('Plan marking overlay byte budget exceeded')
    path.write_bytes(raw)
    return {'file':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'source_features':len(result['records']),
        'side_guides_are_source_measurements':False}
