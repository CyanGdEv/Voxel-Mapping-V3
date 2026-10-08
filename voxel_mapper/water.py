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


def estimated_bed_y(geometry,x,z,level,resolution=1,max_depth_m=3):
    """Shore-distance shelf, explicitly a visual bed estimate, not bathymetry."""
    if not all(math.isfinite(v) for v in (level,resolution,max_depth_m)) or resolution<=0 or not 1<=max_depth_m<=10:
        raise ValueError('Invalid water-bed preview dimensions')
    distance=geometry.boundary.distance(Point((x+.5)*resolution,(z+.5)*resolution))
    depth=min(max_depth_m,resolution+distance*.5)
    return math.floor(level/resolution)-max(1,math.floor(depth/resolution))


def flowing_level(geometry,terrain,x,z,resolution=1):
    """Local terrain-supported stream level; no lake-wide flattening of rivers."""
    values=[]
    p=Point((x+.5)*resolution,(z+.5)*resolution)
    if geometry.geom_type=='LineString':
        station=geometry.project(p)
        for offset in (-2,-1,0,1,2):
            q=geometry.interpolate(max(0,min(geometry.length,station+offset*resolution)))
            value=terrain.sample(q.x,q.y)
            if value is not None and math.isfinite(value):values.append(value)
    else:
        value=terrain.sample(p.x,p.y)
        if value is not None and math.isfinite(value):values.append(value)
    return statistics.median(values) if values else None
