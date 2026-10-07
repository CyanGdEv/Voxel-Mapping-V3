"""Normalize explicitly verified drawing geometry into physical world features.

This consumes adapter records, not application-site boundaries or raw PDF paths.
"""
import math
from copy import deepcopy
from shapely.geometry import shape, box
from .transport import SURFACE_MATERIALS, transport_profile

KINDS = {'plaza':'plaza','path':'path','ride_structure':'structure',
         'building_component':'structure','building':'structure'}


def physical_features(records, sources, bounds, vertical_datum, max_records=1000):
    if len(records) > max_records:
        raise ValueError('Planning geometry record budget exceeded')
    features, decisions, identifiers = [], [], set()
    for record in records:
        identifier = record.get('id')
        try:
            if not isinstance(identifier,str) or not identifier or identifier in identifiers:
                raise ValueError('Missing or duplicate planning component identity')
            identifiers.add(identifier)
            source = record.get('source_id')
            if source not in sources:
                raise ValueError('Unregistered planning source')
            if sources[source].get('license')=='copyright-consultation-only' or sources[source].get('reuse_status')=='consultation_only':
                raise ValueError('Registered source restricts geometry reuse to consultation')
            for key in ('reuse_allowed','registration_verified','as_built_verified'):
                if record.get(key) is not True:
                    raise ValueError(key+' is not confirmed')
            if not record.get('document_id') or not record.get('verification_reference'):
                raise ValueError('Missing document identity or verification reference')
            kind = KINDS.get(record.get('feature_type'))
            if kind is None:
                raise ValueError('Unknown drawing feature semantics')
            if len(str(record['geometry'])) > 1_000_000:
                raise ValueError('Drawing component coordinate budget exceeded')
            geometry = shape(record['geometry'])
            if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.is_empty or not geometry.is_valid or geometry.has_z:
                raise ValueError('Expected a valid registered 2D polygon with holes preserved')
            if not box(*bounds).covers(geometry):
                raise ValueError('Drawing component crosses acquisition bounds')
            props = {'kind':kind,'source_id':source,'planning_semantic_kind':record['feature_type'],
                     'material_warnings':['Drawing material unspecified; generic Minecraft material assumed'],
                     'planning_geometry_evidence':{k:deepcopy(record[k]) for k in
                     ('document_id','verification_reference','reuse_allowed','registration_verified','as_built_verified')}}
            if record.get('surface') is not None:
                surface = record['surface']
                if not isinstance(surface,str) or surface.strip().lower() not in SURFACE_MATERIALS:
                    raise ValueError('Unrecognized drawing material specification')
                props['surface'] = surface.strip().lower()
                props['minecraft_material'] = SURFACE_MATERIALS[props['surface']]
            elevation = record.get('elevation')
            if record.get('surface_colour') is not None:
                props['surface:colour'] = record['surface_colour']
            if props.get('surface'):
                palette = transport_profile(props,'plaza',False)
                props['minecraft_material'] = palette['material']
                props['material_warnings'] = palette['warnings']
            if elevation is not None:
                if not vertical_datum or elevation.get('vertical_datum') != vertical_datum:
                    raise ValueError('Drawing elevation datum does not match terrain')
                base = float(elevation['base_m'])
                top = float(elevation['top_m'])
                if not math.isfinite(base) or not math.isfinite(top) or not 0 < top-base <= 120:
                    raise ValueError('Invalid component base/top elevation')
                props.update(base_elevation_m=base,height_m=top-base,vertical_datum=vertical_datum)
            elif kind == 'structure':
                raise ValueError('Structure requires explicit base/top elevation; layer is not height')
            features.append({'type':'Feature','id':'planning/'+identifier,
                             'geometry':deepcopy(record['geometry']),'properties':props})
            decisions.append({'id':identifier,'status':'accepted_verified_adapter_record'})
        except (ValueError,KeyError,TypeError,OverflowError) as error:
            decisions.append({'id':identifier,'status':'withheld','reason':str(error)})
    return features, decisions
