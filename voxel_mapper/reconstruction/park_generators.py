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


def park_registry():
    registry=default_registry()
    aliases={'path':'paving','plaza':'paving','fence':'wall','metal_fence':'wall','wood_fence':'wall',
             'ride_layout':'track','ride_support_member':'beam','bridge':'architectural_components',
             'flat_ride':'architectural_components','water_ride_structure':'architectural_components',
             'animal_enclosure':'architectural_components','animal_crossing':'architectural_components'}
    registry.update({name:registry[primitive] for name,primitive in aliases.items()})
    registry.update(rocks=rocks,lake=water)
    return registry
