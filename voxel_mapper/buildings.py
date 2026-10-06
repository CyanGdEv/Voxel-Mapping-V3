"""Footprint-constrained, uncertainty-labelled surface-profile building models."""
import math

import numpy as np
from shapely.geometry import Point


def reconstruct_building(geometry, resolution, ground, surface, declared_height=None,
                         base_override=None, max_checks=200_000):
    minx,minz,maxx,maxz = geometry.bounds
    xs = range(math.floor(minx/resolution),math.ceil(maxx/resolution))
    zs = range(math.floor(minz/resolution),math.ceil(maxz/resolution))
    report = {'method':'surface_profile_2_5d','status':'rejected','checks':0,
              'roof_source_id':surface.config['source_id'], 'ground_source_id':ground.config['source_id'],
              'warnings':['DSM surfaces within mapped building footprints may include vegetation or equipment',
                          'Composite survey dates vary; footprint and surface may represent different dates']}
    if len(xs)*len(zs) > max_checks:
        report['reason'] = 'building sampling budget exceeded'
        return None, report
    cells, elevations = {}, []
    total = 0
    for x in xs:
        for z in zs:
            report['checks'] += 1
            px,pz = (x+.5)*resolution,(z+.5)*resolution
            if not geometry.covers(Point(px,pz)):
                continue
            total += 1
            base, top = ground.sample(px,pz), surface.sample(px,pz)
            if base is None or top is None:
                continue
            elevations.append(base)
            if not 1.5 <= top-base <= 120:
                continue
            cells[(x,z)] = (base,top)
    report.update(total_columns=total, usable_columns=len(cells))
    if len(cells) < 4:
        report['reason'] = 'insufficient surface samples above ground'
        return None, report
    # Reject isolated tall returns rather than extending walls into single-cell spikes.
    outliers = []
    for (x,z), (base,top) in cells.items():
        adjacent = [cells[p][1] for p in [(x-1,z),(x+1,z),(x,z-1),(x,z+1)] if p in cells]
        if len(adjacent)>=3 and top-float(np.median(adjacent)) > 3:
            outliers.append((x,z))
    for key in outliers:
        del cells[key]
    report['isolated_outlier_columns'] = len(outliers)
    coverage = len(cells)/total if total else 0
    report['usable_coverage_fraction'] = coverage
    if coverage < .90 or len(cells) < 4:
        report['reason'] = 'surface coverage or plausible-height fraction below 90%'
        return None, report
    foundation = float(base_override) if base_override is not None else float(np.percentile(elevations,10))
    report['foundation_method'] = 'declared_absolute_elevation' if base_override is not None else 'terrain_10th_percentile_estimate'
    report['foundation_elevation_m'] = foundation
    heights = [top-foundation for base,top in cells.values()]
    p95 = float(np.percentile(heights,95))
    report.update(height_p95_m=p95, height_min_m=min(heights), height_max_m=max(heights))
    if declared_height is not None and abs(p95-declared_height) > max(3,declared_height*.25):
        report.update(reason='surface height conflicts with declared height',declared_height_m=declared_height)
        return None, report
    rough = []
    for (x,z),(base,top) in cells.items():
        adjacent = [cells[p][1] for p in [(x-1,z),(x+1,z),(x,z-1),(x,z+1)] if p in cells]
        if len(adjacent)>=3:
            rough.append(abs(top-float(np.median(adjacent)))>1.5)
    report['roughness_fraction'] = float(np.mean(rough)) if rough else None
    if rough and np.mean(rough)>.25:
        report['reason'] = 'irregular surface; possible canopy or complex structure requires stronger evidence'
        return None, report
    # Unknown and outlier columns are left unmodelled, never silently interpolated.
    rows = {key:(foundation,top) for key,(base,top) in cells.items() if top>foundation}
    if len(rows)/total < .90:
        report['reason'] = 'foundation estimate incompatible with surface elevations'
        return None, report
    report.update(status='accepted_unverified',modelled_columns=len(rows),omitted_columns=total-len(rows))
    report['warnings'].append('Foundation is an estimate; output is solid 2.5D geometry, not a classified 3D building mesh')
    return rows, report
