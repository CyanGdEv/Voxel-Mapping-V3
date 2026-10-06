"""Evidence-aware transport classes, dimensions and voxel material approximations."""
import math
import re

TRANSPORT_KINDS = {'road', 'path', 'sidewalk', 'queue', 'cycleway', 'steps'}
SURFACE_MATERIALS = {
    'asphalt': 'black_concrete', 'concrete': 'light_gray_concrete',
    'concrete:plates': 'light_gray_concrete', 'concrete:lanes': 'light_gray_concrete',
    'paving_stones': 'stone_bricks', 'sett': 'cobblestone', 'cobblestone': 'cobblestone',
    'wood': 'oak_planks', 'gravel': 'gravel', 'fine_gravel': 'gravel',
    'compacted': 'coarse_dirt', 'dirt': 'dirt', 'earth': 'dirt',
    'ground': 'coarse_dirt', 'grass': 'grass_block', 'sand': 'sand',
}
DEFAULT_WIDTHS = {'road': 6, 'path': 2, 'sidewalk': 2, 'queue': 1,
                  'cycleway': 2, 'steps': 2}


def transport_kind(tags):
    highway = tags.get('area:highway', tags.get('highway'))
    if not highway:
        return None
    if highway in {'construction', 'proposed', 'abandoned', 'razed'}:
        return 'inactive_transport'
    if tags.get('footway') == 'sidewalk':
        return 'sidewalk'
    if tags.get('footway') == 'queue' or tags.get('queue') == 'yes':
        return 'queue'
    if highway == 'cycleway':
        return 'cycleway'
    if highway == 'steps':
        return 'steps'
    if highway in {'footway', 'path', 'pedestrian', 'bridleway', 'corridor'}:
        return 'path'
    return 'road'


def width_metres(value):
    """Accept a single positive metric or imperial width; never use maxwidth."""
    text = str(value).strip().lower()
    feet_inches = re.fullmatch(r"(\d+(?:\.\d+)?)\s*'\s*(\d+(?:\.\d+)?)\s*\"", text)
    if feet_inches:
        feet, inches = map(float, feet_inches.groups())
        if inches >= 12:
            raise ValueError('invalid inches component')
        result = feet * .3048 + inches * .0254
    else:
        match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(m|metres|meters|ft|feet|in|inches)?', text)
        if not match:
            raise ValueError('ambiguous or unsupported width')
        result = float(match[1]) * {'ft': .3048, 'feet': .3048, 'in': .0254, 'inches': .0254}.get(match[2], 1)
    if not math.isfinite(result) or not 0 < result <= 100:
        raise ValueError('width outside supported 0–100 m range')
    return result


def transport_profile(properties, kind, is_line):
    warnings = []
    width, width_source = None, 'mapped_polygon'
    if is_line:
        for key in ('width_m', 'width', 'est_width'):
            if key not in properties:
                continue
            try:
                width = width_metres(properties[key])
                width_source = key
                if key == 'est_width' or properties.get('source:width') == 'estimated':
                    warnings.append('mapped width is an estimate')
                break
            except ValueError:
                warnings.append(f'unsupported {key} value: {properties[key]}')
        if width is None:
            width = DEFAULT_WIDTHS[kind]
            if kind == 'road' and properties.get('highway') in {'service', 'track'}:
                width = 3
            width_source = 'class_default_assumed'
            warnings.append(f'width assumed {width} m for {kind}; not surveyed')
        if width < 1:
            warnings.append('width below 1 m may disappear or widen on the metre voxel grid')
    surface = properties.get('surface')
    material = SURFACE_MATERIALS.get(surface)
    if material is None:
        material = 'black_concrete' if kind == 'road' else 'stone'
        warnings.append(f'surface {surface!r} unsupported; generic material assumed' if surface else 'surface missing; generic material assumed')
    if kind == 'steps':
        warnings.append('steps follow terrain at metre resolution; individual treads are not measured')
    return {'kind': kind, 'width_m': width, 'width_source': width_source,
            'surface_tag': surface, 'material': material,
            'material_method': 'tagged_surface_approximation' if surface in SURFACE_MATERIALS else 'assumed',
            'warnings': warnings}
