"""Park-independent floor, wall, shell, 3D sweep and trestle generators."""
import math
from shapely.geometry import Point,LineString
from .geometry import line_cells,roof_cells,segment_cells
from .model import EvidenceMissing
from ..paving_palette import palette_block


def number(feature,key,ctx,minimum,maximum,default=None):
    value=float(feature.value(key,ctx.sources,ctx.allow_estimates,default))
    if not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError('Out of range '+key)
    return value


def ground(ctx,x,z):
    value=ctx.ground(x+.5,z+.5)
    if value is None or not math.isfinite(value):raise EvidenceMissing('Missing ground coverage')
    return math.floor(value)


def surface(feature,geom,ctx):
    if geom.geom_type=='LineString':
        width=number(feature,'width_m',ctx,.1,100)
        geom=geom.buffer(width/2,cap_style=2,join_style=2)
    if geom.geom_type not in ('Polygon','MultiPolygon'):raise EvidenceMissing('Floor needs line or polygon')
    material=feature.value('surface',ctx.sources,ctx.allow_estimates)
    for polygon in getattr(geom,'geoms',[geom]):
        for x,z in roof_cells(polygon):yield (x,ground(ctx,x,z),z),palette_block(material,x,z)


def wall(feature,geom,ctx):
    if geom.geom_type=='Polygon':geom=geom.exterior
    if geom.geom_type not in ('LineString','LinearRing'):raise EvidenceMissing('Wall needs line or polygon boundary')
    height=number(feature,'height_m',ctx,.1,100)
    material=feature.value('material',ctx.sources,ctx.allow_estimates)
    for x,z in line_cells(geom):
        base=ground(ctx,x,z)
        for y in range(base+1,base+math.ceil(height)+1):yield (x,y,z),material


def shell(feature,geom,ctx):
    if geom.geom_type!='Polygon':raise EvidenceMissing('Shell needs a polygon')
    height=number(feature,'height_m',ctx,1,100)
    material=feature.value('material',ctx.sources,ctx.allow_estimates)
    # Horizontal roof level from bounded ground samples, never an arbitrary box.
    cells=roof_cells(geom);bases={(x,z):ground(ctx,x,z) for x,z in cells}
    if not bases:raise EvidenceMissing('Empty raster footprint')
    top=max(bases.values())+math.ceil(height)
    for (x,z),base in bases.items():
        if geom.boundary.distance(Point(x+.5,z+.5))<=1:
            for y in range(base+1,top):yield (x,y,z),material
        yield (x,top,z),material


def sweep(feature,geom,ctx):
    if geom.geom_type!='LineString' or not geom.has_z:raise EvidenceMissing('Ride/cable/beam needs measured or explicitly estimated 3D route')
    material=feature.value('material',ctx.sources,ctx.allow_estimates)
    # Input GeoJSON Z is elevation; output local axes are X/elevation/north.
    points=[(p[0],p[2],p[1]) for p in geom.coords]
    for a,b in zip(points,points[1:]):
        if math.dist(a,b)>1000:raise EvidenceMissing('Unbounded route segment')
        for cell in segment_cells(a,b):yield cell,material


def trestle(feature,geom,ctx):
    if geom.geom_type!='LineString' or not geom.has_z:raise EvidenceMissing('Trestle needs deck elevation route')
    spacing=number(feature,'spacing_m',ctx,1,50);width=number(feature,'width_m',ctx,1,10)
    posts=feature.value('post_material',ctx.sources,ctx.allow_estimates)
    beams=feature.value('beam_material',ctx.sources,ctx.allow_estimates)
    points=list(geom.coords);line=LineString([(p[0],p[1]) for p in points]);distances=[0.]
    for a,b in zip(points,points[1:]):distances.append(distances[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
    if not 0<line.length<=10000:raise EvidenceMissing('Trestle horizontal route unavailable')
    import numpy as np
    for station in np.arange(0,line.length,spacing):
        p=line.interpolate(float(station));a=line.interpolate(max(0,station-.2));b=line.interpolate(min(line.length,station+.2));length=math.hypot(b.x-a.x,b.y-a.y)
        if not length:continue
        nx,nz=-(b.y-a.y)/length,(b.x-a.x)/length;top=math.floor(float(np.interp(station,distances,[p[2] for p in points])))-1
        legs=[];members={}
        for side in (-width/2,width/2):
            x,z=math.floor(p.x+side*nx),math.floor(p.y+side*nz);bottom=ground(ctx,x,z)+1
            if top<bottom:raise EvidenceMissing('Deck lacks room for trestle')
            legs.append((x,bottom,z))
            for y in range(bottom,top):members[x,y,z]=posts
        l,r=legs
        for cell in segment_cells((l[0],top,l[2]),(r[0],top,r[2])):members[cell]=beams
        for low in range(max(l[1],r[1]),top,3):
            high=min(low+3,top)
            for start,end in [((l[0],low,l[2]),(r[0],high,r[2])),((r[0],low,r[2]),(l[0],high,l[2]))]:
                for cell in segment_cells(start,end):members.setdefault(cell,posts)
        yield from members.items()


def default_registry():
    return {'paving':surface,'wall':wall,'building_shell':shell,'track':sweep,'cable':sweep,
            'beam':sweep,'trestle':trestle,'tree':tree,'shrub':shrub}


def tree(feature,geom,ctx):
    from ..foliage import tree_cells,stable_seed
    if geom.geom_type!='Point':raise EvidenceMissing('Tree needs a mapped or estimated centre')
    height=number(feature,'height_m',ctx,3,40);radius=number(feature,'crown_radius_m',ctx,1,10)
    wood=feature.value('wood',ctx.sources,ctx.allow_estimates);leaves=feature.value('leaves',ctx.sources,ctx.allow_estimates)
    profile=feature.value('profile',ctx.sources,ctx.allow_estimates)
    yield from tree_cells(geom.x,ground(ctx,math.floor(geom.x),math.floor(geom.y)),geom.y,height,radius,profile,stable_seed(feature.id),wood,leaves).items()


def shrub(feature,geom,ctx):
    from ..foliage import shrub_cells,stable_seed
    if geom.geom_type!='Point':raise EvidenceMissing('Shrub needs a mapped or estimated centre')
    radius=number(feature,'radius_m',ctx,1,6);height=number(feature,'height_m',ctx,1,5)
    flowering=feature.value('flowering',ctx.sources,ctx.allow_estimates)
    yield from shrub_cells(geom.x,ground(ctx,math.floor(geom.x),math.floor(geom.y)),geom.y,radius,height,stable_seed(feature.id),flowering).items()
