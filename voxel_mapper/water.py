"""Bounded lake-surface estimates; terrain rasters are not bathymetry."""
import math
import statistics
from shapely.geometry import Point


def surface_level(geometry, terrain):
    """Require a consistent set of interior raster samples, never infer depth."""
    if terrain is None:
        return None, 'No terrain evidence for water surface elevation'
    left,bottom,right,top = geometry.bounds
    values = []
    for i in range(9):
        for j in range(9):
            x = left + (i+.5)*(right-left)/9
            z = bottom + (j+.5)*(top-bottom)/9
            if geometry.covers(Point(x,z)):
                value = terrain.sample(x,z)
                if value is not None and math.isfinite(value):
                    values.append(value)
    values.sort()
    if len(values) < 4:
        return None, 'Insufficient interior raster coverage for water surface'
    if values[int(.9*(len(values)-1))]-values[int(.1*(len(values)-1))] > 1:
        return None, 'Interior elevations are inconsistent with a level water surface'
    return statistics.median(values), 'Water level estimated from terrain raster; not a surveyed water level. Lakebed depth unavailable; no bathymetry reconstructed'
