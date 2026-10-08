"""Smiler first visible track pass: reviewed lift hypotheses, not a full course.

The manufacturer labels both lifts in an Alton Towers perspective layout, but
its example dimensions differ from the finished ride. Mapped segment bindings
and absolute levels therefore remain explicit hypotheses. Vertical lift uses a
true 3D segment with repeated horizontal coordinates, not a height function of
horizontal distance. No unreviewed crossing branch supplies inversion heights.
"""
import argparse
import copy
import json
import math
from pathlib import Path

import numpy as np
from pyproj import CRS

from .terrain import Terrain
from .survey import activate_retained_grid
from .xsector import apply_overlay

REFERENCE='https://www.gerstlauer-rides.de/fileadmin/Daten/Bilder/Produkte/Achterbahnen/Infinity_Coaster/IC_Layouts/2128_AltonTowers/IC_2128_AltonTowers_02_0001.jpg'


def lift_paths(route, station_floor):
    segments=route['segments']
    # These bindings are for the retained reviewed OSM snapshot only. Reject a
    # changed route instead of silently attaching phase hypotheses elsewhere.
    required={52:1074706894,55:1074706894,59:1074706894,113:597823137,114:597823137,118:597823137}
    if not math.isfinite(station_floor) or len(segments)<119 or any(segments[i]['way_id']!=way for i,way in required.items()):
        raise ValueError('Reviewed Smiler route bindings no longer match')
    horizontal=math.dist(segments[55]['start'],segments[55]['end'])
    if not 25<horizontal<35 or not 30<math.dist(segments[113]['start'],segments[113]['end'])<40:
        raise ValueError('Lift/approach binding geometry differs from reviewed snapshot')
    foot=station_floor-2; crest=foot+30; station_rail=station_floor+1
    def point(xz,y):return [xz[0],y,xz[1]]
    first=[]
    for i in range(52,56):
        fraction=(segments[i]['station_start_m']-segments[52]['station_start_m'])/(segments[55]['station_start_m']-segments[52]['station_start_m'])
        first.append(point(segments[i]['start'],station_rail+(foot-station_rail)*fraction))
    first.append(point(segments[55]['end'],crest))
    for i in range(56,60):first.append(point(segments[i]['end'],crest))
    tower=segments[113]['end']
    second=[point(segments[113]['start'],foot),point(tower,foot),point(tower,crest)]
    for i in range(114,119):second.append(point(segments[i]['end'],crest))
    return [{'name':'inclined_lift_and_approach','points_xyz_m':first,'lift_span_index':3},
            {'name':'vertical_lift_and_approach','points_xyz_m':second,'lift_span_index':1}],{
                'status':'reviewed_horizontal_phase_hypotheses_with_estimated_height',
                'reference_url':REFERENCE,'inclined_lift_segment_index':55,'vertical_lift_foot_after_segment_index':113,
                'station_rail_odn_m':station_rail,'lift_foot_odn_m':foot,'crest_odn_m':crest,'lift_rise_m':30,
                'inclined_lift_angle_deg':math.degrees(math.atan2(30,horizontal)),
                'vertical_lift_angle_deg':90,'width_blocks':1,'representation':'centreline, not measured gauge',
                'limitations':['Manufacturer perspective is design evidence, not a surveyed as-built 3D model',
                               'Lift feet are estimated two metres below the ground-median station slab; crest is thirty metres above foot',
                               'Vertical-lift footprint and crest approach are provisional OSM bindings affected by aerial projection',
                               'Approach/crest shapes, supports, materials and excavation section remain estimates',
                               'Full fourteen-inversion course, loading track and station roll are not emitted in this pass']}


def sample_path(points, spacing=.2):
    values=np.asarray(points,dtype=float)
    if values.ndim!=2 or values.shape[1]!=3 or len(values)<2 or not np.all(np.isfinite(values)):
        raise ValueError('Finite xyz polyline required')
    if not 0<spacing<=.5:raise ValueError('Sampling must preserve voxel continuity')
    result=[]
    for a,b in zip(values,values[1:]):
        length=float(np.linalg.norm(b-a))
        if length<=1e-8:continue
        count=math.ceil(length/spacing)
        result.extend(a+(b-a)*(i/count) for i in range(count))
    result.append(values[-1])
    return result


def emit_lifts(route, station_floor, ground, max_records=100000):
    paths,model=lift_paths(route,station_floor)
    rows={};below=0
    def add(x,y,z,material,component):
        key=(math.floor(x),math.floor(y),math.floor(z))
        old=rows.get(key)
        if old and old['material']!='air' and material=='air':return
        if old and old['feature'].rsplit('/',1)[-1] in ('inclined_lift_and_approach','vertical_lift_and_approach') and component in ('support_columns','vertical_lift_tower'):
            return
        rows[key]={'x':key[0],'y':key[1],'z':key[2],'material':material,'kind':'structure',
                   'feature':'xsector/smiler/'+component,'source':'smiler-estimated-lift-reconstruction',
                   'material_origin':'estimated_reconstruction_void' if material=='air' else 'estimated_reconstruction_shell'}
        if len(rows)>max_records:raise ValueError('Smiler lift voxel budget exceeded')
    sampled=[]
    for path in paths:
        points=sample_path(path['points_xyz_m']); sampled.append((path,points))
        for x,y,z in points:
            h=ground(x,z)
            if h is None or not math.isfinite(h):raise ValueError('Complete finite lift terrain coverage required')
            below+=y<h
            # Visible clearance also cuts station walls and local terrain where
            # the old composite ground is above estimated ride construction.
            for dx in range(-2,3):
                for dz in range(-2,3):
                    for dy in range(-1,5):add(x+dx,y+dy,z+dz,'air','clearance')
    for path,points in sampled:
        for x,y,z in points:add(x,y,z,'black_concrete',path['name'])
    for path,points in sampled:
        travelled=0.;next_support=8.;previous=None
        for x,y,z in points:
            if previous is not None:travelled+=math.dist(previous,(x,y,z))
            previous=(x,y,z)
            if travelled<next_support:continue
            next_support+=8
            h=ground(x,z)
            # Tower chain occupies the same column as its foot; its dedicated
            # offset tower handles support, not generic centreline pillars.
            tower=paths[1]['points_xyz_m'][1]
            if math.hypot(x-tower[0],z-tower[2])<2 or y-h<4:continue
            for level in range(math.floor(h),math.floor(y)):add(x,level,z,'stone','support_columns')
    foot,crest=paths[1]['points_xyz_m'][1:3]
    for y in range(math.floor(foot[1])-1,math.floor(crest[1])+1):
        add(foot[0]+3,y,foot[2],'stone','vertical_lift_tower')
    for y in range(math.floor(foot[1]),math.floor(crest[1])+1,5):
        for dx in range(1,4):add(foot[0]+dx,y,foot[2],'stone','vertical_lift_tower')
    counts={}
    for r in rows.values():name=r['feature'].rsplit('/',1)[-1];counts[name]=counts.get(name,0)+1
    return list(rows.values()),{'status':'partial_track_lifts_only','phase_model':model,'paths':paths,
                               'components':counts,'physical_records':sum(r['material']!='air' for r in rows.values()),
                               'below_ground_samples':int(below),'sampling':'3D arc-length subdivisions <=0.2m; repeated xy vertical spans retained',
                               'unfinished':'Fourteen-inversion course and closed operating route remain unmodelled'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--park-output',required=True);p.add_argument('--datum-grid',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();source=Path(args.park_output)
    config=json.loads((source/'resolved-config.json').read_text());quality=json.loads((source/'quality-report.json').read_text())
    datum=copy.deepcopy(next(s for s in config['sources'] if s['id']=='ea-dtm'))
    datum['coordinate_transform']['grid']['file']=args.datum_grid;activate_retained_grid(datum)
    report=copy.deepcopy(quality['xsector_reconstruction'])
    station=next(s for s in report['stations'] if s['name']=='The Smiler Station')
    terrain=Terrain(config['terrain'],CRS.from_wkt(quality['crs']),{s['id']:s for s in config['sources']})
    try:rows,detail=emit_lifts(report['rides']['The Smiler'],station['floor_odn_m'],terrain.sample)
    finally:terrain.close()
    report['world_name']='Alton Towers — Smiler lift track and Oblivion draft'
    report['smiler_reconstruction']=detail;report['status']='estimated_smiler_lifts_with_oblivion_track'
    report['rides']['The Smiler']['track_generation']='partial_estimated_lift_track'
    report['spawn_minecraft_xyz']=[-790,math.ceil(detail['phase_model']['crest_odn_m'])+quality['world']['vertical_offset_blocks']+8,120]
    apply_overlay(source,args.output,rows,report)
    print(json.dumps({'smiler':detail,'world_verification':report['world_verification']},indent=2))


if __name__=='__main__':main()
