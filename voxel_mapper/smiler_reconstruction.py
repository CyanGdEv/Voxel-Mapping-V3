"""Smiler evidence audit. The rejected lift prototype cannot generate worlds.

Map order is not train direction; plan length is not 3D track length. This
module exports review geometry without track heights, supports or excavation.
"""
import argparse
import copy
import hashlib
import json
import math
from html import escape
from pathlib import Path

WITHDRAWAL = ('Smiler lift prototype withdrawn after visual review: segment 55 and '
              'the end of segment 113 were unregistered guesses, and overall ride '
              'height did not establish either lift rise. Use --audit-only; no '
              'replacement world geometry is currently approved.')


def reconstruction_audit(route, station, crs):
    """Keep source geometry separate from unresolved ride-phase assignments."""
    route = copy.deepcopy(route)
    segments = route['segments']
    if not segments:
        raise ValueError('Mapped Smiler route required')
    for i, segment in enumerate(segments):
        for key in ('start', 'end'):
            if len(segment[key]) != 2 or not all(math.isfinite(v) for v in segment[key]):
                raise ValueError('Finite local metre coordinates required')
        if math.dist(segment['end'], segments[(i+1) % len(segments)]['start']) > .01:
            raise ValueError('Closed contiguous mapped route required')
    fingerprint = hashlib.sha256(json.dumps(segments, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
    features = []
    for i, segment in enumerate(segments):
        features.append({'type': 'Feature', 'geometry': {'type': 'LineString',
                         'coordinates': [segment['start'], segment['end']]},
                         'properties': {'segment_index': i, 'osm_way_id': segment['way_id'],
                         'topological_distance_start_m': segment['station_start_m'],
                         'topological_distance_end_m': segment['station_end_m'],
                         'travel_direction': 'unresolved', 'ride_phase': 'unresolved',
                         'track_height_odn_m': None}})
    features.append({'type': 'Feature', 'geometry': station['footprint'],
                     'properties': {'osm_way_id': station['osm_way_id'],
                                    'role': 'mapped_station_footprint',
                                    'loading_level_odn_m': None}})
    for crossing in route['crossings']:
        features.append({'type': 'Feature', 'geometry': crossing['geometry'],
                         'properties': {'role': 'unresolved_crossing',
                                        'segment_indices': crossing['segment_indices'],
                                        'vertical_separation_m': None}})
    report = {'schema_version': 1, 'status': 'withheld_pending_as_built_registration',
              'prototype_status': 'withdrawn_after_user_visual_review',
              'route_sha256': fingerprint, 'segment_count': len(segments),
              'plan_length_m': route['plan_length_m'],
              'unresolved_crossing_count': len(route['crossings']),
              'direction': 'unresolved; segment indices are topological order only',
              'rejected_bindings': [{'phase': 'inclined_lift', 'segment_index': 55},
                                    {'phase': 'vertical_lift_foot', 'after_segment_index': 113}],
              'rejected_height_model': 'station slab minus 2m, plus 30m for both crests',
              'accepted_3d_controls': [], 'world_records_emitted': 0,
              'requirements': ['Register finished-ride references against mapped station and fixed site controls',
                               'Establish loading point and train travel direction',
                               'Bind lift feet, crests, drops and brakes to identified route branches',
                               'Resolve elevations and roll through all fourteen inversions and mapped crossings'],
              'limitations': ['Mapped aerial geometry may be displaced by elevated structures',
                              'Published overall height is not the rise of each lift',
                              'DSM returns are surfaces, not identified track centres',
                              'Existing station shell remains an estimated building envelope'],
              'coordinate_frame': {'units': 'metres', 'axes': 'local x east, local z north',
                                   'crs_wkt': crs, 'minecraft_z': 'negative local z'},
              'attribution': '© OpenStreetMap contributors; ODbL-1.0'}
    return report, {'type': 'FeatureCollection', 'coordinate_frame': report['coordinate_frame'],
                    'features': features}


def audit_svg(geometry):
    """Top-down review map; deliberately contains no train-direction arrows."""
    lines = [f for f in geometry['features'] if f['geometry']['type'] == 'LineString']
    points = [p for f in lines for p in f['geometry']['coordinates']]
    station = next(f for f in geometry['features'] if f['properties'].get('role') == 'mapped_station_footprint')
    points += station['geometry']['coordinates'][0]
    x0 = min(p[0] for p in points); z1 = max(p[1] for p in points)
    scale = 7
    def position(p): return (40+(p[0]-x0)*scale, 90+(z1-p[1])*scale)
    width = math.ceil((max(p[0] for p in points)-x0)*scale)+80
    height = math.ceil((z1-min(p[1] for p in points))*scale)+180
    colors = ['#1767a1','#8b3894','#1c8260','#bd5d16','#676127','#a73550','#447592','#713fac','#3d7850']
    ways = list(dict.fromkeys(f['properties']['osm_way_id'] for f in lines))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="sans-serif" fill="#172536">',
           '<text x="25" y="30" font-size="21">Smiler — mapped route audit</text>',
           '<text x="25" y="55" font-size="13">North up · local metres · direction and every track elevation unresolved</text>']
    poly = ' '.join(f'{x:.2f},{y:.2f}' for x,y in map(position,station['geometry']['coordinates'][0]))
    out.append(f'<polygon points="{poly}" fill="#eceff2" stroke="#75808d"/>')
    for f in lines:
        a,b = map(position, f['geometry']['coordinates']); props=f['properties']
        color=colors[ways.index(props['osm_way_id']) % len(colors)]
        out.append(f'<path d="M {a[0]:.2f} {a[1]:.2f} L {b[0]:.2f} {b[1]:.2f}" stroke="{color}" stroke-width="2" fill="none"><title>Segment {props["segment_index"]}; OSM way {props["osm_way_id"]}; phase unresolved</title></path>')
        i=props['segment_index']
        if i%10 == 0 or i in (55,113):
            out.append(f'<text x="{a[0]+3:.2f}" y="{a[1]-4:.2f}" font-size="10">{i}</text>')
    out.append(f'<text x="25" y="{height-55}" font-size="13">Labels identify map segments only. Previous lift bindings 55 / 113 are rejected.</text>')
    out.append(f'<text x="25" y="{height-30}" font-size="12">{escape("© OpenStreetMap contributors · ODbL-1.0 · no reconstructed track shown")}</text></g></svg>')
    return '\n'.join(out)+'\n'


def survey_observations(route, ground, surface, previous_ground):
    """Sample registered surfaces; never promote a return to a track control."""
    observations=[]
    for i, segment in enumerate(route['segments']):
        x,z=segment['start']
        levels=[sampler(x,z) for sampler in (ground,surface,previous_ground)]
        if any(v is None or not math.isfinite(v) for v in levels):
            raise ValueError('Complete finite survey and baseline coverage required')
        terrain,highest,previous=levels
        observations.append({'segment_index':i,'local_x_m':x,'local_z_m':z,
                             'ground_odn_m':terrain,'last_return_surface_odn_m':highest,
                             'surface_minus_ground_m':highest-terrain,
                             'baseline_ground_odn_m':previous,
                             'ground_change_m':terrain-previous,
                             'identified_track_height_odn_m':None})
    return observations


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--park-output',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--datum-grid',help='Retired compatibility argument; audit does not sample elevations')
    p.add_argument('--audit-only',action='store_true',help='Export review JSON, local geometry and SVG; no world changes')
    p.add_argument('--survey-pair',help='Matched survey descriptor; measure surfaces without inferring track heights')
    args=p.parse_args()
    if not args.audit_only:
        p.error(WITHDRAWAL)
    source=Path(args.park_output)
    quality=json.loads((source/'quality-report.json').read_text())
    evidence=quality['xsector_reconstruction']
    station=next(s for s in evidence['stations'] if s['name']=='The Smiler Station')
    report,geometry=reconstruction_audit(evidence['rides']['The Smiler'],station,quality['crs'])
    observations=None
    if args.survey_pair:
        from pyproj import CRS
        from .survey import activate_retained_grid
        from .terrain import Terrain
        pair=json.loads(Path(args.survey_pair).read_text())
        activate_retained_grid(pair['source'])
        surface=pair['source']['paired_surface']
        config=json.loads((source/'resolved-config.json').read_text())
        crs=CRS.from_wkt(quality['crs'])
        samplers=[]
        try:
            samplers.append(Terrain(pair['terrain'],crs,{'ea-dtm':pair['source']}))
            samplers.append(Terrain(surface['config'],crs,{'ea-dsm':surface['source']}))
            samplers.append(Terrain(config['terrain'],crs,{s['id']:s for s in config['sources']}))
            observations=survey_observations(evidence['rides']['The Smiler'],*(s.sample for s in samplers))
        finally:
            for sampler in samplers:sampler.close()
        report['survey']={'survey':pair['source']['survey'],
                          'terrain_url':pair['source']['url'],'surface_url':surface['source']['url'],
                          'archive_sha256':{'dtm':pair['source']['archive_sha256'],
                                            'dsm':surface['source']['archive_sha256']},
                          'crop_sha256':{'dtm':hashlib.sha256(Path(pair['terrain']['path']).read_bytes()).hexdigest(),
                                         'dsm':hashlib.sha256(Path(surface['config']['path']).read_bytes()).hexdigest()},
                          'datum_grid_sha256':pair['source']['coordinate_transform']['grid']['sha256'],
                          'sample_count':len(observations),
                          'ground_odn_range_m':[min(o['ground_odn_m'] for o in observations),max(o['ground_odn_m'] for o in observations)],
                          'max_abs_baseline_ground_change_m':max(abs(o['ground_change_m']) for o in observations),
                          'interpretation':'Surface observations only; no accepted track controls'}
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=False)
    (output/'smiler-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'smiler-route-local.geojson').write_text(json.dumps(geometry,indent=2)+'\n')
    (output/'smiler-route-audit.svg').write_text(audit_svg(geometry))
    if observations is not None:
        (output/'smiler-survey-observations.json').write_text(json.dumps(observations,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','segment_count','plan_length_m','unresolved_crossing_count','world_records_emitted')},indent=2))


if __name__=='__main__':main()
