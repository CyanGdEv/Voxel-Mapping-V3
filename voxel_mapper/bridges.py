"""Conservative DSM bridge-deck candidates, never surveyed structure reconstruction."""
import math

import numpy as np
from shapely.geometry import Point


def reconstruct_bridge(centerline, footprint, resolution, ground, surface, max_checks=100_000, width_m=None):
    report = {'method':'bridge_surface_candidate','status':'rejected','checks':0,
              'ground_source_id':ground.config['source_id'],'deck_source_id':surface.config['source_id'],
              'warnings':['DSM returns can include vegetation, rails or vehicles; deck identity is not independently classified',
                          'Composite survey dates and mapped bridge dates may differ',
                          'One voxel deck thickness is assumed; no supports, railings or underside are inferred']}
    def reject(reason):
        report['reason']=reason
        return None,report
    if resolution != 1:
        return reject('Bridge candidates currently require a 1 m voxel grid')
    if ground.config.get('vertical_datum') != surface.config.get('vertical_datum') or not ground.config.get('vertical_datum'):
        return reject('Matching declared terrain/surface vertical datums required')
    if centerline.geom_type != 'LineString' or centerline.has_z or not centerline.is_valid or not centerline.is_simple or centerline.is_ring or not 4<=centerline.length<=500:
        return reject('One simple open 4–500 m bridge centerline required')
    if len(centerline.coords)>1000:
        return reject('Bridge centerline vertex budget exceeded')
    for raster in (ground,surface):
        dataset=getattr(raster,'dataset',None)
        if dataset is not None:
            if not dataset.crs.is_projected or dataset.crs.linear_units_factor[1] != 1 or max(dataset.res)>1:
                return reject('Projected metre rasters at 1 m or finer resolution required')
        elif raster.config.get('resolution_m') != 1:
            return reject('Explicit 1 m sampling resolution required')
    report['length_m']=centerline.length
    if footprint.geom_type not in ('Polygon','MultiPolygon') or footprint.has_z or not footprint.is_valid or footprint.is_empty:
        return reject('Valid nonempty bridge footprint required')
    minx,minz,maxx,maxz=footprint.bounds
    xs=range(math.floor(minx),math.ceil(maxx));zs=range(math.floor(minz),math.ceil(maxz))
    samples=math.ceil(centerline.length)+1
    if len(xs)*len(zs)+samples*3+4>max_checks:
        return reject('Bridge sampling budget exceeded')
    width=float(width_m) if width_m is not None else float('nan')
    if not math.isfinite(width) or not 1<=width<=20:
        return reject('Bridge footprint width outside supported 1–20 m range')

    def sample(x,z):
        report['checks']+=1
        base,deck=ground.sample(x,z),surface.sample(x,z)
        if base is None or deck is None or not math.isfinite(base) or not math.isfinite(deck):
            raise ValueError('Complete finite terrain and surface coverage required')
        if not -.25<=deck-base<=30:
            raise ValueError('Surface/ground clearance outside supported range')
        return base,deck

    try:
        profile=[]
        # At most 1 m spacing and three transverse samples per station.
        for distance in np.linspace(0,centerline.length,samples):
            point=centerline.interpolate(float(distance))
            before=centerline.interpolate(max(0,float(distance)-.5))
            after=centerline.interpolate(min(centerline.length,float(distance)+.5))
            dx,dz=after.x-before.x,after.y-before.y
            length=math.hypot(dx,dz)
            if length<1e-9:
                raise ValueError('Unstable bridge tangent')
            section=[]
            for offset in (-width*.4,0,width*.4):
                x,z=point.x-dz/length*offset,point.y+dx/length*offset
                if not footprint.covers(Point(x,z)):
                    raise ValueError('Transverse section leaves mapped bridge footprint')
                section.append(sample(x,z))
            decks=[p[1] for p in section]
            if max(decks)-min(decks)>.75:
                raise ValueError('Transverse surface variation exceeds 0.75 m; possible rails/canopy')
            profile.append((float(distance),section[1][0],section[1][1]))
        for left,right in zip(profile,profile[1:]):
            if abs(right[2]-left[2])/(right[0]-left[0])>.5:
                raise ValueError('Longitudinal deck slope/jump exceeds 0.5 m per metre')
        endpoint_errors=[]
        for index,inside in ((0,centerline.interpolate(1)),(-1,centerline.interpolate(centerline.length-1))):
            endpoint=centerline.interpolate(0 if index==0 else centerline.length)
            base,deck=profile[index][1:]
            if abs(deck-base)>1:
                raise ValueError('Deck endpoint does not connect to terrain within 1 m')
            dx,dz=endpoint.x-inside.x,endpoint.y-inside.y
            length=math.hypot(dx,dz)
            if length<1e-9:
                raise ValueError('Unstable endpoint approach')
            approach_base,approach_deck=sample(endpoint.x+2*dx/length,endpoint.y+2*dz/length)
            endpoint_errors.extend((abs(deck-base),abs(deck-approach_base)))
            if abs(deck-approach_base)>1 or abs(approach_deck-approach_base)>1:
                raise ValueError('Approach terrain/surface does not connect within 1 m')
        middle=[deck-base for distance,base,deck in profile if .25*centerline.length<=distance<=.75*centerline.length]
        if len(middle)<2 or sum(c>=1.5 for c in middle)/len(middle)<.5:
            raise ValueError('Insufficient interior deck clearance of at least 1.5 m')
        cells={}; elevated_cells=0
        for x in xs:
            for z in zs:
                report['checks']+=1
                if not footprint.covers(Point(x+.5,z+.5)):
                    continue
                # This column check already accounts for the sample operation.
                report['checks']-=1
                base,deck=sample(x+.5,z+.5)
                station=centerline.project(Point(x+.5,z+.5))
                closest=round(station/centerline.length*(samples-1))
                if abs(deck-profile[closest][2])>1:
                    raise ValueError('Column surface differs from longitudinal deck by more than 1 m')
                y=math.floor(deck)
                elevated_cells+=y-math.floor(base)>=2
                cells[(x,z)]=(deck,deck+1)
        if not cells or not elevated_cells:
            raise ValueError('No resolvable two-block clearance after metre voxelisation')
        for (x,z),(deck,_) in cells.items():
            for neighbor in ((x+1,z),(x,z+1)):
                if neighbor in cells and abs(math.floor(deck)-math.floor(cells[neighbor][0]))>1:
                    raise ValueError('Voxel deck contains a disconnected height jump')
        visited=set();pending=[next(iter(cells))]
        while pending:
            cell=pending.pop()
            if cell in visited:
                continue
            visited.add(cell);x,z=cell
            pending.extend(n for n in ((x-1,z),(x+1,z),(x,z-1),(x,z+1)) if n in cells and n not in visited)
        if len(visited)!=len(cells):
            raise ValueError('Voxelized bridge footprint is disconnected; no gap interpolation')
        report.update(status='accepted_unverified',modelled_columns=len(cells),
                      maximum_clearance_m=max(deck-base for _,base,deck in profile),
                      endpoint_max_error_m=max(endpoint_errors),deck_min_m=min(p[2] for p in profile),
                      deck_max_m=max(p[2] for p in profile),assumed_deck_thickness_blocks=1)
        return cells,report
    except ValueError as error:
        return reject(str(error))
