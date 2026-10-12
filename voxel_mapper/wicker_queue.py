"""Native-plan queue walkway review; no survey acceptance is inferred."""
import hashlib
import math
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon,Point,LineString
from .generation_cycles import file_hash

FLOOR_SHA='08afa2513a3cb9ab35b515bcdbd5acb16b125ca5e5ffcedc4e2e14a7e10d9ad3'


def source_walkway(pdf_path,scale_review):
    import pymupdf
    from .drawing_page_tools import native_inverse
    if file_hash(pdf_path)!=FLOOR_SHA or scale_review['floor_sha256']!=FLOOR_SHA:raise ValueError('Pinned floor PDF and scale review required')
    furniture=np.asarray(scale_review['roof_to_floor_matrix_row_convention'])
    if furniture.shape!=(3,2) or scale_review['heldout_max_residual_pdf_points']>.25:raise ValueError('Validated page reduction required')
    with pymupdf.open(pdf_path) as pdf:
        page=pdf[0];paths=page.get_drawings();matrix=native_inverse(page);segments=[]
        for ordinal in (601,602,603,604):
            items=paths[ordinal]['items']
            if len(items)!=1 or items[0][0]!='l':raise ValueError('Queue boundary strokes changed')
            segments.append([list(pymupdf.Point(p)*matrix) for p in items[0][1:]])
    for i in range(4):
        if not np.allclose(segments[i][1],segments[(i+1)%4][0],atol=.01,rtol=0):raise ValueError('Queue outline is not closed')
    native=np.asarray([s[0] for s in segments]);roof=(native-furniture[2])@np.linalg.inv(furniture[:2])
    polygon=Polygon(roof*(100*.0254/72))
    if not polygon.is_valid or not 20<polygon.area<100:raise ValueError('Unexpected queue footprint')
    lengths=sorted(LineString([polygon.exterior.coords[i],polygon.exterior.coords[i+1]]).length for i in range(4))
    return polygon,{'document_sha256':FLOOR_SHA,'page':1,'paint_ordinals':[601,602,603,604],
        'native_pdf_corners_y_up':native.tolist(),'source_dimensions_m':[lengths[0],lengths[-1]],'area_m2':polygon.area,
        'source_polygon_sha256':hashlib.sha256(polygon.normalize().wkb).hexdigest(),
        'identity_basis':'2967-21 P1 queue walkway callout and visually inspected closed four-stroke outline',
        'scale_basis':'Retained floor-to-roof page furniture normalization; no geographic survey acceptance',
        'source_state':'2016 proposed planning drawing; current/as-built state unverified'}


def placement(polygon,station_review):
    station=next(p for p in station_review['parts'] if p['id']=='station')
    theta=math.radians(station['rotation_degrees']);matrix=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    roof=Polygon(station['source_outline']['geometry']['coordinates'][0])
    translation=np.asarray(station['anchor_bng_m'])-matrix@np.asarray(roof.centroid.coords[0])
    return Polygon([matrix@np.asarray(p)+translation for p in polygon.exterior.coords])


def raster_review(polygon,surface,protected,*,rails=False):
    """Saved-world surface callback; inferred rails stay outside the walkway."""
    rows={};foot={};skipped=0
    xmin,zmin,xmax,zmax=polygon.bounds
    for x in range(math.floor(xmin),math.ceil(xmax)):
        for z in range(math.floor(zmin),math.ceil(zmax)):
            if not polygon.covers(Point(x+.5,z+.5)):continue
            if (x,z) in protected:skipped+=1;continue
            y=surface(x,z)
            if y is None:skipped+=1;continue
            foot[x,z]=y;rows[x,y,z]={'x':x,'y':y,'z':z,'material':'stone','kind':'path','feature':'queue-walkway'}
    if rails and foot:
        ring=list(polygon.exterior.coords);longest=max((LineString([ring[i],ring[i+1]]) for i in range(len(ring)-1)),key=lambda l:l.length)
        for x in range(math.floor(xmin)-1,math.ceil(xmax)+1):
            for z in range(math.floor(zmin)-1,math.ceil(zmax)+1):
                point=Point(x+.5,z+.5)
                if (x,z) in protected or polygon.covers(point) or polygon.distance(point)>.55:continue
                at=longest.project(point)
                if at<1 or at>longest.length-1:continue
                y=surface(x,z)
                if y is None:continue
                rows[x,y+1,z]={'x':x,'y':y+1,'z':z,'material':'oak_fence','kind':'structure','feature':'queue-rail-proxy'}
    rises=[abs(y-foot[x+dx,z+dz]) for (x,z),y in foot.items() for dx,dz in [(1,0),(0,1)] if (x+dx,z+dz) in foot]
    return rows,{'paving_columns':len(foot),'protected_or_missing_columns':skipped,
                 'maximum_neighbor_rise_blocks':max(rises,default=0),'rail_cells':sum(r['material']=='oak_fence' for r in rows.values()),
                 'paving_basis':'Whole source polygon; no bound finish label, stone per user default',
                 'rail_basis':'Optional inferred one-block oak-fence proxy outside path; not a verified source specification'}
