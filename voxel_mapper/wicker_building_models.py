"""Bounded station/pre-show review meshes for the existing local-building adapter."""
from copy import deepcopy


def rectangular_model(width,length,eave,ridge,roof='gable',openings=()):
    if not (1<width<30 and 1<length<40 and 1<eave<=ridge<15):
        raise ValueError('Bounded positive building dimensions required')
    if roof not in ('gable','pyramid'):raise ValueError('Unsupported roof form')
    x,z=width/2,length/2
    outline=[[-x+.4,-z+.4,0],[-x+.4,z-.4,0],[x-.4,z-.4,0],[x-.4,-z+.4,0]]
    vertices=[];triangles=[]
    for a,b in zip(outline,outline[1:]+outline[:1]):
        i=len(vertices);vertices.extend([a,b,[b[0],b[1],eave],[a[0],a[1],eave]])
        triangles.extend([[i,i+1,i+2],[i,i+2,i+3]])
    corners=[[-x,-z,eave],[-x,z,eave],[x,z,eave],[x,-z,eave]]
    if roof=='pyramid':
        rv=corners+[[0,0,ridge]];rt=[[i,(i+1)%4,4] for i in range(4)]
    else:
        rv=corners+[[0,-z,ridge],[0,z,ridge]]
        rt=[[0,1,5],[0,5,4],[4,5,2],[4,2,3]]
    doors=[]
    for side,centre,span,height in openings:
        if span<=0 or height<=0 or height>=eave:raise ValueError('Opening must fit below eaves')
        normal=outline[0][0] if side=='x-' else outline[2][0] if side=='x+' else outline[0][1] if side=='z-' else outline[1][1]
        ends=[[normal,centre-span/2,0],[normal,centre+span/2,0]] if side.startswith('x') else [[centre-span/2,normal,0],[centre+span/2,normal,0]]
        limit=(length-.8)/2 if side.startswith('x') else (width-.8)/2
        if abs(centre)+span/2>limit:raise ValueError('Opening lies outside wall')
        doors.append({'id':f'{side}/{centre}','endpoints':ends,'width_metres':span,'height_metres':height,
                      'status':'illustrative aperture pending exact floor/elevation binding'})
    return {'coordinate_frame':'local source x/short-z plane, third coordinate height; metres',
            'outer_wall_base_outline':outline,'opening_base_segments':doors,
            'wall_mesh':{'vertices':vertices,'triangles':triangles},
            'roof_mesh':{'vertices':rv,'triangles':rt},'world_placement_eligible':False,
            'roof_palette':{'full':'oak_planks','bottom':'oak_slab','top':'oak_slab_top'},
            'dimensions':{'roof_width_m':width,'roof_length_m':length,'eave_m':eave,'ridge_m':ridge,'roof_form':roof},
            'limitations':['Four-decimetre roof overhang/inset is a review estimate.',
                           'Heights and apertures remain elevation-informed review parameters, not measured/as-built dimensions.']}


def station_parts(outline_review):
    """Retain the actual roof-plan rectangles; no stretch of source geometry."""
    measurements=outline_review['measurements']
    roof=next(m for m in measurements if m['role']=='station_main_roof')
    corners=roof['geometry']['coordinates'][0][:-1]
    centre=[sum(p[i] for p in corners)/4 for i in (0,1)]
    xmin=min(p[0] for p in corners);xmax=max(p[0] for p in corners)
    zmin=min(p[1] for p in corners);zmax=max(p[1] for p in corners)
    scale=100*.0254/72
    # Native roof-plan boundary/ridge segments, replayed from drawing 2967-48.
    bounds={'preshow_tower':[912.8389282226562,1000.9404296875,1135.1978759765625,1223.29931640625],
            'preshow_low':[912.8389282226562,1209.0194091796875,1135.1978759765625,1450.5789794921875]}
    parts=[{'id':'station','source_plan_centre_m':centre,
            'model':rectangular_model(xmax-xmin,zmax-zmin,4.8,7.0,openings=[('z-',0,3.6,3.5),('z+',0,3.6,3.5),('x+',2,1.8,2.3)]),
            'source_outline':deepcopy(roof),'printed_levels':{'inspection':181.25,'passenger_floor':'unbound'},
            'height_basis':'Ride-building section on 2967-30; first-review estimate relative to inspection level.'}]
    for name,raw in bounds.items():
        # get_drawings() is unrotated and top-down; measured outlines are y-up.
        b=[raw[0],2384-raw[3],raw[2],2384-raw[1]]
        cx,cz=(b[0]+b[2])*scale/2,(b[1]+b[3])*scale/2
        tower=name.endswith('tower')
        model=rectangular_model((b[2]-b[0])*scale,(b[3]-b[1])*scale,
                                5.4 if tower else 2.6,8.0 if tower else 4.9,
                                'pyramid' if tower else 'gable',
                                [('x-',0,1.4,2.3),('x+',0,1.4,2.3),('z-' if tower else 'z+',0,3,2.3),('z+' if tower else 'z-',0,1.8,2.3)])
        parts.append({'id':name,'source_plan_centre_m':[cx,cz],'model':model,
                      'source_outline':{'source_sha256':'6ede3a782954b1ab9ae0442791169c25a44dcfa0a79d99fbfe8b4e4bda019047',
                                        'raw_pdf_bounds':raw,'native_pdf_bounds':b,'raw_page_height_points':2384,'coordinate_conversion':'x unchanged; y_up = 2384 - y_raw','source_boundary_drawing_indices':[6304,6305,6306,6308] if tower else [6320,6321,6323,6324],
                                        'printed_scale_metres_per_point':scale},
                      'printed_levels':{'preshow_floor':183.30,'undercroft':178.0},
                      'height_basis':'2967-30 elevations; rounded first-review eave/ridge estimates.'})
    return parts
