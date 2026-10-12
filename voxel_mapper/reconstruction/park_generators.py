"""Semantic dispatch to evidence-gated primitives; category names never invent dimensions."""
import math
from .generators import default_registry,number
from .model import EvidenceMissing
from .geometry import roof_cells


def rocks(feature,geometry,context):
    from .rocks import rock_cells
    height=number(feature,'height_m',context,1,8)
    lithology=feature.value('rock_type',context.sources,context.allow_estimates)
    cells,_=rock_cells(geometry,context.ground,lithology,height)
    yield from cells.items()


def water(feature,geometry,context):
    if geometry.geom_type not in ('Polygon','MultiPolygon'):raise EvidenceMissing('Water needs a footprint with holes preserved')
    top=number(feature,'surface_elevation_m',context,-1000,10000)
    bed=number(feature,'bed_elevation_m',context,-1000,10000)
    material=feature.value('bed_material',context.sources,context.allow_estimates)
    for key in ('surface_elevation_m','bed_elevation_m'):
        source=context.sources[feature.parameters[key]['source']]
        if not context.vertical_datum or source.vertical_datum!=context.vertical_datum:raise EvidenceMissing('Water/bed elevation datum mismatch')
    if not 0<top-bed<=25:raise EvidenceMissing('Explicit bounded water depth required')
    if math.ceil(top)-math.floor(bed)<2:raise EvidenceMissing('Water depth has no representable water layer at one metre resolution')
    for x,z in roof_cells(geometry):
        bottom=math.floor(bed)
        yield (x,bottom,z),material
        for y in range(bottom+1,math.ceil(top)):yield (x,y,z),'water'


def roof_surface(feature,geometry,context):
    """Rasterize an explicitly evidenced plane; never infer roof pitch or height."""
    if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.has_z:
        raise EvidenceMissing('Roof surface needs a registered 2D footprint')
    plane=feature.value('plane',context.sources,context.allow_estimates)
    if not isinstance(plane,dict):raise EvidenceMissing('Explicit roof plane required')
    origin=plane.get('origin_xy');slope=plane.get('slope_xy');height=plane.get('elevation_m')
    if not isinstance(origin,list) or not isinstance(slope,list) or len(origin)!=2 or len(slope)!=2:
        raise EvidenceMissing('Roof plane origin and slope require two coordinates')
    values=[*origin,*slope,height]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise EvidenceMissing('Finite numeric roof plane required')
    if max(map(abs,slope))>3 or not -1000<=height<=10000:
        raise EvidenceMissing('Roof plane outside bounded slope/height')
    source=context.sources[feature.parameters['plane']['source']]
    if not context.vertical_datum or source.vertical_datum!=context.vertical_datum:
        raise EvidenceMissing('Roof plane vertical datum mismatch')
    thickness=number(feature,'thickness_m',context,.05,2)
    material=feature.value('material',context.sources,context.allow_estimates)
    for polygon in getattr(geometry,'geoms',[geometry]):
        for x,z in roof_cells(polygon):
            top=math.floor(height+(x+.5-origin[0])*slope[0]+(z+.5-origin[1])*slope[1])
            for y in range(top-math.ceil(thickness)+1,top+1):yield (x,y,z),material


FAMILY_ALIASES={'path':'paving','plaza':'paving','fence':'wall','metal_fence':'wall','wood_fence':'wall',
             'ride_layout':'track','ride_support_member':'beam','bridge':'architectural_components',
             'flat_ride':'architectural_components','water_ride_structure':'architectural_components',
             'animal_enclosure':'architectural_components','animal_crossing':'architectural_components'}

def park_registry():
    from .local_buildings import local_building
    registry=default_registry()

    registry.update({name:registry[primitive] for name,primitive in FAMILY_ALIASES.items()})
    registry.update(rocks=rocks,lake=water,roof_surface=roof_surface,local_building=local_building)
    return registry
