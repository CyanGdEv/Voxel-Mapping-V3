"""Explicit flat-section tunnel shells; no guessed width, height or portals."""
import math
from shapely.geometry import Point


def validate_section(section, total_height):
    if not isinstance(section, dict) or section.get('shape') != 'flat_rectangular':
        raise ValueError('Tunnel requires an explicit supported flat rectangular section')
    values = {}
    for key in ('floor_thickness_m', 'roof_thickness_m', 'wall_thickness_m', 'clear_height_m'):
        value = float(section[key])
        if not math.isfinite(value) or not 0 < value <= 30:
            raise ValueError('Invalid tunnel '+key)
        values[key] = value
    if values['clear_height_m'] < 2 or abs(values['floor_thickness_m']+values['clear_height_m']+values['roof_thickness_m']-total_height) > 1e-6:
        raise ValueError('Tunnel clear height and floor/roof thickness must match total height')
    return values


def occupied(geometry, centerline, section, x, z, y, base, top, resolution):
    point = Point((x+.5)*resolution, (z+.5)*resolution)
    lower, upper = y*resolution, (y+1)*resolution
    if lower < base+section['floor_thickness_m'] or upper > top-section['roof_thickness_m']:
        return True
    station = centerline.project(point)
    # Keep both declared portals open; a footprint end cap is not a wall.
    if station < max(resolution, section['wall_thickness_m']) or centerline.length-station < max(resolution, section['wall_thickness_m']):
        return False
    return geometry.boundary.distance(point) < max(resolution, section['wall_thickness_m'])
