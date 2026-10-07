"""Dated ground/surface observations along the mapped ride, never track heights."""
import json
import math
from pathlib import Path

import rasterio
from pyproj.transformer import TransformerGroup

from .wicker_track import ordered_route
from .survey import activate_retained_grid


def sample_route(route, terrain, surface, spacing_m=2, max_samples=10000):
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError('Finite positive sampling spacing required')
    length = route['route_length_m']
    if not math.isfinite(length) or length <= 0 or math.ceil(length/spacing_m)+1 > max_samples:
        raise ValueError('Route sample budget exceeded or invalid length')
    stations = [i*spacing_m for i in range(math.ceil(length/spacing_m))]+[length]
    xy, segment_index = [], 0
    for station in stations:
        while station > route['segments'][segment_index]['station_end_m']:
            segment_index += 1
        segment = route['segments'][segment_index]
        fraction = (station-segment['station_start_m'])/(segment['station_end_m']-segment['station_start_m'])
        xy.append([a+fraction*(b-a) for a,b in zip(segment['start'],segment['end'])])

    def values(dataset):
        result = []
        for point, value in zip(xy, dataset.sample(xy, indexes=1, masked=True)):
            inside = dataset.bounds.left <= point[0] < dataset.bounds.right and dataset.bounds.bottom < point[1] <= dataset.bounds.top
            result.append(float(value[0]) if inside and not value.mask[0] and math.isfinite(float(value[0])) else None)
        return result

    ground, observed = values(terrain), values(surface)
    return [{'station_m': station, 'xy_epsg27700_m': point,
             'ground_odn_m': dtm, 'observed_surface_odn_m': dsm,
             'surface_above_ground_m': dsm-dtm if dtm is not None and dsm is not None else None,
             'track_elevation_m': None,
             'status': 'ground_and_surface_observations' if dtm is not None and dsm is not None else 'missing_raster_observation'}
            for station,point,dtm,dsm in zip(stations,xy,ground,observed)]


def inspect_survey(config, raw_osm, output):
    report = {'status': 'unavailable', 'world_geometry_additions': 0,
              'track_height_profile_verified': False,
              'limitations': ['DSM can observe trees, roofs, supports or track at a mapped position',
                             'Terrain beneath the mapped route is ground, not rail elevation',
                             'Mapped route and survey epoch alignment is unverified',
                             'Raster sampling preserves gaps and does not interpolate a track profile']}
    try:
        sources = {source['id']: source for source in config['sources']}
        ground_config, surface_config = config['terrain'], config['surface']
        ground_source, surface_source = sources[ground_config['source_id']], sources[surface_config['source_id']]
        survey = ground_source.get('survey')
        if not survey or survey != surface_source.get('survey'):
            raise ValueError('Matching dated terrain and surface survey identities required')
        if not all(survey.get(key) for key in ('survey_id','survey_start','survey_end')):
            raise ValueError('Survey identity and dates required')
        if any(c.get('units') != 'm' or c.get('vertical_datum') != 'ODN' for c in (ground_config,surface_config)):
            raise ValueError('Metre elevations and declared ODN required')
        activate_retained_grid(ground_source)
        ways = [e for e in raw_osm['elements'] if e.get('tags',{}).get('name') == 'Wicker Man'
                and e['tags'].get('roller_coaster') == 'track']
        group = TransformerGroup(4326,27700,always_xy=True,allow_ballpark=False)
        if not group.best_available or not group.transformers or not 0 <= group.transformers[0].accuracy <= 1:
            raise ValueError('Metre-scale horizontal transformation required')
        project = group.transformers[0]
        route = ordered_route(ways,project.transform)
        with rasterio.open(ground_config['path']) as terrain, rasterio.open(surface_config['path']) as surface:
            if any(d.crs is None or d.crs.to_epsg() != 27700 or d.count != 1 or d.res != (1,1) for d in (terrain,surface)):
                raise ValueError('Single-band native one-metre BNG rasters required')
            if terrain.transform != surface.transform or terrain.shape != surface.shape:
                raise ValueError('Matched raster grids required')
            samples = sample_route(route,terrain,surface)
        ground = [s['ground_odn_m'] for s in samples if s['ground_odn_m'] is not None]
        report.update(status='dated_ground_surface_observations', survey=survey,
                      horizontal_crs='EPSG:27700', vertical_datum='ODN',
                      source_ids=[ground_source['id'],surface_source['id']],
                      source_urls=[ground_source['url'],surface_source['url']],
                      sampling_spacing_m=2, route_length_m=route['route_length_m'],
                      sample_count=len(samples), missing_samples=sum(s['status'] == 'missing_raster_observation' for s in samples),
                      ground_range_odn_m=[min(ground),max(ground)] if ground else None,
                      samples=samples)
    except (KeyError,ValueError,TypeError,OSError,rasterio.errors.RasterioError) as error:
        report['reason'] = str(error)
    (Path(output)/'wicker-man-survey-evidence.json').write_text(json.dumps(report,indent=2))
    return report
