"""Source-informed, provisional access decks with terrain-bearing slab steps."""
import math
import numpy as np
from shapely.geometry import Polygon, Point, LineString


def access_geometry(matrix, translation, parts):
    scale=100*.0254/72
    def plan(points):
        return Polygon([matrix@np.array([y,x])*scale+translation for x,y in points])
    # Rotated roof page coordinates, traced from 2967-48 P1. Bounds are
    # approximately two display pixels; these are not surveyed controls.
    shapes=[('station_landing',plan([(885,685),(1043,685),(1043,869),(885,869)]),None),
            ('station_north_steps',plan([(922,685),(1001,685),(1001,718),(922,718)]),[1001,701,922,701]),
            ('station_south_steps',plan([(922,835),(1001,835),(1001,868),(922,868)]),[1001,851,922,851])]
    result=[]
    for name,poly,flight in shapes:
        line=None if flight is None else LineString([matrix@np.array([flight[i+1],flight[i]])*scale+translation for i in (0,2)])
        result.append({'id':name,'polygon':poly,'flight':line,'basis':'2967-48 roof page trace; extent and levels provisional'})
    # Entrance and southeast flight endpoints are tied to the corrected model
    # apertures. Runs are extended to obtain half-block risers on this terrain.
    for part in parts:
        if part['id']=='station':continue
        anchor=np.asarray(part['anchor_bng_m']);length=part['dimensions']['roof_length_m']
        sign=1 if part['id']=='preshow_tower' else -1
        inner=anchor+matrix@np.array([0,sign*(length/2-.4)])
        outer=inner+matrix@np.array([0,sign*7])
        line=LineString([outer,inner])
        result.append({'id':part['id']+'_entry_steps','polygon':line.buffer(1.5,cap_style=2),'flight':line,
                       'basis':'source entrance/flight side; 3 m width and 7 m run are provisional terrain connections'})
    return result


def build_access(matrix,translation,parts,terrain_sample,floor,occupied,bounds):
    rows={};audits=[];top=round(floor)
    for shape in access_geometry(matrix,translation,parts):
        poly=shape['polygon'];line=shape['flight'];start=None
        if line:
            p=list(line.coords)[0];start=math.floor(terrain_sample(*p))+1
            if start>top:raise ValueError('Access starts above entrance level')
        footprint=set()
        xmin,zmin,xmax,zmax=poly.bounds
        for x in range(math.floor(xmin),math.ceil(xmax)):
            for z in range(math.floor(zmin),math.ceil(zmax)):
                p=Point(x+.5,z+.5)
                if not poly.covers(p):continue
                if not(bounds[0]<=x<bounds[2] and bounds[1]<=z<bounds[3]):raise ValueError('Access leaves section')
                surface=top if line is None else min(top,start+math.floor((top-start)*line.project(p)/line.length*2)/2)
                ground=math.floor(terrain_sample(x+.5,z+.5))
                if ground>=surface:surface=ground+1
                deck=math.ceil(surface)-1
                if any((x,y,z) in occupied for y in range(deck+1,deck+3)):continue
                footprint.add((x,z,deck,surface))
                # A stair flight may replace part of an earlier landing. Remove
                # its old deck/rails instead of leaving a ceiling above steps.
                if line:
                    for point in [q for q in rows if q[0]==x and q[2]==z]:rows.pop(point)
                for y in range(min(ground+1,deck),deck+1):
                    if (x,y,z) in occupied:continue
                    material='stone' if y<deck else ('oak_slab' if surface%1 else 'oak_planks')
                    rows[x,y,z]={'x':x,'y':y,'z':z,'kind':'structure','material':material,'feature':'access-review/'+shape['id']}
        # Side rails only: flight ends and entrance thresholds remain open.
        for x,z,deck,surface in footprint:
            p=Point(x+.5,z+.5)
            if line and (line.project(p)<1 or line.project(p)>line.length-1):continue
            if poly.boundary.distance(p)>.65:continue
            y=deck+1
            if (x,y,z) in occupied:continue
            if any((x+dx,y,z+dz) in occupied for dx in range(-2,3) for dz in range(-2,3)):continue
            rows[x,y,z]={'x':x,'y':y,'z':z,'kind':'structure','material':'oak_fence','feature':'access-review/'+shape['id']}
        audits.append({'id':shape['id'],'geometry':poly.__geo_interface__,'basis':shape['basis'],
                       'deck_columns':len(footprint),'entrance_surface_m':top,'outer_surface_m':start,
                       'materials':'illustrative oak slab/plank/fence and stone bearing fill'})
    return rows,{'status':'provisional source-informed access review','features':audits,'cells':len(rows),
                 'limitations':['Exact queue alignment, stair gradients and passenger platform level remain unbound.',
                                'Slab steps use half-block increments; terrain intersections retain the existing terrain level.']}
