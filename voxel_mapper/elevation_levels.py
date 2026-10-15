"""Native printed level-marker links and relative-height hypotheses, never survey datum."""
import math

import pymupdf
from shapely.geometry import shape
from shapely.affinity import affine_transform

from .clipped_plan_fills import recover as recover_fills

from .building_spec import digest
from .drawing_annotations import LEVEL
from .glyph_visibility import screen_span

VERSION='native-elevation-level-review-v1'


def extract(page,sha,number,views,*,max_checks=100000):
    if type(max_checks) is not int or not 1<=max_checks<=100000:
        raise ValueError('Bounded level review work required')
    paths=page.get_drawings(extended=True);traces=page.get_texttrace();rotation=page.rotation_matrix
    if len(paths)>100000 or len(traces)>10000 or len(views)>100 or sum(len(t['chars']) for t in traces)>500000:
        raise ValueError('Level source inventory budget exceeded')
    for view in views:
        bounds=view['display_bounds'];unit=view['nominal_metres_per_pdf_point_candidate']
        if (len(bounds)!=4 or not all(type(v) in (int,float) and math.isfinite(v) for v in bounds)
                or bounds[0]>=bounds[2] or bounds[1]>=bounds[3]
                or type(unit) not in (int,float) or not math.isfinite(unit) or not .0001<=unit<=4):
            raise ValueError('Bounded source view and nominal level scale required')
    checks=0
    def charge():
        nonlocal checks
        checks+=1
        if checks>max_checks:raise ValueError('Level source comparison budget exceeded')
    fills=[];lines=[];circles=[];claims=[];screens={}
    for i,path in enumerate(paths):
        if path.get('level',0)!=0 or path.get('layer'):continue
        items=path.get('items',[])
        if path['type']!='s' or path.get('stroke_opacity')!=1 or path.get('dashes') not in (None,'[] 0'):continue
        if len(items)==1 and items[0][0]=='l':
            a,b=[p*rotation for p in items[0][1:3]]
            if abs(a.y-b.y)<=1e-6 and abs(a.x-b.x)>1:
                lines.append((i,[[a.x,a.y],[b.x,b.y]]))
        if len(items)!=4 or any(item[0]!='c' for item in items):continue
        bounds=pymupdf.Rect(path['rect'])*rotation;radius=(bounds.width+bounds.height)/4
        if not 3<=radius<=20 or abs(bounds.width-bounds.height)>.02*radius:continue
        if math.dist(items[0][1],items[-1][-1])>.3:continue
        circles.append((i,bounds,radius))
    if circles:
        recovered=recover_fills(page,sha,number)
        for fill in recovered['candidates']:
            if list(fill['fill_color'])!=[0.,0.,0.]:continue
            geometry=affine_transform(shape(fill['geometry']),[rotation.a,rotation.c,rotation.b,rotation.d,rotation.e,rotation.f])
            fills.append((fill['paint_ordinal'],list(geometry.bounds),fill))
    if len(circles)>128 or len(fills)>4096 or len(lines)>10000:raise ValueError('Level marker inventory budget exceeded')
    for i,span in enumerate(traces):
        text=''.join(chr(c[0]) for c in span['chars']).strip();match=LEVEL.search(text)
        if match:
            claims.append((i,span,text,float(match[1].replace(' ','')),text[:match.start(1)].rstrip(' +')))
    records=[]
    for ordinal,bounds,radius in circles:
        center=(bounds.tl+bounds.br)*.5;quadrants=[]
        for identity,rectangle,source_fill in fills:
            charge();box=pymupdf.Rect(rectangle);mid=(box.tl+box.br)*.5
            if not pymupdf.Rect(bounds.x0-.3,bounds.y0-.3,bounds.x1+.3,bounds.y1+.3).contains(box):continue
            if abs(box.width-radius)>.3 or abs(box.height-radius)>.3:continue
            if min(abs(box.x0-center.x),abs(box.x1-center.x))>.3 or min(abs(box.y0-center.y),abs(box.y1-center.y))>.3:continue
            quadrants.append((identity,1 if mid.x>center.x else -1,1 if mid.y>center.y else -1,source_fill))
        if len(quadrants)!=2 or quadrants[0][1]!=-quadrants[1][1] or quadrants[0][2]!=-quadrants[1][2]:continue
        leaders=[]
        for identity,endpoints in lines:
            charge()
            distance=min(math.dist(p,(x,center.y)) for p in endpoints for x in (bounds.x0,bounds.x1))
            if distance<=.3:leaders.append({'source_path_ordinal':identity,'display_endpoints':endpoints,
                'marker_boundary_endpoint_distance_pdf_points':distance})
        labels=[]
        for identity,span,text,value,label in claims:
            charge();box=pymupdf.Rect(span['bbox'])*rotation
            left=0<=bounds.x0-box.x1<=2*radius
            right=0<=box.x0-bounds.x1<=2*radius
            if not (left or right) or not 0<=center.y-box.y1<=radius:continue
            if identity not in screens:screens[identity]=screen_span(page,span)
            labels.append({'trace_index':identity,'text':text,'level_label_candidate':label,
                'value_m_candidate':value,'bbox_display_points':list(box),
                'glyph_screen_status':screens[identity]['status']})
        scope=[]
        for view in views:
            charge();box=pymupdf.Rect(view['display_bounds'])
            if box.y0<=center.y<=box.y1 and (0<=box.x0-center.x<=128 or 0<=center.x-box.x1<=128):scope.append(view)
        record={'source_circle_path_ordinal':ordinal,'source_quadrant_path_ordinals':[q[0] for q in quadrants],
            'source_circle_paint_seqno':paths[ordinal]['seqno'],
            'source_quadrant_fills':[q[3] for q in quadrants],
            'marker_visibility_verified':False,
            'circle_bbox_display_points':list(bounds),'label_candidates':labels,'datum_line_candidates':leaders,
            'view_key_candidates':[v['view_key_candidate'] for v in scope],
            'status':'withheld_nonunique_level_label_line_or_view','vertical_datum_verified':False,
            'floor_role_verified':False,'source_geometry_changed':False}
        if len(labels)==1 and len(leaders)==1 and len(scope)==1:
            if labels[0]['glyph_screen_status']!='raster_consistent_candidate':record['status']='withheld_level_label_visibility'
            else:
                record.update(status='unverified_native_level_reference_candidate',label=labels[0],
                    datum_y_display_points=leaders[0]['display_endpoints'][0][1],
                    view_key_candidate=scope[0]['view_key_candidate'],
                    nominal_metres_per_pdf_point_candidate=scope[0]['nominal_metres_per_pdf_point_candidate'],
                    reference_line_extension_across_view_verified=False)
        record['id']=digest(record);records.append(record)
    return {'version':VERSION,'document_sha256':sha,'page':number,'records':records,'checks':checks,
        'coordinate_frame':'source_display_pdf_points_y_down','vertical_datum_verified':False,
        'physical_level_identity_verified':False,'world_geometry_additions':0}


def relative_reference(review,view_key):
    records=[r for r in review.get('records',[]) if r.get('view_key_candidate')==view_key
        and r['status']=='unverified_native_level_reference_candidate']
    shop=[r for r in records if r['label']['level_label_candidate'].casefold()=='shop level']
    result={'status':'withheld_nonunique_or_missing_shop_level','level_pair_checks':[],
        'physical_floor_role_verified':False,'vertical_datum_verified':False,
        'document_sha256':review.get('document_sha256'),'page':review.get('page'),'view_key_candidate':view_key,
        'source_level_review_sha256':digest(review),'source_level_units_verified':False}
    if len(shop)!=1:return result
    for i,a in enumerate(records):
        for b in records[:i]:
            if a['nominal_metres_per_pdf_point_candidate']!=b['nominal_metres_per_pdf_point_candidate']:continue
            printed=a['label']['value_m_candidate']-b['label']['value_m_candidate']
            nominal=(b['datum_y_display_points']-a['datum_y_display_points'])*a['nominal_metres_per_pdf_point_candidate']
            result['level_pair_checks'].append({'level_reference_ids':[a['id'],b['id']],
                'printed_difference_m_candidate':printed,'nominal_geometry_difference_m':nominal,
                'difference_residual_m':nominal-printed,'within_level_discovery_tolerance':abs(nominal-printed)<=.01})
    if any(not p['within_level_discovery_tolerance'] for p in result['level_pair_checks']):
        result['status']='withheld_conflicting_relative_level_scale';return result
    result.update(status='unverified_source_relative_shop_level',reference_id=shop[0]['id'],
        datum_y_display_points=shop[0]['datum_y_display_points'],
        nominal_metres_per_pdf_point_candidate=shop[0]['nominal_metres_per_pdf_point_candidate'],
        level_scale_check_available=bool(result['level_pair_checks']))
    return result
