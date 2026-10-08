"""Shared metric voxel geometry; independent of park names and world export."""
import math
import numpy as np
from shapely.geometry import Point

def line_cells(line,spacing=.4):
    """Metre cells sampled along a bounded mapped line, including its endpoint."""
    if line.is_empty or not math.isfinite(line.length) or line.length>10000:raise ValueError('Invalid mapped line')
    cells={};previous=None
    for s in np.r_[np.arange(0,line.length,spacing),line.length]:
        p=line.interpolate(float(s));cell=(math.floor(p.x),math.floor(p.y))
        if previous and cell[0]!=previous[0] and cell[1]!=previous[1]:
            cells[(previous[0],cell[1])]=float(s)
        cells[cell]=float(s);previous=cell
    return cells


def roof_cells(polygon):
    a,b,c,d=polygon.bounds
    if (c-a)*(d-b)>30000:raise ValueError('Landmark footprint budget exceeded')
    return [(x,z) for x in range(math.floor(a),math.ceil(c)) for z in range(math.floor(b),math.ceil(d)) if polygon.covers(Point(x+.5,z+.5))]


def connected_segment(start,end):
    """Six-connected voxel member, including both joints."""
    current=tuple(map(math.floor,start));target=tuple(map(math.floor,end));cells=[current]
    while current!=target:
        delta=[target[i]-current[i] for i in range(3)]
        axis=max(range(3),key=lambda i:abs(delta[i]))
        nxt=list(current);nxt[axis]+=1 if delta[axis]>0 else -1
        current=tuple(nxt);cells.append(current)
    return cells


def segment_cells(start,end):
    """Grid traversal along the actual 3D segment with face-connected tie cells."""
    if len(start)!=3 or len(end)!=3 or not all(math.isfinite(v) for v in (*start,*end)):
        raise ValueError('Finite 3D endpoints required')
    current=list(map(math.floor,start));target=list(map(math.floor,end))
    delta=[end[i]-start[i] for i in range(3)]
    step=[1 if d>0 else -1 if d<0 else 0 for d in delta]
    times=[((current[i]+1 if step[i]>0 else current[i])-start[i])/delta[i] if delta[i] else math.inf for i in range(3)]
    increments=[abs(1/d) if d else math.inf for d in delta]
    if sum(abs(target[i]-current[i]) for i in range(3))>30000:raise ValueError('3D segment budget exceeded')
    yield tuple(current)
    while current!=target:
        axis=min((i for i in range(3) if current[i]!=target[i]),key=lambda i:times[i])
        current[axis]+=step[axis];times[axis]+=increments[axis]
        yield tuple(current)
