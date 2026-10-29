"""Deterministic paving tones within an already established material family.

RGB changes appearance, never the geometry or surface class. Shadows and
occlusions must be screened by the caller before supplying a colour sample.
"""
import numpy as np

VERSION = 'colour-strength-paving-v1'
PALETTES = {
    'brick_strong': (('terracotta', 55), ('mud_bricks', 20), ('oak_planks', 20), ('granite', 5)),
    'brick_faded': (('mud_bricks', 60), ('oak_planks', 25), ('terracotta', 10), ('stone', 5)),
    'asphalt_strong': (('black_concrete', 85), ('gray_wool', 15)),
    'asphalt_faded': (('gray_concrete', 80), ('gray_wool', 20)),
    'stone': (('stone_bricks', 45), ('stone', 35), ('cobblestone', 20)),
}


def strength(family, rgb):
    """Return 0=faded, 1=strong; normalise brick colour for illumination."""
    colour = np.asarray(rgb, dtype=np.float32) / 255
    r, g, b = np.moveaxis(colour, -1, 0)
    if family == 'brick':
        redness = (r - (g + b) / 2) / np.maximum((r + g + b) / 3, .04)
        return np.clip((redness - .02) / .38, 0, 1)
    if family == 'asphalt':
        lightness = .2126 * r + .7152 * g + .0722 * b
        return np.clip((.48 - lightness) / .30, 0, 1)
    if family == 'stone':
        return np.zeros_like(r)
    raise ValueError('Unknown paving family')


def coordinate_random(easting, northing, salt=0):
    """Stable native-metre hash; independent of crop, chunks and iteration order."""
    x = np.asarray(easting, dtype=np.int64).astype(np.uint64)
    z = np.asarray(northing, dtype=np.int64).astype(np.uint64)
    with np.errstate(over='ignore'):
        h = x * np.uint64(0x9E3779B185EBCA87) ^ z * np.uint64(0xC2B2AE3D27D4EB4F) ^ np.uint64(salt)
        h ^= h >> np.uint64(30)
        h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27)
    return (h & np.uint64(0xFFFFFF)).astype(np.float64) / (1 << 24)


def choose(family, rgb, easting, northing):
    """Choose one of two tonal recipes, then its constituent block material."""
    value = strength(family, rgb)
    # Coherent three-metre tonal patches prevent white-noise striping.
    variant = coordinate_random(np.floor_divide(easting, 3), np.floor_divide(northing, 3), 19) < value
    draw = coordinate_random(easting, northing, 71) * 100
    result = np.empty(np.shape(draw), dtype='U24')
    for strong in (False, True):
        palette = PALETTES['stone' if family == 'stone' else family + ('_strong' if strong else '_faded')]
        low = 0
        for material, weight in palette:
            mask = (variant == strong) & (draw >= low) & (draw < low + weight)
            result[mask] = material
            low += weight
    return result, value
