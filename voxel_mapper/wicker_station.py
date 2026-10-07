"""Separate station/exit/lift preview phases; surveyed rail heights remain unknown."""
import math
import re

import numpy as np
from shapely.geometry import Polygon, Point, LineString

from .wicker_track import REVIEW_DOCUMENT

REFERENCE_URLS = [
    'https://www.towerstimes.co.uk/news/2017/07/06/mi7-returns-mid-season-update-featuring-sw8/',
    'https://www.towerstimes.co.uk/news/2018/03/09/wicker-man-meet-the-maker-at-alton-towers-resort/',
]


def drawing_floor_level(evidence, name):
    page = next(d for d in evidence['documents'] if d.get('sha256') == REVIEW_DOCUMENT)['pages'][0]
    label = next(a for a in page['annotations'] if a['text'] == name)
    x0,y0,x1,y1 = label['bbox']
    candidates = []
    for annotation in page['annotations']:
        match = re.fullmatch(r'FFL\s+(\d+(?:\.\d+)?)', annotation['text'])
        ax0,ay0,ax1,ay1 = annotation['bbox']
        if match and max(x0,ax0) < min(x1,ax1) and 0 <= ay0-y1 <= 20:
            candidates.append((float(match[1]),annotation['bbox']))
    if len(candidates) != 1:
        raise ValueError('Unique named drawing floor level required: '+name)
    return candidates[0]


def station_context(raw_osm, route, project, evidence, bindings):
    relation = next(e for e in raw_osm['elements'] if e['type'] == 'relation' and e['id'] == 17436869)
    roles = {834919981:'maintenance',834919980:'station',834919979:'pre_lift_building'}
    line = LineString([route['segments'][0]['start']]+[s['end'] for s in route['segments']])
    parts = []
    for member in relation['members']:
        if member['ref'] not in roles or member.get('role') != 'outer':
            continue
        geometry = member['geometry']
        if geometry[0] != geometry[-1]:
            raise ValueError('Station footprint must be a closed mapped ring')
        polygon = Polygon([project(c['lon'],c['lat']) for c in geometry])
        if not polygon.is_valid or not 50 <= polygon.area <= 1000:
            raise ValueError('Invalid or unbounded station footprint')
        overlap = line.intersection(polygon.buffer(.3))
        if overlap.geom_type != 'LineString' or overlap.is_empty:
            raise ValueError('One connected route passage per station footprint required')
        start,end = sorted([line.project(Point(overlap.coords[0])),line.project(Point(overlap.coords[-1]))])
        role = roles[member['ref']]
        floor,bbox = drawing_floor_level(evidence,'Maintenance' if role == 'maintenance' else 'Station')
        parts.append({'role':role,'osm_way_id':member['ref'],'polygon':polygon,
                      'station_start_m':start,'station_end_m':end,
                      'floor_level_m':floor,'floor_label_bbox':bbox,
                      'floor_status':'assumed_equal_to_station' if role == 'pre_lift_building' else 'printed_FFL'})
    if len(parts) != 3:
        raise ValueError('All three mapped station complex footprints required')
    station = next(p for p in parts if p['role'] == 'station')
    maintenance = next(p for p in parts if p['role'] == 'maintenance')
    crest = next(b for b in bindings if b['point_label'] == 'HP1')
    crest_station = crest['nearest_candidate']['station_m']
    # On this mapped route the long diagonal begins after the low station-exit turn.
    lift_segments = [s for s in route['segments'] if s['way_id'] == 1293691422
                     and s['station_start_m'] > max(p['station_end_m'] for p in parts)
                     and s['station_end_m']-s['station_start_m'] > 10
                     and s['station_start_m'] < crest_station]
    if not lift_segments:
        raise ValueError('Mapped lift diagonal unavailable')
    lift_start = min(s['station_start_m'] for s in lift_segments)
    rail = station['floor_level_m']-1.0  # Preview parameter, not a surveyed rail level.
    return {'parts':parts,'station':station,'level_start_m':maintenance['station_start_m'],
            'level_end_m':station['station_end_m'],'station_rail_level_m':rail,
            'lift_start_m':lift_start,'lift_foot_level_m':rail-2,
            'lift_crest_station_m':crest_station,'lift_crest_level_m':crest['printed_level_m'],
            'source_document_id':REVIEW_DOCUMENT,'reference_urls':REFERENCE_URLS}


def phase_controls(context):
    return [{'status':'estimated_phase_control','point_label':label,
             'nearest_candidate':{'station_m':station},'printed_level_m':height,
             'anchor_kind':'estimated_station_phase_control'}
            for label,station,height in [
                ('STATION_ENTRY',context['level_start_m'],context['station_rail_level_m']),
                ('STATION_EXIT',context['level_end_m'],context['station_rail_level_m']),
                ('LIFT_FOOT',context['lift_start_m'],context['lift_foot_level_m'])]]


def lift_profile(stations, start, end, base, crest, break_fraction=1/3, rise_fraction=.6, blend_m=4):
    """Two inclines with short slope blends; qualitative shape from construction evidence."""
    if not all(math.isfinite(v) for v in (start,end,base,crest,break_fraction,rise_fraction,blend_m)):
        raise ValueError('Finite lift parameters required')
    length = end-start
    if length <= 3*blend_m or blend_m <= 0 or crest <= base or not 0 < break_fraction < 1 or not 0 < rise_fraction < 1:
        raise ValueError('Invalid lift shape parameters')
    kink = length*break_fraction
    if min(kink,length-kink) < 2*blend_m:
        raise ValueError('Lift blend exceeds incline spans')
    first = rise_fraction/kink; second = (1-rise_fraction)/(length-kink)
    def integral(x):
        def ramp(at):
            u = np.maximum(x-at,0)
            return np.where(u < blend_m,u*u/(2*blend_m),u-blend_m/2)
        return first*ramp(0)+(second-first)*ramp(kink-blend_m/2)-second*ramp(length-blend_m)
    x = np.clip(np.asarray(stations,dtype=float)-start,0,length)
    return base+(crest-base)*integral(x)/integral(np.array(length))


def serializable_context(context):
    return {**{k:v for k,v in context.items() if k not in ('parts','station')},
            'parts':[{k:v for k,v in p.items() if k != 'polygon'} for p in context['parts']],
            'verified':False,
            'assumptions':['Printed station/maintenance FFL treated as ODN; FFL is a floor level, not a measured rail level',
                           'Station rail assumed 1 m below platform; lift foot assumed 2 m below station rail',
                           'Mapped station complex has a level rail section before a descending exit',
                           'Lift gradient change occurs at one third of its length; first incline takes 60% of rise; exact angles unknown',
                           'Hollow building shells use mapped footprints, flat median-DSM roof estimates and generic dark timber',
                           'Pre-lift building floor assumed equal to station floor; roof form, interiors and facade details are incomplete']}
